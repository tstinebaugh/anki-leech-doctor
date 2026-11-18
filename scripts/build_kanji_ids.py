"""Rebuilds kanji_ids_data.json from the MIT-licensed yi-bai/ids dataset.

Usage:  python scripts/build_kanji_ids.py [path/to/ids_lv1.txt]

Without a path it downloads ids_lv1.txt at the pinned commit below.
Source and license details: DATA_SOURCES.md.
"""
import json
import os
import re
import sys
import unicodedata
import urllib.request

COMMIT = "2597437b928e8d530b7ae09cf53fe5ec7868569c"  # yi-bai/ids, 2026-10-31
URL = f"https://raw.githubusercontent.com/yi-bai/ids/{COMMIT}/ids_lv1.txt"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kanji_ids_data.json")

IDS_OPERATOR_RE = re.compile(r"[⿰-⿿㇯]")
# Variant notes and stroke descriptions that aren't part of the structure
NOTES_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}")
# The 214 Kangxi radicals stay whole (木, 口, 日, ...): this dataset splits even those into
# strokes, which would stop e.g. 木 and 本 from sharing a component.
KANGXI_RADICALS = {unicodedata.normalize("NFKC", chr(cp)) for cp in range(0x2F00, 0x2FD6)}


def keep(char: str) -> bool:
    cp = ord(char)
    return 0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF


def pick_sequence(column: str) -> str:
    """The Japanese form if one is marked (J), else the default (.) or first form."""
    seqs = [s for s in column.split(";") if s]
    def tags(seq: str) -> set:
        return {t for group in re.findall(r"\(([^)]*)\)", seq) for t in group.split(",")}
    for wanted in ("J", "."):
        for seq in seqs:
            if wanted in tags(seq):
                return seq
    return seqs[0] if seqs else ""


def clean(char: str, seq: str) -> str:
    if char in KANGXI_RADICALS:
        return char
    ids = NOTES_RE.sub("", seq).replace("?", "#").strip()
    # No operator left means the character is atomic (e.g. 一, 口): map it to itself
    return ids if IDS_OPERATOR_RE.search(ids) else char


def main() -> None:
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            text = f.read()
    else:
        with urllib.request.urlopen(URL, timeout=60) as resp:
            text = resp.read().decode("utf-8")

    ids_map = {}
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) < 2 or len(cols[0]) != 1 or not keep(cols[0]):
            continue
        ids_map[cols[0]] = clean(cols[0], pick_sequence(cols[1]))

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(ids_map.items())), f, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {len(ids_map):,} characters to {OUT}")


if __name__ == "__main__":
    main()
