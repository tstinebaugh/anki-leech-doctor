"""
Kanji radical decomposition, visual similarity metrics, and phonetic feature extraction for Japanese RAG.
Includes Level 3 Unicode Ideographic Description Sequences (IDS) Spatial Tree Engine.
"""

import os
import json
import re
import unicodedata
from typing import Dict, List, Set, Tuple, Optional, Any, Union

# Load Unicode Ideographic Description Sequences (IDS) dataset
IDS_DATA: Dict[str, str] = {}
try:
    _ids_path = os.path.join(os.path.dirname(__file__), "kanji_ids_data.json")
    if os.path.exists(_ids_path):
        with open(_ids_path, "r", encoding="utf-8") as _f:
            IDS_DATA = json.load(_f)
except Exception as _e:
    print(f"Warning: Could not load kanji_ids_data.json: {_e}")

# Load look-alike kanji lists (2,902 kanji; source and license in DATA_SOURCES.md)
SIMILAR_KANJI_DATA: Dict[str, Set[str]] = {}
try:
    _sim_path = os.path.join(os.path.dirname(__file__), "kanji_similar.json")
    if os.path.exists(_sim_path):
        with open(_sim_path, "r", encoding="utf-8") as _f:
            _raw_sim = json.load(_f)
            SIMILAR_KANJI_DATA = {k: set(v) for k, v in _raw_sim.items()}
except Exception as _e:
    print(f"Warning: Could not load kanji_similar.json: {_e}")

# Unicode Ideographic Description Characters (IDCs) and their arities
IDS_OPERATORS: Dict[str, int] = {
    "⿰": 2, # Left to right (e.g. 侍 = ⿰亻寺)
    "⿱": 2, # Above to below (e.g. 花 = ⿱艹化, 呆 = ⿱口木)
    "⿲": 3, # Left to middle and right (e.g. 樹 = ⿲木壴寸)
    "⿳": 3, # Above to middle and below (e.g. 哀 = ⿳亠口衣)
    "⿴": 2, # Full surround (e.g. 国 = ⿴囗玉)
    "⿵": 2, # Surround from above (e.g. 同 = ⿵冂一口)
    "⿶": 2, # Surround from below (e.g. 凶 = ⿶凵乂)
    "⿷": 2, # Surround from left (e.g. 匠 = ⿷匚斤)
    "⿸": 2, # Surround from upper left (e.g. 府 = ⿸广付)
    "⿹": 2, # Surround from upper right (e.g. 句 = ⿹勹口)
    "⿺": 2, # Surround from lower left (e.g. 連 = ⿺辶車)
    "⿻": 2, # Overlaid / Intersecting (e.g. 本 = ⿻木一)
    "⿼": 2, # Surround from right
    "⿽": 2, # Surround from lower right
    "⿾": 1, # Horizontal reflection
    "⿿": 1, # Rotation
    "㇯": 2, # Subtraction
}

# Stand-ins for components Unicode has no character for. They say nothing about
# what two kanji share, so they never count as a common component.
IDS_PLACEHOLDERS = set("#？") | {chr(cp) for cp in range(0x2460, 0x2474)}  # ①-⑳

class IDSTree:
    """Represents a hierarchical syntax tree of a Kanji's spatial composition."""
    def __init__(
        self,
        op: Optional[str] = None,
        children: Optional[List[Union["IDSTree", str]]] = None,
        leaf: Optional[str] = None
    ):
        self.op = op
        self.children = children or []
        self.leaf = leaf

    def get_leaves(self) -> Set[str]:
        """Recursively extracts all atomic primitive leaves in the tree."""
        if self.leaf:
            return set() if self.leaf in IDS_PLACEHOLDERS else {RADICAL_VARIANTS.get(self.leaf, self.leaf)}
        leaves = set()
        for c in self.children:
            if isinstance(c, IDSTree):
                leaves.update(c.get_leaves())
            elif isinstance(c, str) and c not in IDS_PLACEHOLDERS:
                leaves.add(RADICAL_VARIANTS.get(c, c))
        return leaves

    def to_string(self) -> str:
        """Serializes the tree back into a canonical IDS string."""
        if self.leaf:
            return self.leaf
        child_strs = [c.to_string() if isinstance(c, IDSTree) else str(c) for c in self.children]
        return f"{self.op}{''.join(child_strs)}"

    def __repr__(self):
        if self.leaf:
            return self.leaf
        return f"{self.op}({', '.join(repr(c) for c in self.children)})"

