"""
Automated unit tests for Multi-Vector RAG (Semantic, Visual, and Phonetic) similarity & deduplication engine.
"""

import pytest
import shutil
import os
from kanji_data import (
    compute_kanji_visual_similarity,
    compute_vocab_visual_similarity,
    compute_phonetic_similarity,
    generate_visual_vector,
    generate_phonetic_vector,
    are_in_same_confusable_cluster
)
from rag_engine import MultiVectorRAG
from fastapi.testclient import TestClient
from app import app

TEST_RAG_DIR = "./.pytest_rag_storage"


@pytest.fixture(scope="module")
def rag_instance():
    # Cleanup any old test storage
    if os.path.exists(TEST_RAG_DIR):
        shutil.rmtree(TEST_RAG_DIR)
    
    rag = MultiVectorRAG(storage_path=TEST_RAG_DIR)
    yield rag
    
    # Teardown
    if os.path.exists(TEST_RAG_DIR):
        shutil.rmtree(TEST_RAG_DIR)


def test_kanji_visual_similarity():
    # Known look-alike pairs (same cluster or radical sharing)
    assert compute_kanji_visual_similarity("待", "持") >= 0.80
    assert compute_kanji_visual_similarity("微", "徴") >= 0.80
    assert compute_kanji_visual_similarity("輪", "輸") >= 0.70
    assert compute_kanji_visual_similarity("治", "冶") >= 0.70

    # Unrelated kanji
    assert compute_kanji_visual_similarity("待", "犬") == 0.0
    assert compute_kanji_visual_similarity("日", "魚") == 0.0

    # Cluster checks
    assert are_in_same_confusable_cluster("待", "持") is True
    assert are_in_same_confusable_cluster("鳥", "烏") is True
    assert are_in_same_confusable_cluster("猫", "犬") is False


def test_vocab_visual_similarity():
    # Expressions sharing confusing kanji
    sim_machigai = compute_vocab_visual_similarity("待機", "持参")
    assert sim_machigai >= 0.40  # 待 vs 持

    # Identical
    assert compute_vocab_visual_similarity("限界", "限界") == 1.0


def test_phonetic_similarity():
    # Identical readings
    assert compute_phonetic_similarity("ついたち", "ついたち") == 1.0
    assert compute_phonetic_similarity("一日[ついたち]", "ついたち") == 1.0

    # Near-homophones / shared moras
    sim_shuu = compute_phonetic_similarity("しゅうしゅう", "しゅうよう")
    assert sim_shuu >= 0.65

    # Completely different sounds
    sim_diff = compute_phonetic_similarity("あめ", "くるま")
    assert sim_diff < 0.30


def test_vector_generation():
    vis_vec = generate_visual_vector("待つ")
    assert len(vis_vec) == 64
    assert sum(x * x for x in vis_vec) > 0.9  # Normalized

    phon_vec = generate_phonetic_vector("まつ")
    assert len(phon_vec) == 64
    assert sum(x * x for x in phon_vec) > 0.9  # Normalized


