"""Default settings, in one place.

Anything here can be overridden in config.json or from the Settings modal.
The defaults are deliberately generic so the app works on any Anki collection.
"""
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Paths (overridable with env vars, e.g. for tests or running several profiles)
CONFIG_PATH = os.environ.get("LEECH_DOCTOR_CONFIG", os.path.join(APP_DIR, "config.json"))
RAG_STORAGE_PATH = os.environ.get("LEECH_DOCTOR_RAG_DIR", os.path.join(APP_DIR, ".rag_storage"))
# SQLite database: Gemini call log, model cooldowns and learned quotas (see db.py)
DB_PATH = os.environ.get("LEECH_DOCTOR_DB", os.path.join(APP_DIR, "leech_doctor.db"))

DEFAULT_MODEL = "gemini-flash-latest"  # Google's alias for the current Flash model

DEFAULT_MINING_DECK = "Mining"
DEFAULT_GRAMMAR_DECK_BASE = "Mining::Grammar"  # cards go to <base>::N5 ... <base>::N1
DEFAULT_LEECH_QUERY = "tag:leech is:suspended"
# Anki search that limits "All Review Cards" and the totals, e.g. 'deck:"Core 2k*"'.
# Empty means the whole collection.
DEFAULT_REVIEW_SCOPE = ""
# Deck holding your kanji stories (RTK, NihongoShark, ...). Empty = look for any deck named *Kanji*.
DEFAULT_KANJI_DECK = ""
# Note type used for mined cards. Fields are matched by name (see anki_client.FIELD_CANDIDATES);
# set "miningFieldMap" in config.json for note types with other field names.
DEFAULT_NOTE_TYPE = "Japanese sentences"

DEFAULT_PERSONA = (
    "Curious language learner who appreciates vivid, slightly absurd, witty, and memorable humor. "
    "Prefers concrete visual imagery over abstract descriptions."
)

DEFAULT_CONFIG = {
    "apiKey": "",  # falls back to the GEMINI_API_KEY / GOOGLE_API_KEY env vars
    "model": DEFAULT_MODEL,
    # Gemini 3+ thinking cap. The model thinks only as much as a task needs, so short requests cost
    # about the same at any level; "medium" leaves room for nuanced grammar and readings.
    "thinkingLevel": "medium",
    "jlptLevel": "N3",
    "kanjiDeckName": DEFAULT_KANJI_DECK,
    "kanjiStrategy": "hybrid",  # "hybrid" (deck stories + AI fallback) or "ai_only"
    "mnemonicStyle": "playful",  # "playful", "historical", "cinematic", "minimalist"
    "mnemonicTone": "Absurd, vivid, funny, and memorable with clear phonetic reading puns",
    "targetMiningDeck": DEFAULT_MINING_DECK,
    "grammarDeckBase": DEFAULT_GRAMMAR_DECK_BASE,
    "leechSearchQuery": DEFAULT_LEECH_QUERY,
    "reviewScopeQuery": DEFAULT_REVIEW_SCOPE,
    "miningNoteType": DEFAULT_NOTE_TYPE,
    "miningFieldMap": {},
    "persona": DEFAULT_PERSONA,
}
