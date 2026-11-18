import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app import app
from utils import format_notes_for_anki

client = TestClient(app)

def test_format_notes_for_anki():
    markdown = "### 🧠 Quick Hook\nTest summary\n\n### 📖 The Scene\nStory line\n\n**Bold Word**\n---\nFootnote"
    html = format_notes_for_anki(markdown)
    assert "<h3>🧠 Quick Hook</h3>" in html
    assert "<h3>📖 The Scene</h3>" in html
    assert "<b>Bold Word</b>" in html
    assert "<hr>" in html

def test_get_config_and_status():
    res = client.get("/api/config")
    assert res.status_code == 200
    data = res.json()
    assert "jlptLevel" in data
    assert "mnemonicStyle" in data
    assert "kanjiStrategy" in data
    assert "targetMiningDeck" in data

    status_res = client.get("/api/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert "jlptLevel" in status_data
    assert "mnemonicStyle" in status_data

def test_update_config():
    res = client.post("/api/config", json={
        "jlptLevel": "N2",
        "mnemonicStyle": "historical",
        "kanjiStrategy": "ai_only"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["config"]["jlptLevel"] == "N2"
    assert data["config"]["mnemonicStyle"] == "historical"
    assert data["config"]["kanjiStrategy"] == "ai_only"

    # Reset back to N3 playful
    client.post("/api/config", json={
        "jlptLevel": "N3",
        "mnemonicStyle": "playful",
        "kanjiStrategy": "hybrid"
    })

def test_index_page_and_assets():
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert "deck-select" in html
    assert "setting-jlpt-level" in html
    assert "btn-style-pill" in html
    assert "modal-card-settings" in html
    assert "Leech<strong>Doctor</strong>" in html

@pytest.mark.anyio
async def test_mining_analyze_endpoint():
    with patch("app.gemini.analyze_vocab") as mock_analyze, \
         patch("app.gemini.generate_personalized_sentence", side_effect=RuntimeError("offline")), \
         patch("app.rag.search_similar", return_value=[]):
        mock_analyze.return_value = {
            "vocabKanji": "限界",
            "vocabFurigana": "限界[げんかい]",
            "vocabDef": "limit; boundary",
            "sentKanji": "これが私の限界です。",
            "sentFurigana": "これが 私[わたし]の 限界[げんかい]です。",
            "sentEng": "This is my limit.",
            "pitchPattern": "0",
            "pitchNum": "Heiban"
        }
        res = client.post("/api/mining/analyze", json={
            "vocab": "限界",
            "jlptLevel": "N3"
        })
        assert res.status_code == 200
        card = res.json()
        assert card["vocabKanji"] == "限界"
        assert card["isDraft"] is True
        assert "限" in card["kanjiChars"]
        assert "界" in card["kanjiChars"]

@pytest.mark.anyio
async def test_generate_mnemonic_endpoint():
    with patch("app.gemini.generate_mnemonic") as mock_gen:
        mock_gen.return_value = {
            "mnemonic": "### 🧠 Quick Hook\nPush past the boundary.\n\n### 📖 The Scene\nEpic training arc."
        }
        res = client.post("/api/generate-mnemonic", json={
            "vocabKanji": "限界",
            "vocabFurigana": "げんかい",
            "vocabDef": "limit",
            "kanjiDetails": {},
            "mnemonicStyle": "cinematic"
        })
        assert res.status_code == 200
        data = res.json()
        assert "mnemonic" in data
        assert "Quick Hook" in data["mnemonic"]

def test_delete_card_endpoint():
    with patch("app.anki.delete_card_or_note") as mock_del_anki, \
         patch("app.rag.delete_card") as mock_del_rag:
        mock_del_anki.return_value = True
        mock_del_rag.return_value = True

        res = client.post("/api/card/delete", json={
            "cardId": 12345,
            "noteId": 67890
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        mock_del_anki.assert_called_once_with(card_id=12345, note_id=67890)
        mock_del_rag.assert_called_once_with(12345)

def test_delete_card_validation():
    res = client.post("/api/card/delete", json={})
    assert res.status_code == 400

def test_anki_client_delete_card_or_note():
    from anki_client import AnkiClient
    client_instance = AnkiClient()
    with patch.object(client_instance, "invoke") as mock_invoke:
        mock_invoke.side_effect = lambda action, **kwargs: [1] if action == "deleteNotes" else None
        res = client_instance.delete_card_or_note(note_id=999)
        assert res is True
        mock_invoke.assert_called_with("deleteNotes", notes=[999])

def test_save_vocab_endpoint():
    with patch("app.anki.update_vocab_fields") as mock_update_vocab, \
         patch("app.anki.invoke") as mock_invoke, \
         patch("app.rag.index_cards") as mock_index:
        mock_update_vocab.return_value = True
        mock_invoke.return_value = [101]
        
        res = client.post("/api/sync/save-vocab", json={
            "noteId": 555,
            "vocabKanji": "遅刻",
            "vocabFurigana": "遅刻[ちこく]",
            "vocabDef": "lateness; tardiness"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        mock_index.assert_called_once()
        mock_update_vocab.assert_called_once_with(
            note_id=555,
            vocab_kanji="遅刻",
            vocab_furigana="遅刻[ちこく]",
            vocab_def="lateness; tardiness"
        )

def test_anki_client_update_vocab_fields():
    from anki_client import AnkiClient
    client_instance = AnkiClient()
    with patch.object(client_instance, "invoke") as mock_invoke:
        def fake_invoke(action, **kwargs):
            if action == "notesInfo":
                return [{"noteId": 123, "fields": {"VocabKanji": {"value": "old"}, "VocabFurigana": {"value": "old"}, "VocabDef": {"value": "old"}}}]
            elif action == "updateNoteFields":
                return None
            return None
        mock_invoke.side_effect = fake_invoke
        res = client_instance.update_vocab_fields(123, "遅刻", "遅刻[ちこく]", "lateness")
        assert res is True

def test_undo_unsuspend_endpoint():
    with patch("app.anki.resuspend_and_releech") as mock_resuspend:
        mock_resuspend.return_value = True
        res = client.post("/api/sync/undo-unsuspend", json={
            "cardId": 12345,
            "noteId": 67890
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        mock_resuspend.assert_called_once_with(12345, 67890)

def test_anki_client_resuspend_and_releech():
    from anki_client import AnkiClient
    client_instance = AnkiClient()
    calls = []
    with patch.object(client_instance, "invoke") as mock_invoke:
        mock_invoke.side_effect = lambda action, **kwargs: calls.append((action, kwargs))
        res = client_instance.resuspend_and_releech(111, 222)
        assert res is True
        assert ("suspend", {"cards": [111]}) in calls
        assert ("addTags", {"notes": [222], "tags": "leech"}) in calls
        assert ("removeTags", {"notes": [222], "tags": "ai-mnemonic-reviewed"}) in calls

def test_find_leech_cards_covers_mining_deck():
    from anki_client import AnkiClient
    client_instance = AnkiClient()
    with patch.object(client_instance, "invoke") as mock_invoke:
        def fake_invoke(action, **kwargs):
            if action == "findCards":
                query = kwargs.get("query", "")
                if 'deck:"Custom Mining Deck"' in query:
                    return [99901]
                elif "default_query" in query or "tag:leech is:suspended" in query or "is:suspended" in query:
                    return [10001, 10002]
                return []
            elif action == "cardsInfo":
                return [
                    {
                        "cardId": cid,
                        "note": cid + 1000,
                        "deckName": "Custom Mining Deck" if cid == 99901 else "Core Deck",
                        "queue": -1,
                        "due": 1,
                        "reps": 10,
                        "lapses": 5,
                        "fields": {
                            "VocabKanji": {"value": f"単語{cid}"},
                            "VocabFurigana": {"value": ""},
                            "VocabDef": {"value": "meaning"},
                            "SentKanji": {"value": ""},
                            "SentFurigana": {"value": ""},
                            "SentEng": {"value": ""},
                            "Notes": {"value": ""}
                        }
                    }
                    for cid in kwargs.get("cards", [])
                ]
            return None
        mock_invoke.side_effect = fake_invoke
        cards = client_instance.find_leech_cards(
            deck_query=None,
            mining_deck="Custom Mining Deck"
        )
        card_ids = [c["cardId"] for c in cards]
        assert 10001 in card_ids
        assert 10002 in card_ids
        assert 99901 in card_ids  # Mining deck suspended leech is included!

def test_get_deck_stats_unique_leeches():
    from anki_client import AnkiClient
    client_instance = AnkiClient()
    with patch.object(client_instance, "invoke") as mock_invoke:
        def fake_invoke(action, **kwargs):
            if action == "deckNames":
                return ["ParentDeck", "ParentDeck::SubDeck", "Mining Deck"]
            elif action == "findCards":
                query = kwargs.get("query", "")
                if query == "tag:leech is:suspended":
                    # Actual unique leeches in collection
                    return [1, 2]
                elif "tag:leech is:suspended" in query:
                    if "ParentDeck::SubDeck" in query:
                        return [1]
                    elif "Mining Deck" in query:
                        return [2]
                    elif "ParentDeck" in query:
                        # Parent deck query returns subdeck cards too
                        return [1]
                else:
                    return [1, 2, 3]
            elif action == "multi":
                return [{"result": fake_invoke(a["action"], **a["params"]), "error": None} for a in kwargs["actions"]]
            return []
        mock_invoke.side_effect = fake_invoke
        stats = client_instance.get_deck_stats()
        assert stats["totalLeeches"] == 2  # Exactly 2 unique, not 3 from double-counting!
        assert "totalActiveLeeches" in stats

def test_status_health_response():
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert "ankiOnline" in data
    assert "hasApiKey" in data
    assert "ragReady" in data
    assert "ragStats" in data
    assert isinstance(data["ragStats"], dict)

def test_find_leech_cards_with_active_and_search():
    from anki_client import AnkiClient
    client_instance = AnkiClient()
    queries_made = []

    with patch.object(client_instance, "invoke") as mock_invoke:
        def fake_invoke(action, **kwargs):
            if action == "findCards":
                q = kwargs.get("query", "")
                queries_made.append(q)
                if "tag:leech -is:suspended" in q:
                    return [501]
                elif "避難" in q:
                    return [502]
                return [101]
            elif action == "cardsInfo":
                return [{
                    "cardId": cid,
                    "note": cid + 10,
                    "deckName": "Mining Deck",
                    "queue": 2,
                    "due": 1,
                    "reps": 5,
                    "lapses": 4,
                    "fields": {
                        "VocabKanji": {"value": "避難"},
                        "VocabFurigana": {"value": "避難[ひなん]"},
                        "VocabDef": {"value": "taking refuge"},
                        "SentKanji": {"value": ""},
                        "SentFurigana": {"value": ""},
                        "SentEng": {"value": ""},
                        "Notes": {"value": ""}
                    }
                } for cid in kwargs.get("cards", [])]
            return None

        mock_invoke.side_effect = fake_invoke

        # Active status test
        active_cards = client_instance.find_leech_cards(leech_status="active")
        assert len(active_cards) > 0
        assert any("tag:leech -is:suspended" in q for q in queries_made)

        # Search term test
        search_cards = client_instance.find_leech_cards(search_term="避難")
        assert len(search_cards) > 0
        assert any("避難" in q for q in queries_made)

def test_cards_api_endpoint_filters():
    with patch("app.anki.find_leech_cards") as mock_find:
        mock_find.return_value = [{"cardId": 99, "vocabKanji": "検索テスト", "suspended": False}]
        
        # Test status parameter
        res_active = client.get("/api/cards?status=active")
        assert res_active.status_code == 200
        assert res_active.json()["count"] == 1
        mock_find.assert_called_with(
            deck_query=None,
            custom_query=None,
            default_query="tag:leech is:suspended",
            mining_deck="Mining",
            leech_status="active",
            search_term=None,
            review_scope=""
        )

        # Test search parameter
        res_search = client.get("/api/cards?search=検索")
        assert res_search.status_code == 200
        mock_find.assert_called_with(
            deck_query=None,
            custom_query=None,
            default_query="tag:leech is:suspended",
            mining_deck="Mining",
            leech_status="suspended",
            search_term="検索",
            review_scope=""
        )

def test_validate_persona_sentence():
    from gemini_client import validate_persona_sentence

    # 1. Perfectly valid sentence
    valid_data = {
        "sent_kanji": "大雨の時は<b>避難</b>所に移動します。",
        "sent_furigana": "大雨[おおあめ]の 時[とき]は<b> 避難[ひなん]</b> 所[じょ]に 移動[いどう]します。"
    }
    is_valid, errors = validate_persona_sentence(valid_data, "避難")
    assert is_valid is True
    assert len(errors) == 0

    # 2. sent_kanji has bracket furigana -> INVALID
    invalid_furigana_in_kanji = {
        "sent_kanji": "大雨の時は<b>避難[ひなん]</b>所に移動します。",
        "sent_furigana": "大雨[おおあめ]の 時[とき]は<b> 避難[ひなん]</b> 所[じょ]に 移動[いどう]します。"
    }
    is_valid, errors = validate_persona_sentence(invalid_furigana_in_kanji, "避難")
    assert is_valid is False
    assert any("sent_kanji contains bracket furigana" in e for e in errors)

    # 3. Missing bold tags -> INVALID
    invalid_no_bold = {
        "sent_kanji": "大雨の時は避難所に移動します。",
        "sent_furigana": "大雨[おおあめ]の 時[とき]は 避難[ひなん] 所[じょ]に 移動[いどう]します。"
    }
    is_valid, errors = validate_persona_sentence(invalid_no_bold, "避難")
    assert is_valid is False
    assert any("missing <b>...</b> bold tags" in e for e in errors)

    # 4. sent_furigana has kanji missing furigana -> INVALID
    invalid_missing_kanji_furi = {
        "sent_kanji": "大雨の時は<b>避難</b>所に移動します。",
        "sent_furigana": "大雨の 時[とき]は<b> 避難[ひなん]</b>所に 移動[いどう]します。"
    }
    is_valid, errors = validate_persona_sentence(invalid_missing_kanji_furi, "避難")
    assert is_valid is False
    assert any("missing bracket furigana" in e for e in errors)

@pytest.mark.anyio
async def test_generate_personalized_sentence_retry():
    from gemini_client import GeminiClient
    client_instance = GeminiClient()

    # Attempt 1: sent_kanji has furigana and missing bold
    bad_resp = '{"theme_used": "🏍️ Riding", "sent_kanji": "山道で避難[ひなん]した。", "sent_furigana": "山道[やまみち]で 避難[ひなん]した。", "sent_eng": "Took refuge.", "rationale": "Good"}'
    # Attempt 2: corrected response
    good_resp = '{"theme_used": "🏍️ Riding", "sent_kanji": "山道で<b>避難</b>した。", "sent_furigana": "山道[やまみち]で<b> 避難[ひなん]</b>した。", "sent_eng": "Took refuge on the mountain road.", "rationale": "Vivid"}'

    with patch.object(client_instance, "_call_gemini") as mock_call:
        mock_call.side_effect = [bad_resp, good_resp]

        res = await client_instance.generate_personalized_sentence(
            vocab_kanji="避難",
            vocab_furigana="ひなん",
            vocab_def="taking refuge",
            personas=["Motorcycle Riding"]
        )

        assert mock_call.call_count == 2
        # Verify second call included feedback
        second_call_contents = mock_call.call_args_list[1][0][0]
        assert len(second_call_contents) == 3  # initial user, model bad_resp, user feedback
        assert "FORMATTING VALIDATION FAILED" in second_call_contents[2]["parts"][0]["text"]
        
        # Verify returned data is the corrected one
        assert res["sentKanji"] == "山道で<b>避難</b>した。"
        assert "<b> 避難[ひなん]</b>" in res["sentFurigana"]
        assert res["themeUsed"] == "🏍️ Riding"


@pytest.mark.anyio
async def test_gemini_fallback_and_error_transparency():
    from gemini_client import GeminiClient

    client = GeminiClient()
    client.config["apiKey"] = "fake-api-key"
    client.config["model"] = "gemini-flash-latest"

    # Test list_available_models priority
    models = await client.list_available_models()
    assert "gemini-flash-latest" in models
    assert "gemini-flash-lite-latest" in models
    assert "gemini-3-flash-preview" in models

    # Test fallback: primary model gets 429, fallback gets 200
    with patch("httpx.AsyncClient.post") as mock_post:
        # 1st call (gemini-flash-latest): 429 Quota Exceeded
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = '{"error": {"code": 429, "message": "Quota exceeded"}}'
        resp_429.json.return_value = {"error": {"code": 429, "message": "Quota exceeded"}}

        # 2nd call (gemini-flash-lite-latest): 200 OK
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"text": "Success from fallback"}]}}
            ]
        }

        mock_post.side_effect = [resp_429, resp_200]

        result = await client._call_gemini([{"parts": [{"text": "hello"}]}])
        assert result == "Success from fallback"
        assert mock_post.call_count == 2
        # Verify first was primary model, second was fallback
        first_url = mock_post.call_args_list[0][0][0]
        second_url = mock_post.call_args_list[1][0][0]
        assert "gemini-flash-latest" in first_url
        assert "gemini-flash-lite-latest" in second_url
        # The key travels in a header, never in the URL
        assert "fake-api-key" not in first_url
        assert mock_post.call_args_list[0].kwargs["headers"]["x-goog-api-key"] == "fake-api-key"


@pytest.mark.anyio
async def test_gemini_all_fail_includes_primary_error():
    from gemini_client import GeminiClient

    client = GeminiClient()
    client.config["apiKey"] = "fake-api-key"
    client.config["model"] = "gemini-flash-latest"

    with patch("httpx.AsyncClient.post") as mock_post:
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = '{"error": {"code": 429, "message": "Daily free limit reached for gemini-3.8-flash"}}'
        resp_429.json.return_value = {"error": {"code": 429, "message": "Daily free limit reached for gemini-3.8-flash"}}
        mock_post.return_value = resp_429

        with pytest.raises(RuntimeError) as exc_info:
            await client._call_gemini([{"parts": [{"text": "hello"}]}])

        err_text = str(exc_info.value)
        assert "gemini-flash-latest" in err_text
        assert "Daily free limit reached" in err_text


def test_find_leech_cards_not_reviewed_filter():
    from anki_client import AnkiClient
    client_instance = AnkiClient()
    queries_made = []

    with patch.object(client_instance, "invoke") as mock_invoke:
        def fake_invoke(action, **kwargs):
            if action == "findCards":
                q = kwargs.get("query", "")
                queries_made.append(q)
                if "-tag:ai-mnemonic-reviewed" in q:
                    return [777]
                return []
            elif action == "cardsInfo":
                return [{
                    "cardId": 777,
                    "note": 888,
                    "deckName": "JLPT Tango N3",
                    "queue": 2,
                    "due": 1,
                    "reps": 3,
                    "lapses": 0,
                    "fields": {
                        "VocabKanji": {"value": "未復習"},
                        "VocabFurigana": {"value": "未復習[みふくしゅう]"},
                        "VocabDef": {"value": "unreviewed"},
                        "SentKanji": {"value": ""},
                        "SentFurigana": {"value": ""},
                        "SentEng": {"value": ""},
                        "Notes": {"value": ""}
                    }
                }]
            return None

        mock_invoke.side_effect = fake_invoke

        # Test collection-wide not_reviewed
        cards = client_instance.find_leech_cards(leech_status="not_reviewed")
        assert len(cards) == 1
        assert cards[0]["vocabKanji"] == "未復習"
        assert any("-tag:ai-mnemonic-reviewed" in q for q in queries_made)

        # Test deck-specific not_reviewed
        queries_made.clear()
        deck_cards = client_instance.find_leech_cards(deck_query="JLPT Tango N3", leech_status="not_reviewed")
        assert len(deck_cards) == 1
        assert any('deck:"JLPT Tango N3" -tag:ai-mnemonic-reviewed' in q for q in queries_made)


def test_cards_api_not_reviewed_route():
    with patch("app.anki.find_leech_cards") as mock_find:
        mock_find.return_value = [{"cardId": 777, "vocabKanji": "未復習", "suspended": False}]
        res = client.get("/api/cards?status=not_reviewed")
        assert res.status_code == 200
        assert res.json()["count"] == 1
        mock_find.assert_called_with(
            deck_query=None,
            custom_query=None,
            default_query="tag:leech is:suspended",
            mining_deck="Mining",
            leech_status="not_reviewed",
            search_term=None,
            review_scope=""
        )





# ---------------------------------------------------------------------------
# Grammar mining + mined-card save path
# ---------------------------------------------------------------------------

def test_mining_analyze_grammar_endpoint():
    with patch("app.gemini.analyze_grammar") as mock_grammar, \
         patch("app.gemini.analyze_vocab") as mock_vocab, \
         patch("app.anki.get_kanji_details") as mock_kanji, \
         patch("app.gemini.generate_personalized_sentence", side_effect=RuntimeError("offline")), \
         patch("app.rag.search_similar", return_value=[]):
        mock_grammar.return_value = {
            "vocabKanji": "〜ばかり",
            "vocabFurigana": "〜ばかり",
            "vocabDef": "just did ~; nothing but ~",
            "sentKanji": "日本に来た<b>ばかり</b>です。",
            "sentFurigana": " 日本[にほん]に 来[き]た<b>ばかり</b>です。",
            "sentEng": "I just came to Japan.",
            "pitchNum": "",
            "pitchPattern": "",
            "notes": "**Formation:** V-た + ばかり",
            "jlptLevel": "N4",
        }
        res = client.post("/api/mining/analyze", json={
            "vocab": "〜ばかり",
            "jlptLevel": "N4",
            "cardType": "grammar",
        })
        assert res.status_code == 200
        card = res.json()
        mock_grammar.assert_called_once()
        mock_vocab.assert_not_called()
        mock_kanji.assert_not_called()
        assert card["cardType"] == "grammar"
        assert card["jlptLevel"] == "N4"
        assert card["deckName"] == "Mining::Grammar::N4"
        assert card["kanjiChars"] == []
        assert "V-た + ばかり" in card["notes"]
        assert "grammar" in card["tags"]


def test_create_mined_grammar_card_routes_to_grammar_deck():
    from anki_client import AnkiClient
    anki_instance = AnkiClient()
    calls = []

    def fake_invoke(action, **kwargs):
        calls.append((action, kwargs))
        if action == "deckNames":
            return ["Core::N4"]
        if action == "modelFieldNames":
            return ["VocabKanji", "VocabFurigana", "VocabDef", "SentKanji", "SentFurigana", "SentEng", "Notes"]
        if action == "addNote":
            return 555
        if action == "findCards":
            return [777]
        return None

    with patch.object(anki_instance, "invoke", side_effect=fake_invoke):
        created = anki_instance.add_mining_note(
            vocab_kanji="〜ばかり", vocab_furigana="〜ばかり", vocab_def="just did ~",
            sent_kanji="来た<b>ばかり</b>", sent_furigana=" 来[き]た<b>ばかり</b>", sent_eng="just came",
            notes="**Formation:** V-た + ばかり", card_type="grammar", jlpt_level="n4",
        )

    note = next(kw["note"] for action, kw in calls if action == "addNote")
    assert note["deckName"] == "Mining::Grammar::N4"
    assert note["modelName"] == "Japanese sentences"
    assert note["fields"]["VocabKanji"] == "〜ばかり"
    assert set(note["tags"]) >= {"grammar", "jlpt::N4", "mined", "ai-mnemonic-reviewed"}
    assert ("createDeck", {"deck": "Mining::Grammar::N4"}) in calls
    # Returned card carries what the frontend merges in after save
    assert created["cardId"] == 777 and created["noteId"] == 555
    assert "grammar" in created["tags"]
    assert created["notes"]


def test_create_card_endpoint_indexes_real_card_id_and_passes_grammar():
    created = {
        "cardId": 777, "noteId": 555,
        "deckName": "Mining::Grammar::N4",
        "notes": "<b>Formation</b>", "tags": ["grammar", "jlpt::N4"],
    }
    with patch("app.anki.add_mining_note", return_value=created) as mock_add, \
         patch("app.rag.index_cards") as mock_index, \
         patch("app._ensure_rag_deck") as mock_rag_deck:
        res = client.post("/api/mining/create-card", json={
            "vocabKanji": "〜ばかり", "vocabFurigana": "〜ばかり", "vocabDef": "just did ~",
            "sentKanji": "来た<b>ばかり</b>", "sentFurigana": " 来[き]た<b>ばかり</b>", "sentEng": "just came",
            "notes": "**Formation:** V-た + ばかり",
            "cardType": "grammar", "jlptLevel": "N4",
        })
        assert res.status_code == 200
        kwargs = mock_add.call_args.kwargs
        assert kwargs["card_type"] == "grammar"
        assert kwargs["jlpt_level"] == "N4"
        mock_rag_deck.assert_called_once_with("Mining::Grammar::N4")
        indexed = mock_index.call_args.args[0][0]
        assert indexed["cardId"] == 777
        assert indexed["noteId"] == 555
        assert indexed["sentFurigana"] == " 来[き]た<b>ばかり</b>"


def test_validate_persona_sentence_grammar_mode():
    from gemini_client import validate_persona_sentence
    parsed = {
        "sent_kanji": "ご飯を<b>食べたばかり</b>です。",
        "sent_furigana": "ご 飯[はん]を<b> 食[た]べたばかり</b>です。",
    }
    ok, errors = validate_persona_sentence(parsed, "〜ばかり", is_grammar=True)
    assert ok, errors
    # Vocab mode would reject it because the literal pattern isn't in the bold span
    ok_vocab, _ = validate_persona_sentence(parsed, "〜ばかり")
    assert not ok_vocab
    # Grammar mode still requires the bold tags
    ok_missing, _ = validate_persona_sentence({"sent_kanji": "食べたばかりです。", "sent_furigana": " 食[た]べたばかりです。"}, "〜ばかり", is_grammar=True)
    assert not ok_missing


def test_find_leech_cards_grammar_deck_falls_back_to_all_cards():
    from anki_client import AnkiClient
    anki_instance = AnkiClient()
    queries = []

    def fake_invoke(action, **kwargs):
        if action == "findCards":
            queries.append(kwargs["query"])
            return [] if "is:suspended" in kwargs["query"] else [1]
        if action == "cardsInfo":
            return [{"cardId": 1, "note": 9, "deckName": "Mining::Grammar::N4",
                     "fields": {"VocabKanji": {"value": "〜ばかり"}}, "queue": 0}]
        if action == "notesInfo":
            return [{"noteId": 9, "tags": ["grammar"]}]
        return None

    with patch.object(anki_instance, "invoke", side_effect=fake_invoke):
        cards = anki_instance.find_leech_cards(
            deck_query="Mining::Grammar::N4", leech_status="suspended"
        )
    assert len(cards) == 1
    assert queries[-1] == 'deck:"Mining::Grammar::N4"'


def test_format_notes_for_anki_passes_through_formatted_html():
    html = "<p><b>Formation:</b> V-た + ばかり</p><p><b>Nuance:</b> just happened</p>"
    assert format_notes_for_anki(html) == html
    # Markdown still converts to the same HTML
    assert format_notes_for_anki("**Formation:** V-た + ばかり\n\n**Nuance:** just happened") == html


@pytest.mark.anyio
async def test_analyze_grammar_rejects_invented_kanji_in_reading():
    import json as _json
    from gemini_client import GeminiClient
    g = GeminiClient()
    fake = _json.dumps({
        "pattern": "〜だけでなく", "pattern_furigana": "〜 堂[だけ]でなく", "meaning": "not only ~ but also",
        "formation": "N + だけでなく", "nuance": "adds info", "similar": ["〜に加えて: in addition to"],
        "jlpt_level": "N3", "sent_kanji": "安い<b>だけでなく</b>", "sent_furigana": " 安[やす]い<b>だけでなく</b>", "sent_eng": "not only cheap",
    })
    with patch.object(g, "_call_gemini", return_value=fake):
        res = await g.analyze_grammar("〜だけでなく", jlpt_level="N3")
    assert res["vocabFurigana"] == "〜だけでなく"
    assert res["jlptLevel"] == "N3"
    assert "<" not in res["notes"]  # notes stay markdown; frontend/server format them

    good = _json.loads(fake)
    good.update(pattern="〜に関して", pattern_furigana="〜に 関[かん]して")
    with patch.object(g, "_call_gemini", return_value=_json.dumps(good)):
        res = await g.analyze_grammar("〜に関して", jlpt_level="N3")
    assert res["vocabFurigana"] == "〜に 関[かん]して"


# ---------------------------------------------------------------------------
# Mining uses the persona sentence generator
# ---------------------------------------------------------------------------

_GRAMMAR_ANALYSIS = {
    "vocabKanji": "〜ばかり",
    "vocabFurigana": "〜ばかり",
    "vocabDef": "just did ~",
    "sentKanji": "日本に来た<b>ばかり</b>です。",
    "sentFurigana": " 日本[にほん]に 来[き]た<b>ばかり</b>です。",
    "sentEng": "I just came to Japan.",
    "notes": "**Formation:** V-た + ばかり",
    "jlptLevel": "N4",
}


def test_mining_analyze_uses_persona_sentence():
    persona = {
        "themeUsed": "🏍️ Motorcycle Riding & Mechanics",
        "sentKanji": "バイクを買った<b>ばかり</b>なのに、もう壊れた。",
        "sentFurigana": "バイクを 買[か]った<b>ばかり</b>なのに、もう 壊[こわ]れた。",
        "sentEng": "I just bought the bike and it's already broken.",
        "rationale": "Fresh purchase + instant breakdown sticks.",
    }
    with patch("app.gemini.analyze_grammar", return_value=dict(_GRAMMAR_ANALYSIS)), \
         patch("app.gemini.generate_personalized_sentence", return_value=persona) as mock_persona, \
         patch("app.rag.search_similar", return_value=[]):
        res = client.post("/api/mining/analyze", json={
            "vocab": "〜ばかり",
            "jlptLevel": "N4",
            "cardType": "grammar",
            "personas": ["Motorcycle Riding & Mechanics"],
        })
        assert res.status_code == 200
        card = res.json()
        kwargs = mock_persona.call_args.kwargs
        assert kwargs["personas"] == ["Motorcycle Riding & Mechanics"]
        assert kwargs["card_type"] == "grammar"
        assert kwargs["jlpt_level"] == "N4"
        assert kwargs["current_sentence"] == _GRAMMAR_ANALYSIS["sentKanji"]
        assert card["sentKanji"] == persona["sentKanji"]
        assert card["sentFurigana"] == persona["sentFurigana"]
        assert card["sentEng"] == persona["sentEng"]
        assert card["sentenceSource"] == "persona"
        assert card["personaSentence"]["themeUsed"] == persona["themeUsed"]
        assert card["personaSentence"]["rationale"] == persona["rationale"]


def test_mining_analyze_falls_back_when_persona_sentence_unusable():
    junk = {"themeUsed": "x", "sentKanji": "<b>〜ばかり</b>を使います。", "sentFurigana": "", "sentEng": "Raw generated response: ???", "rationale": "", "fallback": True}
    with patch("app.gemini.analyze_grammar", return_value=dict(_GRAMMAR_ANALYSIS)), \
         patch("app.gemini.generate_personalized_sentence", return_value=junk), \
         patch("app.rag.search_similar", return_value=[]):
        res = client.post("/api/mining/analyze", json={"vocab": "〜ばかり", "cardType": "grammar", "jlptLevel": "N4"})
        assert res.status_code == 200
        card = res.json()
        assert card["sentKanji"] == _GRAMMAR_ANALYSIS["sentKanji"]
        assert card["sentenceSource"] == "analysis"
        assert card["personaSentence"] is None


def test_mining_grammar_auto_level_uses_ai_pick():
    analysis = dict(_GRAMMAR_ANALYSIS, jlptLevel="N3")
    with patch("app.gemini.analyze_grammar", return_value=analysis) as mock_grammar, \
         patch("app.gemini.generate_personalized_sentence", side_effect=RuntimeError("offline")), \
         patch("app.rag.search_similar", return_value=[]):
        res = client.post("/api/mining/analyze", json={"vocab": "〜ばかり", "cardType": "grammar", "jlptLevel": "auto"})
        assert res.status_code == 200
        card = res.json()
        assert mock_grammar.call_args.kwargs["jlpt_level"] is None
        assert card["jlptLevel"] == "N3"
        assert card["deckName"] == "Mining::Grammar::N3"


def test_mining_grammar_manual_level_overrides_ai_pick():
    analysis = dict(_GRAMMAR_ANALYSIS, jlptLevel="N3")
    with patch("app.gemini.analyze_grammar", return_value=analysis) as mock_grammar, \
         patch("app.gemini.generate_personalized_sentence", side_effect=RuntimeError("offline")), \
         patch("app.rag.search_similar", return_value=[]):
        res = client.post("/api/mining/analyze", json={"vocab": "〜ばかり", "cardType": "grammar", "jlptLevel": "N5"})
        assert res.status_code == 200
        card = res.json()
        assert mock_grammar.call_args.kwargs["jlpt_level"] == "N5"
        assert card["jlptLevel"] == "N5"
        assert card["deckName"] == "Mining::Grammar::N5"



def test_get_deck_stats_uses_single_batched_request():
    from anki_client import AnkiClient
    client_instance = AnkiClient()
    calls = []
    def fake_invoke(action, **kwargs):
        calls.append(action)
        if action == "deckNames":
            return ["A", "B", "Empty"]
        if action == "multi":
            out = []
            for a in kwargs["actions"]:
                q = a["params"]["query"]
                if q.startswith('deck:"Empty"'):
                    out.append({"result": [], "error": None})
                elif "is:suspended" in q and "tag:leech" not in q:
                    out.append({"result": [7], "error": None})
                else:
                    out.append({"result": [1, 2, 3], "error": None})
            return out
        raise AssertionError(f"unexpected per-query call: {action}")
    with patch.object(client_instance, "invoke", side_effect=fake_invoke):
        stats = client_instance.get_deck_stats()
    assert calls == ["deckNames", "multi"]
    assert [d["name"] for d in stats["decks"]] == ["A", "B"]
    assert stats["decks"][0]["suspendedCount"] == 1
    assert stats["decks"][0]["totalCount"] == 3
    assert stats["totalSuspended"] == 1


# ---------------------------------------------------------------------------
# Open-source readiness: configurable scope, note types, safety
# ---------------------------------------------------------------------------

def test_review_scope_limits_all_review_cards_and_totals():
    from anki_client import AnkiClient
    client_instance = AnkiClient()
    queries = []

    def fake_invoke(action, **kwargs):
        if action == "findCards":
            queries.append(kwargs["query"])
            return []
        if action == "deckNames":
            return ["Core"]
        if action == "multi":
            queries.extend(a["params"]["query"] for a in kwargs["actions"])
            return [{"result": [], "error": None} for _ in kwargs["actions"]]
        return None

    with patch.object(client_instance, "invoke", side_effect=fake_invoke):
        client_instance.find_leech_cards(leech_status="active", review_scope='deck:"Core*"')
        assert queries[0] == '(deck:"Core*") tag:leech -is:suspended'

        queries.clear()
        stats = client_instance.get_deck_stats(review_scope='deck:"Core*"')
        assert '(deck:"Core*") -tag:ai-mnemonic-reviewed' in queries
        assert stats["totalNotReviewed"] == 0

        # No scope: whole collection, and no hardcoded deck names anywhere
        queries.clear()
        client_instance.find_leech_cards(leech_status="not_reviewed")
        assert queries[0] == "-tag:ai-mnemonic-reviewed"


def test_add_mining_note_missing_note_type_gives_clear_error():
    from anki_client import AnkiClient
    client_instance = AnkiClient()

    def fake_invoke(action, **kwargs):
        if action == "modelFieldNames":
            raise Exception("model was not found: Japanese sentences")
        raise AssertionError(f"should stop before {action}")

    with patch.object(client_instance, "invoke", side_effect=fake_invoke):
        with pytest.raises(ValueError, match="was not found in Anki"):
            client_instance.add_mining_note("猫", "猫[ねこ]", "cat", "", "", "")


def test_add_mining_note_maps_fields_for_other_note_types():
    from anki_client import AnkiClient
    client_instance = AnkiClient()
    calls = []

    def fake_invoke(action, **kwargs):
        calls.append((action, kwargs))
        if action == "modelFieldNames":
            return ["Front", "Back", "Sentence"]
        if action == "deckNames":
            return ["Mining"]
        if action == "addNote":
            return 1
        if action == "findCards":
            return [2]
        return None

    with patch.object(client_instance, "invoke", side_effect=fake_invoke):
        client_instance.add_mining_note(
            "猫", "猫[ねこ]", "cat", "<b>猫</b>がいる。", "", "", note_type="Basic",
            field_map={"vocabDef": "Back"},
        )
    note = next(kw["note"] for a, kw in calls if a == "addNote")
    assert note["modelName"] == "Basic"
    assert note["fields"] == {"Front": "猫", "Back": "cat", "Sentence": "<b>猫</b>がいる。"}


def test_mining_create_card_reports_setup_errors_as_400():
    with patch("app.anki.add_mining_note", side_effect=ValueError('Note type "X" was not found in Anki.')):
        res = client.post("/api/mining/create-card", json={
            "vocabKanji": "猫", "vocabFurigana": "猫[ねこ]", "vocabDef": "cat",
            "sentKanji": "", "sentFurigana": "", "sentEng": "",
        })
    assert res.status_code == 400
    assert "was not found" in res.json()["detail"]


def test_save_sentence_writes_to_the_notes_own_field_names():
    from anki_client import AnkiClient
    client_instance = AnkiClient()
    calls = []

    def fake_invoke(action, **kwargs):
        calls.append((action, kwargs))
        if action == "notesInfo":
            return [{"noteId": 5, "fields": {"Expression": {}, "Meaning": {}, "Sentence": {}, "Comment": {}}}]
        return None

    with patch.object(client_instance, "invoke", side_effect=fake_invoke):
        written = client_instance.update_note_by_role(5, {
            "sentKanji": "新しい文", "sentFurigana": "x", "sentAudio": "", "notes": "**hook**",
        })
    assert written == {"Sentence": "新しい文", "Comment": "<p><b>hook</b></p>"}
    assert ("updateNoteFields", {"note": {"id": 5, "fields": written}}) in calls


def test_rejects_requests_for_unknown_hosts():
    res = client.get("/api/config", headers={"host": "evil.example.com"})
    assert res.status_code == 400


def test_config_exposes_new_settings_with_neutral_defaults():
    data = client.get("/api/config").json()
    assert data["targetMiningDeck"] == "Mining"
    assert data["reviewScopeQuery"] == ""
    assert data["miningNoteType"] == "Japanese sentences"
    assert "AnkiDrone" not in data["leechSearchQuery"]