@pytest.mark.anyio
async def test_rag_indexing_and_multi_search(rag_instance):
    sample_cards = [
        {
            "cardId": 101,
            "noteId": 101,
            "deckName": "Core2k",
            "vocabKanji": "持つ",
            "vocabFurigana": "持[も]つ",
            "vocabDef": "to hold; to carry; to possess",
            "sentKanji": "荷物を<b>持つ</b>。",
            "sentEng": "I hold the luggage."
        },
        {
            "cardId": 102,
            "noteId": 102,
            "deckName": "Core2k",
            "vocabKanji": "一日",
            "vocabFurigana": "一日[ついたち]",
            "vocabDef": "first day of the month",
            "sentKanji": "五月<b>一日</b>です。",
            "sentEng": "It is May 1st."
        },
        {
            "cardId": 103,
            "noteId": 103,
            "deckName": "Mining",
            "vocabKanji": "収集",
            "vocabFurigana": "収集[しゅうしゅう]",
            "vocabDef": "gathering; collection; harvest",
            "sentKanji": "ゴミを<b>収集</b>する。",
            "sentEng": "Collect the garbage."
        },
        {
            "cardId": 104,
            "noteId": 104,
            "deckName": "Core2k",
            "vocabKanji": "紛らわしい",
            "vocabFurigana": "紛[まぎ]らわしい",
            "vocabDef": "confusing; misleading; ambiguous",
            "sentKanji": "<b>紛らわしい</b>言葉。",
            "sentEng": "Confusing words."
        }
    ]

    index_res = await rag_instance.index_cards(sample_cards, deck_name="Core2k")
    assert index_res["indexed"] == 4
    assert index_res["totalIndexed"] == 4

    # 1. Test Visual Look-alike retrieval: Query "待つ" should match "持つ" (Visual Confuser)
    matches_matsu = await rag_instance.search_similar("待つ", "待[ま]つ", "to wait")
    assert len(matches_matsu) > 0
    top_matsu = matches_matsu[0]
    assert top_matsu["vocabKanji"] == "持つ"
    assert top_matsu["isVisualConfuser"] is True
    assert any("Look-alike kanji" in r for r in top_matsu["collisionReasons"])

    # 2. Test Semantic Duplicate retrieval: Query "朔日" (first day of month) should match "一日" (first day of month)
    matches_tsuitachi = await rag_instance.search_similar("朔日", "朔日[ついたち]", "first day of the month")
    assert len(matches_tsuitachi) > 0
    top_tsuitachi = matches_tsuitachi[0]
    assert top_tsuitachi["vocabKanji"] == "一日"
    assert top_tsuitachi["isSemanticDuplicate"] is True or top_tsuitachi["semanticScore"] >= 0.80

    # 3. Test Phonetic Collision: Query "収容" (しゅうよう) should match "収集" (しゅうしゅう)
    matches_shuu = await rag_instance.search_similar("収容", "収容[しゅうよう]", "accommodation, admission")
    assert len(matches_shuu) > 0
    found_shuu = next((m for m in matches_shuu if m["vocabKanji"] == "収集"), None)
    assert found_shuu is not None
    # 4. Test Kanji Anagram / Inversion: Index "会社" and query "社会"
    await rag_instance.index_cards([{
        "cardId": 105,
        "noteId": 105,
        "deckName": "Core2k",
        "vocabKanji": "会社",
        "vocabFurigana": "会社[かいしゃ]",
        "vocabDef": "company; corporation",
        "sentKanji": "<b>会社</b>に行く。",
        "sentEng": "Go to the company."
    }])

    matches_shakai = await rag_instance.search_similar("社会", "社会[しゃかい]", "society; the world")
    assert len(matches_shakai) > 0
    top_shakai = next((m for m in matches_shakai if m["vocabKanji"] == "会社"), None)
    assert top_shakai is not None
    assert top_shakai["isKanjiInversion"] is True
    assert any("Kanji Reversal" in r for r in top_shakai["collisionReasons"])


def test_kanji_inversion_and_overlap_function():
    from kanji_data import check_kanji_inversion_and_overlap

    # Exact anagram / inversion
    inv_res = check_kanji_inversion_and_overlap("社会", "会社")
    assert inv_res["is_inversion"] is True
    assert inv_res["overlap_ratio"] == 1.0
    assert sorted(inv_res["shared_kanji"]) == ["会", "社"]

    # Shared constituent kanji
    shared_res = check_kanji_inversion_and_overlap("現金", "料金")
    assert shared_res["is_inversion"] is False
    assert shared_res["shared_kanji"] == ["金"]
    assert shared_res["overlap_ratio"] == 0.5

    # Completely disjoint kanji
    disjoint_res = check_kanji_inversion_and_overlap("現金", "不審")
    assert disjoint_res["is_inversion"] is False
    assert disjoint_res["shared_kanji"] == []
    assert disjoint_res["overlap_ratio"] == 0.0


def test_semantic_fallback_precision():
    from rag_engine import fallback_text_embedding
    import numpy as np

    v_genkin = fallback_text_embedding("cash; ready money")
    v_fushin = fallback_text_embedding("suspicious")
    v_gyouretsu = fallback_text_embedding("line; queue")
    v_okane = fallback_text_embedding("money; cash")

    # Unrelated meanings must have 0.0 similarity
    assert np.dot(v_genkin, v_fushin) == 0.0
    assert np.dot(v_genkin, v_gyouretsu) == 0.0

    # Synonyms sharing terms have high similarity
    assert np.dot(v_genkin, v_okane) >= 0.70


