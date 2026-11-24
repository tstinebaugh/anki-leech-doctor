"""Duplicate check before mining: exact matches, grammar scope, and the analyze route."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from anki_client import AnkiClient, word_forms


@pytest.mark.parametrize("field,expected", [
    ("〜ばかり", {"ばかり"}),
    ("しか〜ない", {"しかない"}),
    ("〜のです / 〜んです", {"のです", "んです"}),
    ("〜のだ・〜んだ", {"のだ", "んだ"}),
    ("〜かけだ / 〜かけの / 〜かける", {"かけだ", "かけの", "かける"}),
    ("省みる・顧みる", {"省みる", "顧みる"}),
    ("ハード(な)", {"ハード", "ハードな"}),
    ("(ボタンが)取れる", {"取れる", "ボタンが取れる"}),
    ("減り張り（を付ける）", {"減り張り", "減り張りを付ける"}),
    ("遺産[1]", {"遺産"}),
    ("肉親[にくしん]", {"肉親"}),
    ("<div><div>摘む[1]</div><div></div></div>", {"摘む"}),
    ("署名&nbsp; ", {"署名"}),
    ("", set()),
])
def test_word_forms(field, expected):
    assert word_forms(field) == expected


def _note(note_id, word, deck_card=1, tags=(), definition="def"):
    return {"noteId": note_id, "cards": [note_id * 10], "modelName": "Japanese sentences", "tags": list(tags),
            "fields": {"VocabKanji": {"value": word}, "VocabFurigana": {"value": ""}, "VocabDef": {"value": definition}}}


def _fake_anki(notes, decks=None):
    """invoke() stand-in answering the four AnkiConnect actions the lookup uses."""
    calls = []

    def invoke(action, **params):
        calls.append((action, params))
        if action == "findNotes":
            return [n["noteId"] for n in notes]
        if action == "notesInfo":
            return [n for n in notes if n["noteId"] in params["notes"]]
        if action == "getDecks":
            return decks or {"Deck": params["cards"]}
        if action == "areSuspended":
            return [False for _ in params["cards"]]
        raise AssertionError(action)
    return invoke, calls


def test_only_exact_words_match():
    client = AnkiClient()
    notes = [_note(1, "出す"), _note(2, "引き出す"), _note(3, "<div>出す[2]</div>"), _note(4, "出す・だす")]
    invoke, calls = _fake_anki(notes)
    with patch.object(client, "invoke", side_effect=invoke):
        found = client.find_existing_notes("出す")
    assert [m["noteId"] for m in found] == [1, 3, 4]
    query = calls[0][1]["query"]
    assert '"VocabKanji:*出す*"' in query and "Kanji:" not in query.replace("VocabKanji:", "")


def test_grammar_mode_compares_against_grammar_notes_only():
    client = AnkiClient()
    notes = [_note(1, "しか〜ない", tags=["grammar"]), _note(2, "〜のです / 〜んです", tags=["grammar"])]
    invoke, calls = _fake_anki(notes)
    with patch.object(client, "invoke", side_effect=invoke):
        found = client.find_existing_notes("しかない", grammar_only=True)
    assert calls[0][1]["query"] == '(tag:grammar OR "deck:*grammar*")'
    assert [(m["noteId"], m["vocabKanji"], m["isGrammar"]) for m in found] == [(1, "しか〜ない", True)]


def test_search_values_are_escaped():
    client = AnkiClient()
    invoke, calls = _fake_anki([])
    with patch.object(client, "invoke", side_effect=invoke):
        client.find_existing_notes('a*b_"c')
    assert r'*a\*b\_\"c*' in calls[0][1]["query"]


GRAMMAR_ANALYSIS = {"vocabKanji": "〜ばかり", "vocabFurigana": "〜ばかり", "vocabDef": "just did", "sentKanji": "",
                    "sentFurigana": "", "sentEng": "", "notes": "", "jlptLevel": "N4"}


def test_analyze_returns_existing_notes_without_calling_gemini():
    import app as app_module
    match = {"noteId": 5, "cardId": 50, "deckName": "Grammar::N4", "vocabKanji": "〜ばかり", "isGrammar": True}
    with patch.object(app_module.anki, "find_existing_notes", return_value=[match]) as find, \
         patch.object(app_module.gemini, "analyze_grammar") as analyze:
        res = TestClient(app_module.app).post("/api/mining/analyze", json={"vocab": "ばかり", "cardType": "grammar"})
    assert res.status_code == 200
    assert res.json() == {"duplicate": True, "query": "ばかり", "matches": [match]}
    assert find.call_args.kwargs["grammar_only"] is True
    analyze.assert_not_called()


def test_mine_anyway_skips_the_check():
    import app as app_module
    with patch.object(app_module.anki, "find_existing_notes") as find, \
         patch.object(app_module.gemini, "analyze_grammar", return_value=dict(GRAMMAR_ANALYSIS)) as analyze, \
         patch.object(app_module.gemini, "generate_personalized_sentence", side_effect=RuntimeError("skip")), \
         patch.object(app_module.rag, "search_similar", return_value=[]):
        res = TestClient(app_module.app).post(
            "/api/mining/analyze", json={"vocab": "ばかり", "cardType": "grammar", "allowDuplicate": True}
        )
    assert res.status_code == 200 and res.json().get("isDraft") is True
    find.assert_not_called()
    analyze.assert_called_once()


def test_anki_being_unreachable_does_not_block_mining():
    import app as app_module
    with patch.object(app_module.anki, "find_existing_notes", side_effect=ConnectionError("Anki is closed")), \
         patch.object(app_module.gemini, "analyze_grammar", return_value=dict(GRAMMAR_ANALYSIS)) as analyze, \
         patch.object(app_module.gemini, "generate_personalized_sentence", side_effect=RuntimeError("skip")), \
         patch.object(app_module.rag, "search_similar", return_value=[]):
        res = TestClient(app_module.app).post("/api/mining/analyze", json={"vocab": "ばかり", "cardType": "grammar"})
    assert res.status_code == 200
    analyze.assert_called_once()


def test_browse_opens_the_note_in_anki():
    import app as app_module
    with patch.object(app_module.anki, "invoke") as invoke:
        res = TestClient(app_module.app).post("/api/anki/browse", json={"noteId": 42})
    assert res.status_code == 200
    invoke.assert_called_once_with("guiBrowse", query="nid:42")
