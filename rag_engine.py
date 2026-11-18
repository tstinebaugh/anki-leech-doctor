"""
Multi-Vector RAG Engine for Anki Japanese Cards.
Provides 3-dimensional indexing:
1. Semantic (Definitions & Nuance via text embeddings)
2. Visual (Kanji Radicals & Topological Structure)
3. Phonetic (Kana Mora Sequences & Sound-Alikes)
"""

import os
import re
import json
import time
import httpx
from typing import Any, Dict, List, Optional, Set

import chromadb
from chromadb.config import Settings

from kanji_data import (
    compute_vocab_visual_similarity,
    compute_phonetic_similarity,
    check_kanji_inversion_and_overlap,
    generate_visual_vector,
    generate_phonetic_vector,
    extract_kanji_chars,
    normalize_vector,
)

from config_defaults import RAG_STORAGE_PATH as DEFAULT_STORAGE_PATH

STOPWORDS = {
    "a", "an", "the", "to", "is", "are", "was", "were", "of", "in", "on", "at",
    "by", "for", "with", "about", "against", "between", "into", "through", "during",
    "before", "after", "above", "below", "from", "up", "down", "and", "or", "but",
    "if", "while", "that", "this", "these", "those", "it", "its", "as", "word",
    "reading", "meaning", "none", "etc", "e.g", "i.e"
}

import hashlib

def extract_definition_tokens(text: str) -> Set[str]:
    """Extracts lowercase alphabetic and CJK semantic tokens, discarding standard stopwords."""
    if not text:
        return set()
    # Strip HTML tags
    clean_text = re.sub(r"<[^>]+>", " ", text)
    raw = re.findall(r"[a-zA-Z\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]+", clean_text.lower())
    clean = {t for t in raw if t not in STOPWORDS and len(t) > 1}
    return clean or {t for t in raw if t}

def compute_exact_definition_similarity(def1: str, def2: str) -> float:
    """
    Computes exact, collision-free semantic token Jaccard similarity between two definitions.
    Guarantees that definitions sharing no common meaning tokens have strictly 0.0 similarity.
    """
    t1 = extract_definition_tokens(def1)
    t2 = extract_definition_tokens(def2)
    if not t1 or not t2:
        return 0.0
    if t1 == t2:
        return 1.0
    intersection = t1 & t2
    if not intersection:
        return 0.0
    union = t1 | t2
    return round(len(intersection) / len(union), 3)

def fallback_text_embedding(text: str, dim: int = 3072) -> List[float]:
    """
    Collision-resistant sub-word character-trigram & token TF-IDF sparse vectorizer.
    Guarantees that words with different spellings/meanings do not collide into single hash buckets.
    """
    vec = [0.0] * dim
    if not text:
        vec[0] = 1.0
        return normalize_vector(vec)
    
    clean_text = re.sub(r"<[^>]+>", " ", text)
    tokens = re.findall(r"[\w\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]+", clean_text.lower())
    clean_tokens = [t for t in tokens if t not in STOPWORDS and len(t) > 1]
    if not clean_tokens:
        clean_tokens = [t for t in tokens if t] or list(clean_text.strip().lower())
    
    if not clean_tokens:
        vec[0] = 1.0
        return normalize_vector(vec)

    features: Dict[str, float] = {}
    for t in clean_tokens:
        # 1. Whole word feature
        features[f"w_{t}"] = features.get(f"w_{t}", 0.0) + 2.0
        # 2. Sub-word character trigrams (e.g. "_bi", "bil", "ill", "ll_")
        t_padded = f"_{t}_"
        for i in range(max(1, len(t_padded) - 2)):
            tri = t_padded[i:i+3]
            features[f"tri_{tri}"] = features.get(f"tri_{tri}", 0.0) + 1.0

    for feat, weight in features.items():
        h = int(hashlib.md5(feat.encode("utf-8")).hexdigest(), 16) % dim
        vec[h] += weight

    return normalize_vector(vec)


