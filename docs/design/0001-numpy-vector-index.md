# 0001: Replace ChromaDB with a plain numpy vector index

- **Status:** Accepted, implemented 2026-11-18
- **Date:** 2026-11-18
- **Area:** Collision & Confusion Radar (`rag_engine.py`)

## Summary

The Collision Radar stores about 4,000 cards as three small vectors each and looks up the
nearest neighbours of one card at a time. We used ChromaDB for this. Measured on a real
collection, a plain numpy matrix does the same job:

| | ChromaDB 1.5.9 | numpy | Change |
|---|---|---|---|
| Vector lookups per search (3 × top-100) | 11.4 ms | 0.63 ms | **~18× faster** |
| Full `search_similar` call | 42 ms | ~31 ms (est.) | ~25% faster |
| Index load at startup | ~1.1 s | 0.06 s | **~18× faster** |
| Extra memory in the app process | +174 MB | +63 MB | **−111 MB** |
| Index on disk | 480 MB (54 MB live) | 53 MB | **−89%** |
| Extra installed packages | 62 packages, 328 MB | 0 (numpy is already a dependency) | **−328 MB** |
| Same top-100 results | n/a | 96% overlap on average | numpy is exact |

numpy uses **less** memory, not more: ChromaDB keeps a full copy of every vector in its
search index anyway, then adds its own library, SQLite cache and index graph on top.