def test_level3_ids_tree_parsing_and_similarity():
    from kanji_data import (
        parse_ids,
        get_kanji_ids_tree,
        compute_ids_tree_similarity,
        check_kanji_spatial_inversion
    )

    # 1. Parse recursive IDS tree
    tree_matsu, _ = parse_ids("⿰彳⿱土寸")
    assert tree_matsu.op == "⿰"
    assert len(tree_matsu.children) == 2
    assert "彳" in tree_matsu.get_leaves()
    assert "土" in tree_matsu.get_leaves()
    assert "寸" in tree_matsu.get_leaves()

    # 2. Test Right-Branch Alignment between 待 and 持
    t_matsu = get_kanji_ids_tree("待")
    t_motsu = get_kanji_ids_tree("持")
    sim_res = compute_ids_tree_similarity(t_matsu, t_motsu)
    assert sim_res["score"] >= 0.50
    assert sim_res["operator_match"] is True
    assert sim_res["shared_branch"] in ["寺", "⿱土寸"]
    assert compute_kanji_visual_similarity("待", "持") >= 0.80

    # 3. Test Positional Inversion (呆 vs 杏)
    t_baka = get_kanji_ids_tree("呆")
    t_anzu = get_kanji_ids_tree("杏")
    inv_res = compute_ids_tree_similarity(t_baka, t_anzu)
    assert inv_res["is_spatial_inversion"] is True
    assert inv_res["score"] >= 0.80

    sp_res = check_kanji_spatial_inversion("呆", "杏")
    assert sp_res["is_spatial_inversion"] is True

    # 4. Test Enclosure frame (国 vs 園)
    t_koku = get_kanji_ids_tree("国")
    t_en = get_kanji_ids_tree("園")
    enc_res = compute_ids_tree_similarity(t_koku, t_en)
    assert enc_res["operator_match"] is True
    assert enc_res["shared_branch"] == "囗"


def test_rag_api_endpoints():
    client = TestClient(app)

    # 1. Stats endpoint
    res = client.get("/api/rag/stats")
    assert res.status_code == 200
    data = res.json()
    assert "indexedCount" in data

    # 2. Search endpoint
    search_res = client.post("/api/rag/search-similar", json={
        "vocabKanji": "待つ",
        "vocabFurigana": "待[ま]つ",
        "vocabDef": "to wait",
        "topK": 3
    })
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert "matches" in search_data

    # 3. Config check includes ragStats and deck options
    cfg_res = client.get("/api/config")
    assert cfg_res.status_code == 200
    cfg_data = cfg_res.json()
    assert "ragStats" in cfg_data
    assert "ragExcludeSuspended" in cfg_data


@pytest.mark.anyio
async def test_constituent_kanji_retrieval(rag_instance):
    # Index two cards sharing the kanji 電
    sample_cards = [
        {
            "cardId": 9001,
            "noteId": 9001,
            "deckName": "Test Deck",
            "vocabKanji": "電池",
            "vocabFurigana": "電池[でんち]",
            "vocabDef": "Battery",
            "sentKanji": "電池",
            "sentEng": "",
            "suspended": False,
            "lapses": 0
        },
        {
            "cardId": 9002,
            "noteId": 9002,
            "deckName": "Test Deck",
            "vocabKanji": "電車",
            "vocabFurigana": "電車[でんしゃ]",
            "vocabDef": "Train",
            "sentKanji": "電車",
            "sentEng": "",
            "suspended": False,
            "lapses": 0
        }
    ]
    await rag_instance.index_cards(sample_cards, deck_name="Test Deck")

    # Search for 充電 (charging) which shares 電 with 電池 and 電車
    matches = await rag_instance.search_similar("充電", "充電[じゅうでん]", "charging", top_k=5)
    matched_kanji = [m["vocabKanji"] for m in matches]
    
    assert "電池" in matched_kanji
    assert "電車" in matched_kanji
    
    # Verify collision reasons
    denchi_match = next(m for m in matches if m["vocabKanji"] == "電池")
    assert any("【電】" in r for r in denchi_match["collisionReasons"])

    # Test deleting a card from RAG
    rag_instance.delete_card(9001)
    matches_after_delete = await rag_instance.search_similar("充電", "充電[じゅうでん]", "charging", top_k=5)
    matched_kanji_after = [m["vocabKanji"] for m in matches_after_delete]
    assert "電池" not in matched_kanji_after
    assert "電車" in matched_kanji_after