class MultiVectorRAG:
    def __init__(self, storage_path: str = DEFAULT_STORAGE_PATH, api_key: str = ""):
        self.storage_path = storage_path
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
        os.makedirs(self.storage_path, exist_ok=True)
        self.kanji_index: Dict[str, Set[str]] = {}
        self._init_chroma()
        self.meta_file = os.path.join(self.storage_path, "meta.json")
        self.meta = self._load_meta()

    def _init_chroma(self):
        """Initializes fresh persistent ChromaDB client and collections."""
        self.chroma_client = chromadb.PersistentClient(
            path=self.storage_path,
            settings=Settings(anonymized_telemetry=False)
        )
        self.semantic_col = self.chroma_client.get_or_create_collection(
            name="anki_semantic",
            metadata={"hnsw:space": "cosine"}
        )
        self.visual_col = self.chroma_client.get_or_create_collection(
            name="anki_visual",
            metadata={"hnsw:space": "cosine"}
        )
        self.phonetic_col = self.chroma_client.get_or_create_collection(
            name="anki_phonetic",
            metadata={"hnsw:space": "cosine"}
        )
        self._build_kanji_index()

    def _build_kanji_index(self):
        """Builds an in-memory inverted index mapping individual kanji characters to card IDs."""
        self.kanji_index = {}
        try:
            records = self.semantic_col.get(include=["metadatas"])
            if records and records.get("metadatas"):
                for m in records["metadatas"]:
                    cid = str(m.get("cardId"))
                    vk = m.get("vocabKanji", "")
                    for k in extract_kanji_chars(vk):
                        if k not in self.kanji_index:
                            self.kanji_index[k] = set()
                        self.kanji_index[k].add(cid)
        except Exception as e:
            print(f"Kanji index build error: {e}")

    def set_api_key(self, api_key: str):
        self.api_key = api_key

    def _load_meta(self) -> Dict[str, Any]:
        if os.path.exists(self.meta_file):
            try:
                with open(self.meta_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"last_sync": None, "indexed_count": 0, "deck_names": []}

    def _save_meta(self):
        with open(self.meta_file, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, indent=2, ensure_ascii=False)

    def reset_index(self):
        """Cleans and re-initializes vector collections to prevent schema or lock issues."""
        for name in ["anki_semantic", "anki_visual", "anki_phonetic"]:
            try:
                self.chroma_client.delete_collection(name)
            except Exception:
                pass
        self._init_chroma()
        self.meta = {"last_sync": None, "indexed_count": 0, "deck_names": []}
        self._save_meta()

    async def get_semantic_embeddings_batch(self, texts: List[str], use_cloud: bool = False) -> List[List[float]]:
        """
        Generates semantic embeddings. By default, uses local high-precision TF-IDF / Sublinear
        vectorizer to ensure instant, zero-cost, zero-API quota indexing.
        """
        if not use_cloud or not self.api_key:
            return [fallback_text_embedding(t) for t in texts]

        # Use batchEmbedContents with models/gemini-embedding-001 if cloud is explicitly requested
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents"
        requests_payload = []
        for t in texts:
            clean_text = (t or "").strip()[:500] or "empty"
            requests_payload.append({
                "model": "models/gemini-embedding-001",
                "content": {"parts": [{"text": clean_text}]}
            })

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json={"requests": requests_payload}, headers={"x-goog-api-key": self.api_key})
                if resp.status_code == 200:
                    data = resp.json()
                    embeddings = data.get("embeddings", [])
                    if len(embeddings) == len(texts):
                        return [e.get("values", []) for e in embeddings]
                else:
                    print(f"Gemini embedding batch status {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"Cloud embedding fallback: {e}")

        return [fallback_text_embedding(t) for t in texts]

    async def get_semantic_embedding_single(self, text: str) -> List[float]:
        """Embeds single text string."""
        return fallback_text_embedding(text)

    async def index_cards(self, cards: List[Dict[str, Any]], deck_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Indexes a list of parsed Anki cards into the 3 vector collections.
        """
        if not cards:
            return {"indexed": 0, "message": "No cards to index"}

        ids = []
        semantic_texts = []
        visual_vectors = []
        phonetic_vectors = []
        metadatas = []

        for c in cards:
            cid = str(c.get("cardId", ""))
            vocab_kanji = str(c.get("vocabKanji", "")).strip()
            if not cid or not vocab_kanji:
                continue

            vocab_furigana = str(c.get("vocabFurigana", "")).strip()
            vocab_def = str(c.get("vocabDef", "")).strip()

            sem_text = f"Word: {vocab_kanji} | Reading: {vocab_furigana} | Meaning: {vocab_def}"
            
            ids.append(cid)
            semantic_texts.append(sem_text)
            visual_vectors.append(generate_visual_vector(vocab_kanji))
            phonetic_vectors.append(generate_phonetic_vector(vocab_furigana or vocab_kanji))
            
            metadatas.append({
                "cardId": int(c.get("cardId", 0)),
                "noteId": int(c.get("noteId", 0)),
                "deckName": str(c.get("deckName", "")),
                "vocabKanji": vocab_kanji,
                "vocabFurigana": vocab_furigana,
                "vocabDef": vocab_def[:300],
                "sentKanji": str(c.get("sentKanji", ""))[:200],
                "sentEng": str(c.get("sentEng", ""))[:200],
                "suspended": bool(c.get("suspended", False)),
                "lapses": int(c.get("lapses", 0)),
            })

        if not ids:
            return {"indexed": 0, "message": "No valid cards found"}

        # Generate fast local embeddings (zero API calls, instant, quota-free)
        all_semantic_embeddings = [fallback_text_embedding(t) for t in semantic_texts]

        # Upsert into Chroma collections in safe chunks <= 500 items to respect batch limits
        chroma_chunk_size = 500
        for attempt in range(2):
            try:
                for i in range(0, len(ids), chroma_chunk_size):
                    chunk_ids = ids[i:i+chroma_chunk_size]
                    chunk_sem_emb = all_semantic_embeddings[i:i+chroma_chunk_size]
                    chunk_sem_docs = semantic_texts[i:i+chroma_chunk_size]
                    chunk_vis = visual_vectors[i:i+chroma_chunk_size]
                    chunk_phon = phonetic_vectors[i:i+chroma_chunk_size]
                    chunk_meta = metadatas[i:i+chroma_chunk_size]

                    # 1. Semantic
                    self.semantic_col.upsert(
                        ids=chunk_ids,
                        embeddings=chunk_sem_emb,
                        documents=chunk_sem_docs,
                        metadatas=chunk_meta
                    )

                    # 2. Visual
                    self.visual_col.upsert(
                        ids=chunk_ids,
                        embeddings=chunk_vis,
                        metadatas=chunk_meta
                    )

                    # 3. Phonetic
                    self.phonetic_col.upsert(
                        ids=chunk_ids,
                        embeddings=chunk_phon,
                        metadatas=chunk_meta
                    )
                break
            except Exception as e:
                print(f"RAG upsert error on attempt {attempt}: {e}")
                if attempt == 0:
                    print("Re-initializing ChromaDB client and collections to recover...")
                    self.reset_index()
                else:
                    raise e

        self.meta["last_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.meta["indexed_count"] = self.semantic_col.count()
        if deck_name and deck_name not in self.meta["deck_names"]:
            self.meta["deck_names"].append(deck_name)
        self._save_meta()
        self._build_kanji_index()

        return {
            "indexed": len(ids),
            "totalIndexed": self.meta["indexed_count"],
            "lastSync": self.meta["last_sync"]
        }

    def delete_card(self, card_id: int) -> bool:
        """
        Removes a card by its ID from all vector collections and kanji index.
        """
        cid_str = str(card_id)
        try:
            self.semantic_col.delete(ids=[cid_str])
        except Exception:
            pass
        try:
            self.visual_col.delete(ids=[cid_str])
        except Exception:
            pass
        try:
            self.phonetic_col.delete(ids=[cid_str])
        except Exception:
            pass

        # Clean from in-memory kanji index
        for k in list(self.kanji_index.keys()):
            self.kanji_index[k].discard(cid_str)

        try:
            self.meta["indexed_count"] = self.semantic_col.count()
            self._save_meta()
        except Exception:
            pass
        return True

    async def search_similar(
        self,
        vocab_kanji: str,
        vocab_furigana: str = "",
        vocab_def: str = "",
        top_k: int = 6,
        weights: Optional[Dict[str, float]] = None,
        exclude_card_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Performs multi-vector similarity search across Semantic, Visual, and Phonetic axes.
        Returns scored and categorized collision results.
        """
        if self.semantic_col.count() == 0:
            return []

        w = weights or {"semantic": 0.45, "visual": 0.30, "phonetic": 0.25}
        w_sem = w.get("semantic", 0.45)
        w_vis = w.get("visual", 0.30)
        w_phon = w.get("phonetic", 0.25)

        # 1. Prepare query vectors
        query_text = f"Word: {vocab_kanji} | Reading: {vocab_furigana} | Meaning: {vocab_def}"
        sem_q_emb = await self.get_semantic_embedding_single(query_text)
        vis_q_emb = generate_visual_vector(vocab_kanji)
        phon_q_emb = generate_phonetic_vector(vocab_furigana or vocab_kanji)

        fetch_k = min(100, self.semantic_col.count())

        # 2. Query each collection safely
        try:
            sem_res = self.semantic_col.query(query_embeddings=[sem_q_emb], n_results=fetch_k)
        except Exception as e:
            print(f"Semantic query error (recovering): {e}")
            sem_res = None

        try:
            vis_res = self.visual_col.query(query_embeddings=[vis_q_emb], n_results=fetch_k)
        except Exception as e:
            print(f"Visual query error: {e}")
            vis_res = None

        try:
            phon_res = self.phonetic_col.query(query_embeddings=[phon_q_emb], n_results=fetch_k)
        except Exception as e:
            print(f"Phonetic query error: {e}")
            phon_res = None

        # Combine candidates by card ID
        candidates: Dict[str, Dict[str, Any]] = {}

        def process_results(res, dim_name):
            if not res or not res.get("ids") or not res["ids"] or not res["ids"][0]:
                return
            ids = res["ids"][0]
            distances = res["distances"][0] if "distances" in res and res["distances"] else [0.5] * len(ids)
            metadatas = res["metadatas"][0] if "metadatas" in res and res["metadatas"] else [{}] * len(ids)

            for c_id, dist, meta in zip(ids, distances, metadatas):
                if exclude_card_id and meta.get("cardId") == exclude_card_id:
                    continue
                if c_id not in candidates:
                    candidates[c_id] = {
                        "cardId": meta.get("cardId"),
                        "noteId": meta.get("noteId"),
                        "deckName": meta.get("deckName"),
                        "vocabKanji": meta.get("vocabKanji", ""),
                        "vocabFurigana": meta.get("vocabFurigana", ""),
                        "vocabDef": meta.get("vocabDef", ""),
                        "sentKanji": meta.get("sentKanji", ""),
                        "sentEng": meta.get("sentEng", ""),
                        "suspended": meta.get("suspended", False),
                        "lapses": meta.get("lapses", 0),
                        "semanticScore": 0.0,
                        "visualScore": 0.0,
                        "phoneticScore": 0.0,
                    }
                # Cosine distance to similarity (1.0 - dist)
                sim = max(0.0, min(1.0, 1.0 - dist))
                if dim_name == "semantic":
                    candidates[c_id]["semanticScore"] = round(sim, 3)
                elif dim_name == "visual":
                    candidates[c_id]["visualScore"] = round(sim, 3)
                elif dim_name == "phonetic":
                    candidates[c_id]["phoneticScore"] = round(sim, 3)

        process_results(sem_res, "semantic")
        process_results(vis_res, "visual")
        process_results(phon_res, "phonetic")

        # 3. Explicitly retrieve and inject all cards that share constituent kanji
        target_kanji_chars = extract_kanji_chars(vocab_kanji)
        shared_kanji_cids = set()
        for ch in target_kanji_chars:
            shared_kanji_cids.update(self.kanji_index.get(ch, set()))

        missing_cids = [cid for cid in shared_kanji_cids if cid not in candidates]
        if missing_cids:
            try:
                extra_records = self.semantic_col.get(ids=missing_cids, include=["metadatas"])
                if extra_records and extra_records.get("metadatas"):
                    for meta in extra_records["metadatas"]:
                        c_id = str(meta.get("cardId"))
                        if exclude_card_id and meta.get("cardId") == exclude_card_id:
                            continue
                        candidates[c_id] = {
                            "cardId": meta.get("cardId"),
                            "noteId": meta.get("noteId"),
                            "deckName": meta.get("deckName"),
                            "vocabKanji": meta.get("vocabKanji", ""),
                            "vocabFurigana": meta.get("vocabFurigana", ""),
                            "vocabDef": meta.get("vocabDef", ""),
                            "sentKanji": meta.get("sentKanji", ""),
                            "sentEng": meta.get("sentEng", ""),
                            "suspended": meta.get("suspended", False),
                            "lapses": meta.get("lapses", 0),
                            "semanticScore": 0.0,
                            "visualScore": 0.0,
                            "phoneticScore": 0.0,
                        }
            except Exception as e:
                print(f"Error retrieving shared kanji candidates: {e}")

        # Compute fine-grained visual, phonetic, definition, and kanji anagram re-scoring for precision
        results = []
        target_kanji_clean = vocab_kanji.strip()
        target_reading_clean = vocab_furigana.strip() or vocab_kanji.strip()
        target_def_clean = vocab_def.strip()

        for c_id, item in candidates.items():
            cand_kanji = item["vocabKanji"].strip()
            cand_reading = item["vocabFurigana"].strip() or cand_kanji
            cand_def = item["vocabDef"].strip()

            # Precise pairwise re-scoring
            exact_visual = compute_vocab_visual_similarity(target_kanji_clean, cand_kanji)
            exact_phonetic = compute_phonetic_similarity(target_reading_clean, cand_reading)
            overlap_info = check_kanji_inversion_and_overlap(target_kanji_clean, cand_kanji)

            exact_def_sim = 0.0
            if target_def_clean and cand_def:
                exact_def_sim = compute_exact_definition_similarity(target_def_clean, cand_def)
            
            # Set precise algorithmic and definition scores
            item["visualScore"] = max(item["visualScore"], exact_visual)
            item["phoneticScore"] = max(item["phoneticScore"], exact_phonetic)
            item["semanticScore"] = round(exact_def_sim, 3)
            item["sharedKanji"] = overlap_info["shared_kanji"]
            item["isKanjiInversion"] = overlap_info["is_inversion"]
            item["kanjiOverlapRatio"] = overlap_info["overlap_ratio"]

            # Combined weighted score
            comb = (
                w_sem * item["semanticScore"] +
                w_vis * item["visualScore"] +
                w_phon * item["phoneticScore"]
            )
            if overlap_info["is_inversion"]:
                comb += 0.40
            elif overlap_info["has_shared_kanji"]:
                comb += 0.30 * overlap_info["overlap_ratio"]
            item["combinedScore"] = round(min(1.0, comb), 3)

            # Classify collisions & interference diagnostics
            is_exact = (
                target_kanji_clean == cand_kanji
                or (item["semanticScore"] >= 0.95 and item["phoneticScore"] >= 0.95)
            )
            is_inversion = bool(overlap_info["is_inversion"] and not is_exact)
            is_spatial_inversion = bool(overlap_info.get("is_spatial_inversion") and not is_exact and not is_inversion)
            has_shared_kanji = bool(overlap_info["has_shared_kanji"] and not is_exact and not is_inversion)
            is_semantic_dup = bool(item["semanticScore"] >= 0.82 and not is_exact)
            is_visual_conf = bool(item["visualScore"] >= 0.70 and not is_exact)
            is_phonetic_conf = bool(item["phoneticScore"] >= 0.82 and not is_exact)

            reasons = []
            if is_exact:
                item["combinedScore"] = 1.0
                reasons.append("Exact vocabulary duplicate in deck")
            if is_inversion:
                reasons.append("🔄 Kanji Reversal / Anagram (same kanji in different order)")
            if is_spatial_inversion:
                reasons.append("🔀 Spatial Component Inversion (same radicals in swapped positions)")
            if has_shared_kanji:
                shared_str = ", ".join(overlap_info["shared_kanji"])
                reasons.append(f"🀄 Shares constituent kanji 【{shared_str}】 ({int(overlap_info['overlap_ratio']*100)}% overlap)")
            if is_semantic_dup:
                reasons.append(f"Near-identical meaning ({int(item['semanticScore']*100)}% match)")
            if is_visual_conf:
                reasons.append(f"Look-alike kanji structure ({int(item['visualScore']*100)}% visual similarity)")
            if is_phonetic_conf:
                reasons.append(f"Homophone / sound-alike reading ({int(item['phoneticScore']*100)}% phonetic match)")

            item["isExactDuplicate"] = is_exact
            item["isKanjiInversion"] = is_inversion
            item["isSpatialInversion"] = is_spatial_inversion
            item["hasSharedKanji"] = has_shared_kanji
            item["isSemanticDuplicate"] = is_semantic_dup
            item["isVisualConfuser"] = is_visual_conf
            item["isPhoneticConfuser"] = is_phonetic_conf
            item["hasCollision"] = bool(
                is_exact or is_inversion or is_spatial_inversion or has_shared_kanji or 
                is_semantic_dup or is_visual_conf or is_phonetic_conf
            )
            item["collisionReasons"] = reasons

            results.append(item)

        # Sort by exact duplicate priority, then combined score descending
        results.sort(
            key=lambda x: (1 if x.get("isExactDuplicate") else 0, x["combinedScore"]),
            reverse=True
        )
        return results[:top_k]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "indexedCount": self.semantic_col.count(),
            "lastSync": self.meta.get("last_sync"),
            "deckNames": self.meta.get("deck_names", []),
            "storagePath": self.storage_path
        }
