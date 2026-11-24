"""Clean up Anki bracket furigana ("漢字[かんじ]") so it renders the way it was meant to.

How Anki reads it: the {{furigana:Field}} filter uses the regex ` ?([^ >]+?)\\[(.+?)\\]`.
A reading covers every character back to the previous space or '>', and that one space
is consumed. So:

- a block needs a space (or a '>' from a tag such as <b>) right before it, otherwise
  the kana in front joins it: 'の社員[しゃいん]' puts しゃいん over の社員;
- any other space is shown on the card: '友達[ともだち] が' has a visible gap.

LLMs get this wrong often enough that fixing it here is cheaper and more reliable than
asking the model to try again. normalize_furigana() only moves spaces and trims kana
that are duplicated between a block and its surroundings; it never invents readings.
Kanji that have no reading at all are left for validation to report.
"""
import re
from typing import List, Tuple

KANJI = "㐀-䶿一-鿿豈-﫿々〆ヶ"
KANA = "ぁ-ゖゝゞァ-ヵーヽヾ"

# A reading block: kanji or digits (optionally with kana in between, e.g. 振る舞, 取り消,
# 2つ目), then kana stuck before the bracket (okurigana that belong after it), then
# [reading]. Accepts full-width brackets and a stray space before the bracket, both fixed
# on output. Readings may contain tags (some decks list alternatives as さび<br>さみ).
_DIGITS = "0-9０-９"
_WORD_CHAR = f"{KANJI}{_DIGITS}"
_BLOCK = re.compile(
    rf"([{_WORD_CHAR}](?:[{KANA}]*[{_WORD_CHAR}])*)([{KANA}]*)[ ]*[\[［]([^\[\]［］\n]+?)[\]］]"
)
_TRAILING_KANA = re.compile(rf"[{KANA}]+$")
_KANA_RUN = re.compile(rf"[{KANA}]+")
_WORD_RUN_START = re.compile(rf"(?<![{_WORD_CHAR}])[{_WORD_CHAR}]")
# Exactly what Anki's furigana filter treats as a reading block
ANKI_BLOCK = re.compile(r" ?([^ >]+?)\[(.+?)\]")
_KANJI_CHAR = re.compile(rf"[{KANJI}]")
# Characters that can't be part of a word, so a block right after one needs a space:
# kana, Japanese punctuation and brackets, full-width punctuation, ASCII opening brackets/quotes.
_SPLITTERS = re.compile(rf"[{KANA}　-〿！-／：-＠［-｀｛-･(\"']$")
# A space Anki consumes: the next run of characters (up to a space or '>') is a block's base
_STARTS_BLOCK = re.compile(r"[^ >\[\]\n]+\[")
_HONORIFIC_PREFIXES = "おご"


def _fits(base: str, reading: str) -> bool:
    """True if kana inside a mixed base (振る舞) also appear, in order, inside its reading (ふるま)."""
    runs = _KANA_RUN.findall(base)
    if not runs:
        return True
    return re.fullmatch(".+" + ".+".join(re.escape(r) for r in runs) + ".+", reading, re.S) is not None


def _split_base(base: str, reading: str) -> Tuple[str, str]:
    """Splits off leading kanji that can't belong to this reading.

    '毎日の社員' with reading しゃいん is really '毎日の' (missing its reading) + '社員'.
    Returns (leading text, base).
    """
    if _fits(base, reading):
        return "", base
    for m in _WORD_RUN_START.finditer(base):
        if m.start() and _fits(base[m.start():], reading):
            return base[:m.start()], base[m.start():]
    return "", base  # unreachable: the last kanji run alone always fits


