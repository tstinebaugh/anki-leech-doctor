import numpy as np
import pytest

from vector_store import VectorStore


def _store(tmp_path):
    return VectorStore(str(tmp_path / "vectors.npz"))


def test_query_returns_exact_top_k_by_cosine(tmp_path):
    s = _store(tmp_path)
    s.upsert(
        ["a", "b", "c"],
        {"v": [[1, 0], [0.8, 0.6], [0, 1]]},
        [{"n": "a"}, {"n": "b"}, {"n": "c"}],
    )
    hits = s.query("v", [1, 0], k=2)
    assert [h[0] for h in hits] == ["a", "b"]
    assert hits[0][1] == pytest.approx(1.0)
    assert hits[1][1] == pytest.approx(0.8)
    assert hits[0][2] == {"n": "a"}
    # k larger than the index returns everything, sorted
    assert [h[0] for h in s.query("v", [0, 1], k=10)] == ["c", "b", "a"]


def test_upsert_replaces_existing_and_appends_new(tmp_path):
    s = _store(tmp_path)
    s.upsert(["a", "b"], {"v": [[1, 0], [0, 1]]}, [{"x": 1}, {"x": 2}])
    s.upsert(["b", "c"], {"v": [[1, 0], [1, 1]]}, [{"x": 20}, {"x": 3}])
    assert s.count() == 3
    assert s.get(["b"]) == [{"x": 20}]
    assert {h[0] for h in s.query("v", [1, 0], k=2)} == {"a", "b"}


def test_delete_and_persistence_round_trip(tmp_path):
    s = _store(tmp_path)
    s.upsert(["a", "b", "c"], {"v": [[1, 0], [0, 1], [1, 1]], "w": [[1], [2], [3]]}, [{}, {"k": "日本"}, {}])
    assert s.delete(["a", "missing"]) == 1

    reloaded = _store(tmp_path)
    assert reloaded.count() == 2
    assert reloaded.get(["b"]) == [{"k": "日本"}]
    assert [h[0] for h in reloaded.query("v", [0, 1], k=1)] == ["b"]
    # No temp files left behind
    assert [p.name for p in tmp_path.iterdir()] == ["vectors.npz"]


def test_zero_vectors_never_match(tmp_path):
    s = _store(tmp_path)
    s.upsert(["a", "z"], {"v": [[1, 0], [0, 0]]}, [{}, {}])
    hits = s.query("v", [1, 0], k=2)
    assert hits[0][0] == "a"
    assert hits[1][1] == 0.0
    assert s.query("v", [0, 0], k=2) == []


def test_layout_mismatch_is_rejected(tmp_path):
    s = _store(tmp_path)
    s.upsert(["a"], {"v": [[1, 0]]}, [{}])
    with pytest.raises(ValueError):
        s.upsert(["b"], {"v": [[1, 0, 0]]}, [{}])
    with pytest.raises(ValueError):
        s.query("v", [1, 0, 0], k=1)


def test_unreadable_file_starts_empty(tmp_path):
    (tmp_path / "vectors.npz").write_bytes(b"not a numpy file")
    s = _store(tmp_path)
    assert s.count() == 0
    s.upsert(["a"], {"v": [[1.0]]}, [{}])
    assert s.count() == 1


def test_clear_removes_file(tmp_path):
    s = _store(tmp_path)
    s.upsert(["a"], {"v": [[1.0, 2.0]]}, [{}])
    s.clear()
    assert s.count() == 0
    assert not (tmp_path / "vectors.npz").exists()
    assert np.asarray(s.query("v", [1, 2], k=1)).size == 0


def test_rag_reset_removes_legacy_chroma_files(tmp_path):
    from rag_engine import MultiVectorRAG
    legacy = tmp_path / "0f8fad5b-d9cb-469f-a165-70867728950e"
    legacy.mkdir()
    (legacy / "header.bin").write_bytes(b"x")
    (tmp_path / "chroma.sqlite3").write_bytes(b"x")
    keep = tmp_path / "notes"
    keep.mkdir()

    rag = MultiVectorRAG(storage_path=str(tmp_path))
    rag.reset_index()
    assert not legacy.exists()
    assert not (tmp_path / "chroma.sqlite3").exists()
    assert keep.exists()


def test_feature_vectors_are_identical_across_processes():
    """Saved vectors must match query vectors after a restart (hash() is per-process random)."""
    import os
    import subprocess
    import sys

    code = (
        "from kanji_data import generate_visual_vector, generate_phonetic_vector;"
        "from rag_engine import fallback_text_embedding;"
        "print(repr((generate_visual_vector('待つ'), generate_phonetic_vector('まつ'),"
        " generate_visual_vector('鬱'), fallback_text_embedding('Word: 待つ'))))"
    )
    root = os.path.dirname(os.path.abspath(__file__))
    outs = {
        subprocess.run(
            [sys.executable, "-c", code], cwd=root, capture_output=True, text=True, check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("1", "2", "3")
    }
    assert len(outs) == 1


def test_indexing_fetch_uses_notes_not_rendered_cards():
    from unittest.mock import patch
    from anki_client import AnkiClient

    client = AnkiClient()
    calls = []

    def fake_invoke(action, **kw):
        calls.append(action)
        if action == "findCards":
            return [11, 12, 13]
        if action == "getDecks":
            return {"Core": [11, 13], "Core::Sub": [12]}
        if action == "areSuspended":
            return [False, True, False]
        if action == "findNotes":
            return [1, 2]
        if action == "notesInfo":
            return [
                {"noteId": 1, "cards": [11, 12], "fields": {"Expression": {"value": "猫"}, "Meaning": {"value": "cat"}}},
                {"noteId": 2, "cards": [13], "fields": {"Expression": {"value": ""}}},  # no word: skipped
            ]
        raise AssertionError(f"unexpected {action}")

    with patch.object(client, "invoke", side_effect=fake_invoke):
        cards = client.get_all_cards_for_indexing(deck_names=["Core"])

    assert "cardsInfo" not in calls
    assert [(c["cardId"], c["deckName"], c["suspended"]) for c in cards] == [(11, "Core", False), (12, "Core::Sub", True)]
    assert cards[0]["vocabKanji"] == "猫" and cards[0]["vocabDef"] == "cat" and cards[0]["noteId"] == 1
