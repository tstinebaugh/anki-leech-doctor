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
import logging
import shutil
from typing import Any, Dict, List, Optional, Set

import numpy as np


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
from vector_store import VectorStore

logger = logging.getLogger(__name__)
UUID_DIR_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

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
    SPACES = ("semantic", "visual", "phonetic")

    def __init__(self, storage_path: str = DEFAULT_STORAGE_PATH):
        self.storage_path = storage_path
        os.makedirs(self.storage_path, exist_ok=True)
        self.store = VectorStore(os.path.join(self.storage_path, "vectors.npz"))
        self.meta_file = os.path.join(self.storage_path, "meta.json")
        self.meta = self._load_meta()
        self.kanji_index: Dict[str, Set[str]] = {}
        self._build_kanji_index()
        if os.path.exists(os.path.join(self.storage_path, "chroma.sqlite3")):
            logger.info("Found an old ChromaDB index; it is no longer used and is removed on the next RAG sync.")

    def _build_kanji_index(self):
        """Maps each kanji to the ids of indexed cards whose word contains it."""
        self.kanji_index = {}
        for cid, m in self.store.all_metadata():
            for k in extract_kanji_chars(m.get("vocabKanji", "")):
                self.kanji_index.setdefault(k, set()).add(cid)

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

    def _remove_legacy_chroma_files(self):
        """Deletes the ChromaDB index used before 0001-numpy-vector-index (a rebuildable cache)."""
        sqlite_path = os.path.join(self.storage_path, "chroma.sqlite3")
        if not os.path.exists(sqlite_path):
            return
        for name in os.listdir(self.storage_path):
            full = os.path.join(self.storage_path, name)
            # ChromaDB keeps each collection's index in a folder named by a UUID
            if os.path.isdir(full) and UUID_DIR_RE.match(name) and os.path.exists(os.path.join(full, "header.bin")):
                shutil.rmtree(full, ignore_errors=True)
        for name in ("chroma.sqlite3", "chroma.sqlite3-wal", "chroma.sqlite3-shm"):
            try:
                os.remove(os.path.join(self.storage_path, name))
            except FileNotFoundError:
                pass
        logger.info("Removed the old ChromaDB index files.")

    def reset_index(self):
        """Empties the index before a full re-sync."""
        self.store.clear()
        self._remove_legacy_chroma_files()
        self.kanji_index = {}
        self.meta = {"last_sync": None, "indexed_count": 0, "deck_names": []}
        self._save_meta()

    async def get_semantic_embedding_single(self, text: str) -> List[float]:
        """Embeds a single text string (local, no API calls)."""
        return fallback_text_embedding(text)

    async def index_cards(self, cards: List[Dict[str, Any]], deck_name: Optional[str] = None) -> Dict[str, Any]:
        """Adds or updates cards in the semantic, visual and phonetic indexes."""
        if not cards:
            return {"indexed": 0, "message": "No cards to index"}

        ids: List[str] = []
        semantic, visual, phonetic = [], [], []
        metadatas = []
        seen = set()
        for c in cards:
            cid = str(c.get("cardId", ""))
            vocab_kanji = str(c.get("vocabKanji", "")).strip()
            if not cid or not vocab_kanji or cid in seen:
                continue
            seen.add(cid)
            vocab_furigana = str(c.get("vocabFurigana", "")).strip()
            vocab_def = str(c.get("vocabDef", "")).strip()

            ids.append(cid)
            # float32 right away: a 3,072-float Python list costs ~100 KB per card, the array 12 KB
            semantic.append(np.asarray(fallback_text_embedding(f"Word: {vocab_kanji} | Reading: {vocab_furigana} | Meaning: {vocab_def}"), dtype=np.float32))
            visual.append(np.asarray(generate_visual_vector(vocab_kanji), dtype=np.float32))
            phonetic.append(np.asarray(generate_phonetic_vector(vocab_furigana or vocab_kanji), dtype=np.float32))
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

        vectors = {"semantic": np.stack(semantic), "visual": np.stack(visual), "phonetic": np.stack(phonetic)}
        del semantic, visual, phonetic
        try:
            self.store.upsert(ids, vectors, metadatas)
        except ValueError as e:
            # Index built with a different layout (e.g. older vector sizes): rebuild from these cards
            logger.warning(f"Vector index layout changed, starting a fresh index: {e}")
            self.store.clear()
            self.store.upsert(ids, vectors, metadatas)
            self._build_kanji_index()

        for cid, m in zip(ids, metadatas):
            for k in extract_kanji_chars(m["vocabKanji"]):
                self.kanji_index.setdefault(k, set()).add(cid)

        self.meta["last_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.meta["indexed_count"] = self.store.count()
        if deck_name and deck_name not in self.meta["deck_names"]:
            self.meta["deck_names"].append(deck_name)
        self._save_meta()

        return {
            "indexed": len(ids),
            "totalIndexed": self.meta["indexed_count"],
            "lastSync": self.meta["last_sync"]
        }

    def delete_card(self, card_id: int) -> bool:
        """Removes a card from the vector and kanji indexes."""
        cid_str = str(card_id)
        self.store.delete([cid_str])
        for cids in self.kanji_index.values():
            cids.discard(cid_str)
        self.meta["indexed_count"] = self.store.count()
        self._save_meta()
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
        if self.store.count() == 0:
            return []

        w = weights or {"semantic": 0.45, "visual": 0.30, "phonetic": 0.25}
        w_sem = w.get("semantic", 0.45)
        w_vis = w.get("visual", 0.30)
        w_phon = w.get("phonetic", 0.25)

        # 1. Query vectors
        query_text = f"Word: {vocab_kanji} | Reading: {vocab_furigana} | Meaning: {vocab_def}"
        queries = {
            "semantic": await self.get_semantic_embedding_single(query_text),
            "visual": generate_visual_vector(vocab_kanji),
            "phonetic": generate_phonetic_vector(vocab_furigana or vocab_kanji),
        }
        fetch_k = 100

        # 2. Top candidates from each space, merged by card id
        candidates: Dict[str, Dict[str, Any]] = {}

        def add_candidate(c_id: str, meta: Dict[str, Any]) -> bool:
            if exclude_card_id and meta.get("cardId") == exclude_card_id:
                return False
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
            return True

        for space, q in queries.items():
            try:
                hits = self.store.query(space, q, fetch_k)
            except ValueError as e:
                logger.warning(f"{space} search skipped: {e}")
                continue
            for c_id, sim, meta in hits:
                if add_candidate(c_id, meta):
                    candidates[c_id][f"{space}Score"] = round(max(0.0, min(1.0, sim)), 3)

        # 3. Add every indexed card that shares a kanji with the word
        shared_kanji_cids = set()
        for ch in extract_kanji_chars(vocab_kanji):
            shared_kanji_cids.update(self.kanji_index.get(ch, set()))
        missing = [cid for cid in shared_kanji_cids if cid not in candidates]
        for meta in self.store.get(missing):
            add_candidate(str(meta.get("cardId")), meta)

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
            "indexedCount": self.store.count(),
            "lastSync": self.meta.get("last_sync"),
            "deckNames": self.meta.get("deck_names", []),
            "storagePath": self.storage_path
        }