def parse_ids(ids_str: str) -> Tuple[IDSTree, int]:
    """
    Deterministic recursive descent parser converting Unicode IDS string into an IDSTree.
    """
    if not ids_str:
        return IDSTree(leaf=""), 0
    char = ids_str[0]
    if char in IDS_OPERATORS:
        arity = IDS_OPERATORS[char]
        children: List[Union[IDSTree, str]] = []
        idx = 1
        for _ in range(arity):
            if idx < len(ids_str):
                child_tree, consumed = parse_ids(ids_str[idx:])
                children.append(child_tree)
                idx += consumed
        return IDSTree(op=char, children=children), idx
    else:
        return IDSTree(leaf=char), 1

def get_kanji_ids_tree(kanji: str) -> IDSTree:
    """Returns the parsed hierarchical IDSTree for a given single kanji character."""
    if not kanji:
        return IDSTree(leaf="")
    norm = unicodedata.normalize("NFKC", kanji)
    ids_str = IDS_DATA.get(norm) or IDS_DATA.get(kanji)
    if ids_str:
        tree, _ = parse_ids(ids_str)
        return tree
    return IDSTree(leaf=norm)

def compute_ids_tree_similarity(t1: IDSTree, t2: IDSTree) -> Dict[str, Any]:
    """
    Level 3 Spatial Tree Similarity Metric:
    Evaluates leaf primitive Jaccard, spatial operator matching, branch alignment, and inversion.
    """
    leaves1 = t1.get_leaves()
    leaves2 = t2.get_leaves()
    if not leaves1 or not leaves2:
        return {"score": 0.0, "jaccard": 0.0, "operator_match": False, "shared_branch": None, "is_spatial_inversion": False}

    intersection = leaves1 & leaves2
    union = leaves1 | leaves2
    jaccard = len(intersection) / len(union) if union else 0.0

    is_operator_match = (t1.op is not None and t1.op == t2.op)
    is_spatial_inversion = False
    shared_branch = None

    branch_bonus = 0.0
    if is_operator_match and len(t1.children) == len(t2.children) and len(t1.children) > 0:
        matched_positions = 0
        for i, (c1, c2) in enumerate(zip(t1.children, t2.children)):
            s1 = c1.to_string() if isinstance(c1, IDSTree) else str(c1)
            s2 = c2.to_string() if isinstance(c2, IDSTree) else str(c2)
            if s1 == s2:
                matched_positions += 1
                shared_branch = s1
        
        if matched_positions > 0:
            branch_bonus = 0.40 * (matched_positions / len(t1.children))
        elif len(t1.children) == 2:
            s1_0 = t1.children[0].to_string() if isinstance(t1.children[0], IDSTree) else str(t1.children[0])
            s1_1 = t1.children[1].to_string() if isinstance(t1.children[1], IDSTree) else str(t1.children[1])
            s2_0 = t2.children[0].to_string() if isinstance(t2.children[0], IDSTree) else str(t2.children[0])
            s2_1 = t2.children[1].to_string() if isinstance(t2.children[1], IDSTree) else str(t2.children[1])
            if s1_0 == s2_1 and s1_1 == s2_0:
                is_spatial_inversion = True

    score = (0.50 * jaccard) + (0.15 if is_operator_match else 0.0) + branch_bonus
    if is_spatial_inversion:
        score = max(score, 0.85)

    return {
        "score": round(min(1.0, score), 3),
        "jaccard": round(jaccard, 3),
        "operator_match": is_operator_match,
        "shared_branch": shared_branch,
        "is_spatial_inversion": is_spatial_inversion
    }

