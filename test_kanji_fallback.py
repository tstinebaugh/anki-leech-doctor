"""Integration tests: need Anki running with AnkiConnect, and (for the second test)
a real Gemini API key in config.json. They spend API quota, so they're skipped by
default. Run them with:  pytest -m integration
"""
import asyncio
import json
import os

import pytest

from anki_client import AnkiClient
from gemini_client import GeminiClient

pytestmark = pytest.mark.integration

REAL_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def _real_config() -> dict:
    try:
        with open(REAL_CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def test_get_kanji_details_missing_kanji():
    anki = AnkiClient()
    if not anki.is_connected():
        pytest.skip("AnkiConnect is offline")
    deck = _real_config().get("kanjiDeckName")
    if not deck:
        pytest.skip("No kanjiDeckName set in config.json")

    # A rare kanji most story decks don't cover, and a very common one they do
    details = anki.get_kanji_details(["嬉", "見"], deck_name=deck)

    assert details["嬉"]["found"] is False
    assert details["嬉"]["keyword"] is None
    assert details["嬉"]["myStory"] is None
    assert details["見"]["found"] is True
    assert details["見"]["keyword"] is not None


def test_generate_mnemonic_with_missing_rtk_kanji():
    async def _run():
        gemini = GeminiClient(config_path=REAL_CONFIG)
        if not gemini.api_key or "YOUR_GEMINI" in gemini.api_key:
            pytest.skip("No Gemini API key in config.json")

        kanji_details = {
            "嬉": {
                "kanji": "嬉",
                "found": False,
                "keyword": None,
                "myStory": None,
                "koohiiStory1": None,
                "heisigStory": None,
            }
        }

        try:
            result = await gemini.generate_mnemonic(
                vocab_kanji="嬉しい",
                vocab_furigana="嬉[うれ]しい",
                vocab_def="happy; glad; joyful",
                kanji_details=kanji_details,
                notes="JLPT N4 vocabulary",
            )
        except RuntimeError as e:
            if "API key not valid" in str(e):
                pytest.skip("Invalid Gemini API key in config.json")
            raise

        mnemonic = result.get("mnemonic", "")
        # No "Unknown" stand-in for the missing keyword
        assert "unknown" not in mnemonic.lower()
        # No conversational intro or outro fluff
        assert not mnemonic.lower().startswith("here is")
        assert not mnemonic.lower().startswith("sure")
        assert "why this works" not in mnemonic.lower()
        # Starts with a hook
        assert "Quick Hook" in mnemonic or "TL;DR" in mnemonic or "Hook" in mnemonic

    asyncio.run(_run())