We also found that **ChromaDB leaked about 50 MB of disk per re-index** in our usage, which
made up 399 MB of the 480 MB index (see [Disk leak](#disk-leak)).

Decision: replace ChromaDB with a small numpy-backed index behind the same
`MultiVectorRAG` interface. This is now implemented; see [Results](#results-after-the-switch),
which also covers two bugs the work uncovered.

## Context

The Collision Radar warns when a card is easy to confuse with cards you already have.
For each card it stores three vectors, all computed locally with no API calls:

| Vector | Dimensions | What it captures |
|---|---|---|
| Semantic | 3,072 | Hashed word and character-trigram features of the reading and meaning |
| Visual | 64 | Kanji components from Ideographic Description Sequences |
| Phonetic | 64 | Mora sequence of the reading |

A search embeds one card, takes the top 100 neighbours from each of the three vectors,
then re-ranks the candidates in Python (exact duplicates, shared kanji, inversions such as
会社/社会).

Scale: one user, one process, a few thousand cards. The sync is capped at 15,000 cards.

ChromaDB was chosen early because a vector database seemed like the "proper" tool. It
was never used for anything a database specifically provides:

- Embeddings are always supplied by us, so its built-in embedding models are unused.
- No metadata filters, no client/server mode, no multi-process access.
- The only calls are `upsert`, `query` (top-k), `get`, `delete` and `count`.

## Findings

### Where the time goes

For a few thousand vectors an exhaustive search is one matrix–vector product:
4,000 × 3,072 multiply-adds is about 12 million operations, which a laptop CPU finishes in
well under a millisecond. ChromaDB's approximate index (HNSW) is built to avoid scanning
millions of vectors; at our size its per-query overhead (query planning, SQLite reads for
ids and metadata, result marshalling) costs more than scanning everything.

Exhaustive search is also exact. ChromaDB's HNSW results agreed with the exact top-100 on
96% of entries on average (88% worst case). Part of the difference is approximation and
part is ties between equal scores.

The full `search_similar` call spends most of its time in our own Python re-ranking,
not in the vector store. That is why the end-to-end gain is ~25% while the lookup itself is
~18× faster. The re-ranking is the next thing to profile if search speed ever matters.

### Memory

Resident memory of the app process (`ps -o rss`), after loading the index and running 20
searches, on top of a 73 MB baseline (FastAPI, uvicorn, httpx, numpy and the kanji data):

| | Library | Index | Total over baseline | Whole process |
|---|---|---|---|---|
| ChromaDB | +22 MB | +152 MB | **+174 MB** | 246 MB |
| numpy | 0 MB | +63 MB | **+63 MB** | 136 MB |

Per card that is roughly 16 KB for numpy (12.8 KB of float32 vectors plus metadata) and
about 40 KB for ChromaDB.

Extrapolated to the 15,000-card cap (an estimate, not a measurement): about 240 MB with
numpy as designed today.

The semantic vectors are 99% zeros: 26 non-zero values out of 3,072 on average. Storing
them in 512 dimensions would cut the vectors from 12.8 KB to 2.5 KB per card, so about
5.5 KB per card with metadata, or roughly 85 MB at 15,000 cards. That is an optional
follow-up, and it needs a quality check, because fewer dimensions mean more hash collisions.

### Disk leak

Every "Sync RAG Index" deletes and recreates the three collections. ChromaDB removed them
from its SQLite catalog but left each collection's index folder on disk:

- 27 segment folders on disk, only 3 still referenced
- 399 MB orphaned, 54 MB live, plus 51 MB of SQLite

So the index grew by about 50 MB per sync, without bound. A numpy index is written as one
file per sync and replaced atomically, so this class of bug cannot happen.

### Install footprint

ChromaDB pulls in 62 packages (328 MB) that nothing else in the app needs. The largest are
`onnxruntime` (83 MB), `kubernetes` (81 MB), `chromadb` itself (59 MB) and `grpcio` (40 MB),
followed by Hugging Face tooling. For comparison, the rest of the app (FastAPI, uvicorn,
httpx, pydantic, numpy) is 17 packages and 51 MB.

`onnxruntime` also sets the pace for Python support. Its current release requires
Python 3.11+ and had no wheels for Python 3.15, so ChromaDB blocked 3.15. With it gone,
the project now requires Python 3.12+ and CI tests 3.12 through 3.15.

## Decision

Replace ChromaDB with a numpy-backed index that keeps the `MultiVectorRAG` interface,
so callers in `app.py` don't change.

## Design

**Storage:** one file, `.rag_storage/vectors.npz` ([`vector_store.py`](../../vector_store.py)), holding:

- the card ids;
- one float32 matrix per vector type (semantic, visual, phonetic), with rows in the same
  order. Vectors are L2-normalised when written, so a dot product is the cosine similarity;
- per-card metadata as a JSON string (note id, deck, word, reading, meaning, sentence,
  suspended);
- a format version.

Keeping everything in one file means one atomic `os.replace` per save. Sync statistics stay
in the existing `.rag_storage/meta.json`.

**Operations:**

- `search`: `scores = matrix @ query`, `np.argpartition` for the top k, then sort those k.
- `upsert`: replace rows whose id already exists and append the rest.
- `delete`: drop rows by id.
- `reset`: start from empty matrices.
- Writes go to a temporary file followed by `os.replace`, so a crash can never leave a
  half-written index.
- A `threading.Lock` around writes, since FastAPI may serve requests from a thread pool.

**Loading:** the files are read once at startup (about 60 ms for 4,000 cards) and kept in
memory. The kanji inverted index (`kanji_index`) is rebuilt from `meta.json`, as it is today
from ChromaDB metadata.

**Migration:** the old ChromaDB files are not read. On first start the radar reports 0
indexed cards, and one "Sync RAG Index" rebuilds the index (about 9 s for 4,000 cards). The
first sync also deletes the leftover ChromaDB files (`chroma.sqlite3` and its UUID-named
segment folders).

**Dependencies:** remove `chromadb` from `requirements.txt`. numpy, already installed as
a ChromaDB dependency, becomes a direct requirement.

## Results after the switch

Measured on the live app with the same 3,971-card collection.

Index storage, ChromaDB vs numpy:

| | ChromaDB | numpy |
|---|---|---|
| `.rag_storage` on disk | 481 MB | **54 MB** |
| Installed packages | +62 (328 MB) | **0** |

Search speed and memory are as measured in [Findings](#findings).

Measuring the sync on the first numpy version turned up two more problems, described below.
Fixing them changed the sync like this (numpy index in both columns):

| Full "Sync RAG Index" | Old card fetch | New card fetch |
|---|---|---|
| Time | 18 s | **9.3 s** |
| Peak memory during the sync | ~1.07 GB | **~400 MB** |
| Server memory right after the sync | 450 MB | **332 MB** |

The old fetch is the one the ChromaDB version used, so it had the same sync cost. A freshly
started server with the index loaded uses about 196 MB. Python keeps part of a sync's peak
memory for reuse afterwards, which is why the server sits higher right after a sync.

### Finding: the indexer downloaded HTML it never used

Indexing fetched cards with AnkiConnect's `cardsInfo`, which also returns each card's
rendered question, answer and note-type CSS. That made up 94% of the reply: 48 MB for
every 500 cards. Indexing now uses `notesInfo` (fields only) plus `getDecks` and
`areSuspended` for the card's deck and suspension state. The data is identical (all
3,971 cards, zero field differences); the transfer is about 10× smaller. Vectors are also
converted to float32 as they are built, since a 3,072-element Python list costs about
100 KB per card against 12 KB as an array.

### Finding: visual and phonetic vectors changed on every restart

The visual and phonetic vectors placed each kanji component and sound into a slot with
Python's built-in `hash()`. That function is randomised per process, so the same card got
different vectors in each run. For one card, the vectors from two runs had a cosine
similarity of 0.01 (phonetic) and 0.84 (visual).

The index is built in one process and queried in later ones, so after any restart,
including every auto-reload during development, the visual and phonetic searches compared
against a scrambled index. Results still looked reasonable, because candidates are
re-scored exactly afterwards and shared-kanji matches are added separately. But genuine
sound-alikes and look-alikes could be missed. This affected the ChromaDB version too.

The fix is a stable hash (`hashlib.blake2b`), with a test that builds the vectors under
three different hash seeds and checks they match.

## Trade-offs and risks

- **Scale.** Exhaustive search grows linearly. It stays in the low milliseconds well past
  15,000 cards, but memory with 3,072-dim semantic vectors would be about 800 MB at 50,000
  cards (about 1.9 GB with ChromaDB at its measured ~40 KB per card). Shrinking the
  semantic vectors (above) brings numpy to roughly 280 MB. If the app ever
  needed millions of vectors, an approximate index would be worth revisiting.
- **Single writer.** No locking across processes. Fine for a single-user local app; two app
  instances writing the same index folder would race.
- **Features given up.** Metadata filtering, built-in embedding models, server mode. None
  are used.
- **Own code to maintain.** [`vector_store.py`](../../vector_store.py) is about 170 lines,
  with its own tests ([`test_vector_store.py`](../../test_vector_store.py)) on top of the
  existing RAG tests.
- **Dropped field.** Card lapse counts are no longer stored in the index (`notesInfo` doesn't
  return them). Nothing in the app read them.

## Alternatives considered

- **Keep ChromaDB and work around the leak.** Deleting orphaned folders after each reset
  fixes disk growth. It doesn't touch latency, memory, install size or the Python 3.15
  block.
- **Another approximate-search library** (FAISS, hnswlib, sqlite-vec, LanceDB). These are
  built for far larger datasets than ours, so each still adds a dependency we don't need.
  Exact search is already sub-millisecond.
- **Sparse semantic vectors** (e.g. SciPy sparse matrices). They would fit the 99%-zero
  data well, but SciPy is a large dependency. Reducing dimensions in numpy gets most of the
  benefit.

## Methodology

- **Machine:** Apple M3 Pro, 18 GB RAM, macOS 27.2.1. Python 3.11.0, chromadb 1.5.9,
  numpy 2.4.6.
- **Data:** a copy of a real index, 3,989 cards, so the running app was not touched. The
  numpy index used the exact vectors exported from that ChromaDB copy.
- **Latency:** `time.perf_counter` around each lookup; 5 query words × 40 rounds after a
  warm-up; median and p95 reported. K = 100, the value the app uses.
- **Memory:** current RSS from `ps -o rss`, read in a fresh process after imports, after
  loading and after 20 searches; runs repeated with identical results.
- **Disk:** segment folders on disk were compared with the `segments` table in
  `chroma.sqlite3`.
- **Install size:** the sum of installed files for every package `chromadb` requires
  (recursively) that FastAPI, uvicorn, httpx, pydantic and numpy don't also require.