def check_kanji_spatial_inversion(k1: str, k2: str) -> Dict[str, Any]:
    """Checks if two single kanji are positional/spatial inversions (e.g. 呆 vs 杏)."""
    t1 = get_kanji_ids_tree(k1)
    t2 = get_kanji_ids_tree(k2)
    res = compute_ids_tree_similarity(t1, t2)
    return {
        "is_spatial_inversion": res["is_spatial_inversion"],
        "score": res["score"],
        "operator": t1.op if res["operator_match"] else None
    }

# Kangxi Radicals & Variant Normalization
RADICAL_VARIANTS: Dict[str, str] = {
    "亻": "人", "𠆢": "人",
    "氵": "水", "氺": "水",
    "扌": "手",
    "艹": "艸", "䒑": "艸",
    "阝": "邑", # or 阜
    "犭": "犬",
    "⻌": "辵", "辶": "辵",
    "忄": "心", "⺗": "心",
    "礻": "示",
    "衤": "衣",
    "灬": "火",
    "爫": "爪",
    "⺪": "疋",
    "牜": "牛",
    "飠": "食", "饣": "食",
    "⺅": "人",
    "⻑": "長",
    "⻖": "阜",
}

# 64 Distinct Core Radical Primitives for dense 64-D Visual Embedding
CORE_RADICAL_VOCAB: List[str] = [
    "人", "水", "手", "艸", "心", "言", "木", "糸", "口", "日",
    "月", "土", "金", "車", "女", "火", "目", "頁", "力", "門",
    "阜", "邑", "辵", "彳", "寸", "刀", "刂", "戈", "石", "貝",
    "禾", "米", "广", "宀", "酉", "竹", "鳥", "牛", "犬", "食",
    "立", "青", "見", "音", "又", "斤", "子", "夂", "止", "山",
    "田", "方", "甫", "戔", "僉", "寺", "侖", "兪", "冓", "氐",
    "龹", "爰", "奐", "頁"
]
RADICAL_TO_INDEX = {rad: idx for idx, rad in enumerate(CORE_RADICAL_VOCAB)}

KANJI_REGEX = re.compile(r"[\u4e00-\u9faf々〆ヶ]")

def extract_kanji_chars(text: str) -> List[str]:
    """Extracts unique kanji characters preserving order."""
    if not text:
        return []
    return list(dict.fromkeys(KANJI_REGEX.findall(text)))

def check_kanji_inversion_and_overlap(vocab1: str, vocab2: str) -> Dict[str, Any]:
    """
    Checks if vocab1 and vocab2:
    1. Are kanji anagrams/word inversions (e.g. 会社 vs 社会, 平和 vs 和平, 段階 vs 階段).
    2. Contain single kanji that are spatial component inversions (e.g. 呆 vs 杏).
    3. Share constituent kanji characters (e.g. 現金 and 料金 share 金, 現金 and 現在 share 現).
    """
    k1 = extract_kanji_chars(vocab1)
    k2 = extract_kanji_chars(vocab2)

    if not k1 or not k2:
        return {
            "is_inversion": False,
            "is_spatial_inversion": False,
            "shared_kanji": [],
            "overlap_ratio": 0.0,
            "has_shared_kanji": False
        }

    s1 = set(k1)
    s2 = set(k2)
    shared = sorted(list(s1 & s2))

    is_inversion = False
    if len(k1) >= 2 and len(k2) >= 2:
        if s1 == s2 and k1 != k2:
            is_inversion = True

    # Check for single-kanji spatial component inversions (e.g. 呆 vs 杏)
    is_spatial_inversion = False
    for char1 in k1:
        for char2 in k2:
            if char1 != char2:
                sp_res = check_kanji_spatial_inversion(char1, char2)
                if sp_res["is_spatial_inversion"]:
                    is_spatial_inversion = True
                    break

    overlap_ratio = len(shared) / max(len(s1), len(s2)) if max(len(s1), len(s2)) > 0 else 0.0

    return {
        "is_inversion": is_inversion,
        "is_spatial_inversion": is_spatial_inversion,
        "shared_kanji": shared,
        "overlap_ratio": round(overlap_ratio, 3),
        "has_shared_kanji": len(shared) > 0
    }