def _trim_duplicated_prefix(before: str, reading: str) -> str:
    """Drops kana written both before the block and at the start of its reading.

    'お茶[おちゃ]' -> 'お 茶[ちゃ]', 'やり遂[やりと]げる' -> 'やり 遂[と]げる'. Only trims the
    whole kana run (when nothing but a delimiter precedes it) or an honorific お/ご, so
    'まだ駄目[だめ]' keeps its reading.
    """
    m = _TRAILING_KANA.search(before)
    if not m:
        return reading
    run = m.group(0)
    starts_word = m.start() == 0 or not re.match(rf"[{_WORD_CHAR}]", before[m.start() - 1])
    if starts_word and len(reading) > len(run) and reading.startswith(run):
        return reading[len(run):]
    if run[-1] in _HONORIFIC_PREFIXES and len(reading) > 1 and reading[0] == run[-1]:
        return reading[1:]
    return reading


def _needs_space(before: str, base: str) -> bool:
    """A block directly after kana or punctuation would swallow it: 'の社員[しゃいん]'."""
    if not _SPLITTERS.search(before):
        return False
    # '2、3日[にさんにち]' and '500,000[...]': punctuation inside a number is part of it
    return not (re.match(rf"[{_DIGITS}]", base) and re.search(rf"[{_DIGITS}][、，,.．]$", before))


def _keep_space(prev: str, nxt: str) -> bool:
    """Between ASCII words ('Wi-Fi password') a space is meant to be seen."""
    return prev.isascii() and nxt.isascii() and prev not in "<>]" and nxt not in "<["


def normalize_furigana(text: str) -> str:
    if not text:
        return ""
    s = (
        str(text)
        .replace("&nbsp;", " ")
        .replace(" ", " ")
        .replace("　", " ")
        .replace("\t", " ")
    )

    pieces: List[str] = []
    pos = 0
    for m in _BLOCK.finditer(s):
        before = s[pos:m.start()]
        base, okurigana, reading = m.group(1), m.group(2), m.group(3).strip()
        lead, base = _split_base(base, reading)
        before += lead
        # 食べ[たべ] -> 食[た]べ: kana before the bracket belong after it
        if okurigana and reading.endswith(okurigana) and len(reading) > len(okurigana):
            reading = reading[: -len(okurigana)]
        reading = _trim_duplicated_prefix(before, reading)
        pieces += [before, " " if _needs_space(before, base) else "", f"{base}[{reading}]", okurigana]
        pos = m.end()
    pieces.append(s[pos:])
    joined = "".join(pieces)

    # Spaces outside readings: keep one where Anki needs it (before a block) or between
    # ASCII words; every other space would show on the card.
    def fix(m: re.Match) -> str:
        if m.group(0).startswith("["):
            return m.group(0)
        prev = joined[m.start() - 1] if m.start() else ""
        nxt = joined[m.end()] if m.end() < len(joined) else ""
        if not prev or not nxt:
            return ""
        if _STARTS_BLOCK.match(joined, m.end()) or _keep_space(prev, nxt):
            return " "
        return ""

    return re.sub(r"\[[^\]\n]*\]| +", fix, joined).strip()


def to_plain(text: str) -> str:
    """The sentence without readings, as Anki's {{kanji:Field}} shows it."""
    return ANKI_BLOCK.sub(r"\1", normalize_furigana(text)) if text else ""


def kanji_without_reading(text: str) -> str:
    """Kanji that Anki would show with no reading above them (sorted, de-duplicated)."""
    leftover = ANKI_BLOCK.sub("", normalize_furigana(text))
    leftover = re.sub(r"<[^>]+>", "", leftover)
    return "".join(sorted(set(_KANJI_CHAR.findall(leftover))))


def clean_sentence_pair(sent_kanji: str, sent_furigana: str) -> Tuple[str, str]:
    """Normalizes the furigana sentence and rebuilds the plain sentence from it, so the
    two can never disagree and the plain one never carries stray readings."""
    furigana = normalize_furigana(sent_furigana)
    if furigana:
        return to_plain(furigana), furigana
    plain = re.sub(r"\[[^\]]*\]", "", str(sent_kanji or ""))
    return re.sub(rf"(?<=[{KANJI}]) +| +(?=[{KANJI}])", "", plain).strip(), ""