def get_kanji_components(kanji: str) -> List[str]:
    """Returns the constituent components/radicals for a given kanji using Level 3 IDS."""
    tree = get_kanji_ids_tree(kanji)
    leaves = tree.get_leaves()
    if leaves:
        return sorted(list(leaves))
    norm = unicodedata.normalize("NFKC", kanji)
    return [RADICAL_VARIANTS.get(norm, norm)]

def are_in_same_confusable_cluster(k1: str, k2: str) -> bool:
    """Checks if two kanji belong to a known optical look-alike confusable set (2,902 Joyo/JLPT kanji)."""
    if k1 in SIMILAR_KANJI_DATA and k2 in SIMILAR_KANJI_DATA[k1]:
        return True
    if k2 in SIMILAR_KANJI_DATA and k1 in SIMILAR_KANJI_DATA[k2]:
        return True
    return False

def compute_kanji_visual_similarity(k1: str, k2: str) -> float:
    """
    Level 3 Visual Similarity Metric between two individual kanji characters.
    Combines:
    1. Known high-confusion cluster mapping (0.88 baseline)
    2. Level 3 Unicode IDS Spatial Tree Similarity (operator matching, branch alignment, spatial inversions)
    3. Fine-grained primitive Jaccard overlap
    """
    if k1 == k2:
        return 1.0
    
    # 1. Check known confusion cluster
    cluster_match = are_in_same_confusable_cluster(k1, k2)

    # 2. Level 3 IDS Tree structural & spatial similarity
    t1 = get_kanji_ids_tree(k1)
    t2 = get_kanji_ids_tree(k2)
    ids_res = compute_ids_tree_similarity(t1, t2)
    tree_score = ids_res["score"]

    # 3. Leaf primitive Jaccard overlap with complex component weighting
    c1 = set(get_kanji_components(k1))
    c2 = set(get_kanji_components(k2))
    jaccard = 0.0
    if c1 and c2:
        intersection = len(c1 & c2)
        union = len(c1 | c2)
        jaccard = intersection / union if union > 0 else 0.0
        shared = c1 & c2
        complex_primitives = {"寺", "戔", "侖", "兪", "冓", "僉", "甫", "氐", "龹", "爰", "奐", "青", "東", "頁"}
        if any(p in complex_primitives for p in shared):
            jaccard = max(jaccard, 0.82)
        elif intersection >= 2:
            jaccard = max(jaccard, 0.70)
        elif intersection == 1 and ("彳" in shared or "扌" in shared or "木" in shared or "言" in shared):
            jaccard = max(jaccard, 0.45)

    final_score = max(tree_score, jaccard)
    if cluster_match:
        final_score = max(final_score, 0.88)

    return round(min(final_score, 0.98), 3)

def compute_vocab_visual_similarity(vocab1: str, vocab2: str) -> float:
    """
    Computes visual similarity between two vocabulary expressions.
    """
    if vocab1 == vocab2:
        return 1.0

    k1_list = extract_kanji_chars(vocab1)
    k2_list = extract_kanji_chars(vocab2)

    if not k1_list and not k2_list:
        # Both kana-only
        return 1.0 if vocab1 == vocab2 else 0.0
    if not k1_list or not k2_list:
        return 0.0

    # Pairwise max matching
    sim_scores = []
    for k1 in k1_list:
        best_for_k1 = max((compute_kanji_visual_similarity(k1, k2) for k2 in k2_list), default=0.0)
        sim_scores.append(best_for_k1)

    for k2 in k2_list:
        best_for_k2 = max((compute_kanji_visual_similarity(k1, k2) for k1 in k1_list), default=0.0)
        sim_scores.append(best_for_k2)

    return round(sum(sim_scores) / len(sim_scores), 3) if sim_scores else 0.0

def generate_visual_vector(text: str, dim: int = 64) -> List[float]:
    """
    Generates a 64-dimensional dense visual feature vector based on kanji radicals and topological features.
    """
    vec = [0.0] * dim
    kanji_list = extract_kanji_chars(text)
    if not kanji_list:
        # For kana words, encode unicode category baseline
        for idx, ch in enumerate(text[:dim]):
            vec[idx % dim] += 0.1
        return normalize_vector(vec)

    for k in kanji_list:
        components = get_kanji_components(k)
        for comp in components:
            if comp in RADICAL_TO_INDEX:
                vec[RADICAL_TO_INDEX[comp]] += 1.0
            else:
                # Hash unmapped component
                h = abs(hash(comp)) % dim
                vec[h] += 0.5
        # Add unicode codepoint feature
        cp_idx = (ord(k) - 0x4E00) % dim
        vec[cp_idx] += 0.3

    return normalize_vector(vec)


# --- Phonetic Feature Extraction ---

KANA_TO_ROMAJI: Dict[str, str] = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "を": "wo", "ん": "n",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "っ": "Q", "ー": "-", "・": "", " ": ""
}

def clean_furigana_to_kana(reading: str) -> str:
    """Extracts pure hiragana/katakana string from bracket furigana syntax."""
    if not reading:
        return ""
    # Extract text in brackets if present: 限界[げんかい] -> げんかい
    bracket_matches = re.findall(r"\[([^\]]+)\]", reading)
    if bracket_matches:
        kana_only = "".join(bracket_matches)
    else:
        # Strip kanji and punctuation
        kana_only = re.sub(r"[^\u3040-\u309F\u30A0-\u30FFー]", "", reading)
    
    # Convert Katakana to Hiragana
    hiragana = []
    for char in kana_only:
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            hiragana.append(chr(code - 0x60))
        else:
            hiragana.append(char)
    return "".join(hiragana)

def kana_to_phoneme_sequence(kana_str: str) -> List[str]:
    """Converts hiragana string into a standardized mora/phoneme sequence."""
    kana = clean_furigana_to_kana(kana_str)
    i = 0
    phonemes = []
    while i < len(kana):
        # Check two-character combination (e.g. しゃ, きゅ)
        if i + 1 < len(kana) and kana[i:i+2] in KANA_TO_ROMAJI:
            phonemes.append(KANA_TO_ROMAJI[kana[i:i+2]])
            i += 2
        elif kana[i] in KANA_TO_ROMAJI:
            phonemes.append(KANA_TO_ROMAJI[kana[i]])
            i += 1
        else:
            phonemes.append(kana[i])
            i += 1
    return phonemes

def compute_phonetic_similarity(r1: str, r2: str) -> float:
    """
    Computes phonetic acoustic similarity between two readings using Levenshtein distance on phoneme sequences.
    """
    p1 = kana_to_phoneme_sequence(r1)
    p2 = kana_to_phoneme_sequence(r2)

    if not p1 and not p2:
        return 1.0
    if not p1 or not p2:
        return 0.0

    s1 = "-".join(p1)
    s2 = "-".join(p2)
    if s1 == s2:
        return 1.0

    # Levenshtein distance
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if s1[i-1] == s2[j-1] else 1
            dp[i][j] = min(
                dp[i-1][j] + 1,
                dp[i][j-1] + 1,
                dp[i-1][j-1] + cost
            )

    dist = dp[m][n]
    max_len = max(m, n)
    sim = 1.0 - (dist / max_len)
    return round(max(0.0, sim), 3)

def generate_phonetic_vector(reading: str, dim: int = 64) -> List[float]:
    """
    Generates a 64-dimensional dense phonetic feature vector from reading.
    """
    vec = [0.0] * dim
    phonemes = kana_to_phoneme_sequence(reading)
    if not phonemes:
        return normalize_vector(vec)

    # 1. Encode phonemes with positional weighting
    for pos, ph in enumerate(phonemes):
        pos_weight = 1.0 / (1.0 + 0.2 * pos)
        h = abs(hash(ph)) % dim
        vec[h] += 1.0 * pos_weight
        # Bigram encoding
        if pos + 1 < len(phonemes):
            bigram = f"{ph}_{phonemes[pos+1]}"
            bh = abs(hash(bigram)) % dim
            vec[bh] += 1.5 * pos_weight

    # 2. Length feature
    vec[0] += min(len(phonemes) * 0.1, 1.0)

    return normalize_vector(vec)

def normalize_vector(vec: List[float]) -> List[float]:
    """L2 normalizes a vector."""
    norm = sum(x * x for x in vec) ** 0.5
    if norm == 0:
        return [0.0] * len(vec)
    return [round(x / norm, 5) for x in vec]
