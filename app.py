import sys

if sys.version_info < (3, 12):
    sys.exit(
        f"Anki Leech Doctor needs Python 3.12 or newer (this is Python {sys.version.split()[0]}). "
        "See the Quickstart in README.md."
    )

import asyncio
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from anki_client import AnkiClient, JLPT_LEVELS, grammar_deck_name, normalize_jlpt_level
from config_defaults import DEFAULT_CONFIG
from gemini_client import FALLBACK_MODELS, GeminiBusyError, GeminiClient, GeminiQuotaError, usage_report
from rag_engine import MultiVectorRAG
from utils import format_notes_for_anki

logger = logging.getLogger(__name__)

def http_error(e: Exception) -> HTTPException:
    """Maps an exception to an HTTP error. Gemini being busy is 503 + Retry-After, which the
    frontend retries with a spinner; running out of quota is a final 429."""
    if isinstance(e, GeminiBusyError):
        return HTTPException(
            status_code=503,
            detail="All available Gemini models are busy right now.",
            headers={"Retry-After": str(e.retry_after)},
        )
    if isinstance(e, GeminiQuotaError):
        return HTTPException(status_code=429, detail=str(e))
    return HTTPException(status_code=500, detail=str(e))


app = FastAPI(title="Anki Leech Doctor & Mnemonic Studio")

# Only answer requests addressed to this machine. Blocks DNS-rebinding attacks, where a
# web page points its own hostname at 127.0.0.1 to reach local apps. Add hosts (comma
# separated) via LEECH_DOCTOR_ALLOWED_HOSTS if you serve the app on your LAN.
ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("LEECH_DOCTOR_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()
]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

anki = AnkiClient()
gemini = GeminiClient()
rag = MultiVectorRAG()

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# Pydantic Request Models
class MnemonicRequest(BaseModel):
    vocabKanji: str
    vocabFurigana: str
    vocabDef: str
    kanjiDetails: Dict[str, Dict[str, Any]]
    notes: Optional[str] = ""
    customInstructions: Optional[str] = ""
    mnemonicStyle: Optional[str] = None
    tone: Optional[str] = None
    confusableCards: Optional[List[Dict[str, Any]]] = None
    cardType: Optional[str] = "vocab"

class SentenceRequest(BaseModel):
    vocabKanji: str
    vocabFurigana: str
    vocabDef: str
    currentSentence: Optional[str] = ""
    personas: Optional[List[str]] = None
    customTopic: Optional[str] = ""
    jlptLevel: Optional[str] = None
    cardType: Optional[str] = "vocab"

class ChatRequest(BaseModel):
    vocabKanji: str
    vocabFurigana: str
    vocabDef: str
    kanjiDetails: Dict[str, Dict[str, Any]]
    conversationHistory: List[Dict[str, str]]
    userMessage: str
    jlptLevel: Optional[str] = None
    confusableCards: Optional[List[Dict[str, Any]]] = None

class RAGSearchRequest(BaseModel):
    vocabKanji: str
    vocabFurigana: Optional[str] = ""
    vocabDef: Optional[str] = ""
    topK: Optional[int] = 5
    excludeCardId: Optional[int] = None
    weights: Optional[Dict[str, float]] = None

class RAGSyncRequest(BaseModel):
    deckNames: Optional[List[str]] = None
    limit: Optional[int] = 15000
    excludeSuspended: Optional[bool] = False

class ConfigUpdateRequest(BaseModel):
    apiKey: Optional[str] = None
    model: Optional[str] = None
    persona: Optional[str] = None
    mnemonicTone: Optional[str] = None
    jlptLevel: Optional[str] = None
    kanjiDeckName: Optional[str] = None
    kanjiStrategy: Optional[str] = None
    mnemonicStyle: Optional[str] = None
    targetMiningDeck: Optional[str] = None
    leechSearchQuery: Optional[str] = None
    ragDecks: Optional[List[str]] = None
    ragExcludeSuspended: Optional[bool] = None
    grammarDeckBase: Optional[str] = None
    reviewScopeQuery: Optional[str] = None
    miningNoteType: Optional[str] = None
    miningFieldMap: Optional[Dict[str, str]] = None

class SaveVocabRequest(BaseModel):
    noteId: int
    vocabKanji: str
    vocabFurigana: str
    vocabDef: str

class SaveNotesRequest(BaseModel):
    noteId: int
    notes: str

class SaveSentenceRequest(BaseModel):
    noteId: int
    sentKanji: str
    sentFurigana: str
    sentEng: str

class MiningAnalyzeRequest(BaseModel):
    vocab: str
    customHint: Optional[str] = ""
    jlptLevel: Optional[str] = None
    cardType: Optional[str] = "vocab"
    personas: Optional[List[str]] = None
    # False: if the word is already in a deck, return those notes instead of analyzing
    allowDuplicate: bool = False


class BrowseNoteRequest(BaseModel):
    noteId: int

class SaveMinedCardRequest(BaseModel):
    vocabKanji: str
    vocabFurigana: str
    vocabDef: str
    sentKanji: str
    sentFurigana: str
    sentEng: str
    notes: Optional[str] = ""
    pitchPattern: Optional[str] = ""
    pitchNum: Optional[str] = ""
    deckName: Optional[str] = None
    cardType: Optional[str] = "vocab"
    jlptLevel: Optional[str] = None

class CardActionRequest(BaseModel):
    cardId: int
    noteId: int
    suspend: Optional[bool] = None

class DeleteCardRequest(BaseModel):
    cardId: Optional[int] = None
    noteId: Optional[int] = None


@app.get("/api/status")
def get_status():
    anki_online = anki.is_connected()
    has_api_key = bool(gemini.api_key)
    rag_stats = rag.get_stats()
    rag_ready = bool(rag_stats.get("indexedCount", 0) > 0)
    return {
        "ankiOnline": anki_online,
        "hasApiKey": has_api_key,
        "ragReady": rag_ready,
        "ragStats": rag_stats,
        "model": gemini.model,
        "persona": gemini.persona,
        "jlptLevel": gemini.jlpt_level,
        "kanjiDeckName": gemini.kanji_deck_name,
        "kanjiStrategy": gemini.kanji_strategy,
        "mnemonicStyle": gemini.mnemonic_style,
        "targetMiningDeck": gemini.target_mining_deck,
        "leechSearchQuery": gemini.leech_search_query,
        "reviewScopeQuery": gemini.review_scope_query
    }

@app.get("/api/models")
async def get_models():
    try:
        models = await gemini.list_available_models()
        return {"models": models, "current": gemini.model}
    except Exception:
        return {"models": [gemini.model], "current": gemini.model}

@app.get("/api/decks")
def get_decks():
    try:
        stats = anki.get_deck_stats(
            review_scope=gemini.review_scope_query,
            mining_deck=gemini.target_mining_deck
        )
        return stats
    except Exception as e:
        raise http_error(e)

@app.get("/api/cards")
def get_cards(
    deck: Optional[str] = None,
    query: Optional[str] = None,
    status: Optional[str] = "suspended",
    search: Optional[str] = None
):
    try:
        cards = anki.find_leech_cards(
            deck_query=deck,
            custom_query=query,
            default_query=gemini.leech_search_query,
            mining_deck=gemini.target_mining_deck,
            leech_status=status,
            search_term=search,
            review_scope=gemini.review_scope_query
        )
        return {"count": len(cards), "cards": cards}
    except Exception as e:
        raise http_error(e)

@app.get("/api/rag/stats")
async def get_rag_stats():
    try:
        return rag.get_stats()
    except Exception as e:
        raise http_error(e)

@app.post("/api/rag/sync")
async def sync_rag_index(req: Optional[RAGSyncRequest] = None):
    try:
        cfg = gemini.load_config()
        deck_names = req.deckNames if (req and req.deckNames) else cfg.get("ragDecks")
        exclude_suspended = req.excludeSuspended if (req and req.excludeSuspended is not None) else cfg.get("ragExcludeSuspended", False)
        jlpt_level = cfg.get("jlptLevel", "N3")
        limit = req.limit if req and req.limit else 15000
        
        cards = await asyncio.to_thread(
            anki.get_all_cards_for_indexing,
            deck_names=deck_names,
            limit=limit,
            exclude_suspended=exclude_suspended,
            jlpt_level=jlpt_level
        )
        if not cards:
            return {"indexed": 0, "totalIndexed": rag.get_stats()["indexedCount"], "message": "No cards found in Anki to index"}
        
        # Reset previous index to cleanly mirror current deck selection
        rag.reset_index()
        res = await rag.index_cards(cards)
        return res
    except Exception as e:
        logger.exception("Request failed")
        raise http_error(e)

@app.post("/api/rag/search-similar")
async def search_similar_cards(req: RAGSearchRequest):
    try:
        matches = await rag.search_similar(
            vocab_kanji=req.vocabKanji,
            vocab_furigana=req.vocabFurigana or "",
            vocab_def=req.vocabDef or "",
            top_k=req.topK or 5,
            weights=req.weights,
            exclude_card_id=req.excludeCardId
        )
        return {"count": len(matches), "matches": matches}
    except Exception as e:
        raise http_error(e)

@app.get("/api/card/{card_id}/details")
async def get_card_details(
    card_id: int,
    kanji: str = "",
    vocab_kanji: str = "",
    vocab_furigana: str = "",
    vocab_def: str = "",
    deck: Optional[str] = None
):
    try:
        kanji_list = [k.strip() for k in kanji.split(",") if k.strip()]
        
        # If strategy is purely AI on-the-fly, skip deck query
        if gemini.kanji_strategy == "ai_only":
            kanji_details = {
                k: {
                    "kanji": k,
                    "found": False,
                    "keyword": None,
                    "myStory": None
                }
                for k in kanji_list
            }
        else:
            target_deck = deck or gemini.kanji_deck_name
            kanji_details = await asyncio.to_thread(anki.get_kanji_details, kanji_list, deck_name=target_deck)

        # Retrieve confusable cards from RAG vector index
        confusable_cards = []
        if vocab_kanji:
            try:
                confusable_cards = await rag.search_similar(
                    vocab_kanji=vocab_kanji,
                    vocab_furigana=vocab_furigana,
                    vocab_def=vocab_def,
                    top_k=4,
                    exclude_card_id=card_id
                )
            except Exception as e:
                logger.warning(f"RAG search error for card {card_id}: {e}")

        return {
            "cardId": card_id,
            "kanjiDetails": kanji_details,
            "confusableCards": confusable_cards
        }
    except Exception as e:
        raise http_error(e)

@app.post("/api/anki/browse")
def browse_note(req: BrowseNoteRequest):
    """Opens Anki's card browser on a note (e.g. an existing card found while mining)."""
    try:
        anki.open_in_browser(req.noteId)
        return {"success": True}
    except Exception as e:
        raise http_error(e)


@app.get("/api/gemini/usage")
def gemini_usage():
    """Today's Gemini requests per model (quota day = since midnight Pacific), from the
    call log, with each model's learned daily limit and current cooldown."""
    try:
        models = [gemini.model] + [m for m in FALLBACK_MODELS if m != gemini.model]
        return usage_report(models)
    except Exception as e:
        logger.exception("Request failed")
        raise http_error(e)


@app.post("/api/generate-mnemonic")
async def generate_mnemonic(req: MnemonicRequest):
    try:
        confusables = req.confusableCards
        if confusables is None:
            try:
                confusables = await rag.search_similar(
                    vocab_kanji=req.vocabKanji,
                    vocab_furigana=req.vocabFurigana,
                    vocab_def=req.vocabDef,
                    top_k=3
                )
            except Exception:
                confusables = []

        res = await gemini.generate_mnemonic(
            vocab_kanji=req.vocabKanji,
            vocab_furigana=req.vocabFurigana,
            vocab_def=req.vocabDef,
            kanji_details=req.kanjiDetails,
            notes=req.notes or "",
            custom_instructions=req.customInstructions or "",
            mnemonic_style=req.mnemonicStyle,
            tone=req.tone,
            confusable_cards=confusables,
            card_type=req.cardType or "vocab"
        )
        return res
    except Exception as e:
        logger.exception("Request failed")
        raise http_error(e)

@app.post("/api/generate-sentence")
async def generate_sentence(req: SentenceRequest):
    try:
        res = await gemini.generate_personalized_sentence(
            vocab_kanji=req.vocabKanji,
            vocab_furigana=req.vocabFurigana,
            vocab_def=req.vocabDef,
            current_sentence=req.currentSentence or "",
            personas=req.personas,
            custom_topic=req.customTopic or "",
            jlpt_level=req.jlptLevel,
            card_type=req.cardType or "vocab"
        )
        return res
    except Exception as e:
        logger.exception("Request failed")
        raise http_error(e)

@app.post("/api/chat")
async def chat_tutor(req: ChatRequest):
    try:
        confusables = req.confusableCards
        if confusables is None:
            try:
                confusables = await rag.search_similar(
                    vocab_kanji=req.vocabKanji,
                    vocab_furigana=req.vocabFurigana,
                    vocab_def=req.vocabDef,
                    top_k=3
                )
            except Exception:
                confusables = []

        reply = await gemini.chat_tutor(
            vocab_kanji=req.vocabKanji,
            vocab_furigana=req.vocabFurigana,
            vocab_def=req.vocabDef,
            kanji_details=req.kanjiDetails,
            conversation_history=req.conversationHistory,
            user_message=req.userMessage,
            jlpt_level=req.jlptLevel,
            confusable_cards=confusables
        )
        return {"reply": reply}
    except Exception as e:
        raise http_error(e)

@app.post("/api/sync/save-notes")
async def save_notes(req: SaveNotesRequest):
    try:
        formatted = format_notes_for_anki(req.notes)
        await asyncio.to_thread(anki.update_note_by_role, req.noteId, {"notes": formatted})
        return {"success": True, "notes": formatted, "message": "Card notes updated in Anki"}
    except Exception as e:
        raise http_error(e)

@app.post("/api/sync/save-vocab")
async def save_vocab(req: SaveVocabRequest):
    try:
        await asyncio.to_thread(
            anki.update_vocab_fields,
            note_id=req.noteId,
            vocab_kanji=req.vocabKanji,
            vocab_furigana=req.vocabFurigana,
            vocab_def=req.vocabDef
        )
        # Re-index card into RAG if possible
        try:
            cards_for_note = await asyncio.to_thread(anki.invoke, "findCards", query=f"nid:{req.noteId}")
            if cards_for_note:
                cid = cards_for_note[0]
                await rag.index_cards([{
                    "cardId": cid,
                    "noteId": req.noteId,
                    "vocabKanji": req.vocabKanji,
                    "vocabFurigana": req.vocabFurigana,
                    "vocabDef": req.vocabDef
                }])
        except Exception as e:
            logger.warning(f"Error updating RAG on vocab save: {e}")

        return {"success": True, "message": "Vocabulary definition updated in Anki"}
    except Exception as e:
        raise http_error(e)

@app.post("/api/sync/save-sentence")
async def save_sentence(req: SaveSentenceRequest):
    try:
        await asyncio.to_thread(anki.update_note_by_role, req.noteId, {
            "sentKanji": req.sentKanji,
            "sentFurigana": req.sentFurigana,
            "sentEng": req.sentEng,
            "sentAudio": ""
        })
        return {"success": True, "message": "Example sentence updated and SentAudio cleared in Anki"}
    except Exception as e:
        raise http_error(e)

@app.post("/api/sync/unsuspend")
def unsuspend_card(req: CardActionRequest):
    try:
        anki.unsuspend_and_unleech(req.cardId, req.noteId)
        return {"success": True, "message": "Card unsuspended and leech tag removed"}
    except Exception as e:
        raise http_error(e)

@app.post("/api/sync/undo-unsuspend")
def undo_unsuspend_card(req: CardActionRequest):
    try:
        anki.resuspend_and_releech(req.cardId, req.noteId)
        return {"success": True, "message": "Card re-suspended and leech tag restored"}
    except Exception as e:
        raise http_error(e)

@app.post("/api/sync/toggle-suspend")
def toggle_suspend(req: CardActionRequest):
    try:
        anki.toggle_suspend(req.cardId, bool(req.suspend))
        return {"success": True, "suspended": req.suspend}
    except Exception as e:
        raise http_error(e)

@app.post("/api/card/delete")
def delete_card_endpoint(req: DeleteCardRequest):
    if not req.cardId and not req.noteId:
        raise HTTPException(status_code=400, detail="Either cardId or noteId must be provided")
    try:
        anki.delete_card_or_note(card_id=req.cardId, note_id=req.noteId)
        if req.cardId:
            try:
                rag.delete_card(req.cardId)
            except Exception as e:
                logger.warning(f"Error removing card {req.cardId} from RAG: {e}")
        return {"success": True, "message": "Card permanently deleted from Anki"}
    except Exception as e:
        logger.exception("Request failed")
        raise http_error(e)

@app.post("/api/mining/analyze")
async def analyze_mining_vocab(req: MiningAnalyzeRequest):
    if not req.vocab or not req.vocab.strip():
        raise HTTPException(status_code=400, detail="Vocabulary input cannot be empty")
    is_grammar = req.cardType == "grammar"
    # Grammar level: "auto" (or anything that isn't N5-N1) lets the AI place the
    # pattern; an explicit level is an override that decides the deck.
    requested_level = (req.jlptLevel or "").strip().upper()
    manual_grammar_level = requested_level if is_grammar and requested_level in JLPT_LEVELS else None
    if not req.allowDuplicate:
        # Checked before any Gemini request, so a word you already have costs no quota
        try:
            field_map = gemini.config.get("miningFieldMap") or {}
            existing = await asyncio.to_thread(
                anki.find_existing_notes, req.vocab.strip(), [field_map.get("vocabKanji")], grammar_only=is_grammar
            )
        except Exception as e:
            logger.warning(f"Duplicate check skipped: {e}")
            existing = []
        if existing:
            return {"duplicate": True, "query": req.vocab.strip(), "matches": existing}
    try:
        if is_grammar:
            analysis = await gemini.analyze_grammar(
                req.vocab.strip(),
                req.customHint or "",
                jlpt_level=manual_grammar_level
            )
        else:
            analysis = await gemini.analyze_vocab(
                req.vocab.strip(),
                req.customHint or "",
                jlpt_level=req.jlptLevel
            )
        vocab_kanji = analysis.get("vocabKanji", req.vocab.strip())
        vocab_furigana = analysis.get("vocabFurigana", vocab_kanji)
        vocab_def = analysis.get("vocabDef", "")
        
        kanji_chars = list(dict.fromkeys(re.findall(r"[\u4e00-\u9faf]", vocab_kanji)))

        if is_grammar:
            # Grammar points get no kanji breakdown panel
            kanji_chars = []
            kanji_details = {}
        elif gemini.kanji_strategy == "ai_only":
            kanji_details = {k: {"kanji": k, "found": False, "keyword": None} for k in kanji_chars}
        else:
            kanji_details = await asyncio.to_thread(anki.get_kanji_details, kanji_chars, deck_name=gemini.kanji_deck_name)
        
        target_mining = gemini.target_mining_deck
        grammar_level = None
        if is_grammar:
            grammar_level = manual_grammar_level or normalize_jlpt_level(analysis.get("jlptLevel"))
            target_mining = grammar_deck_name(grammar_level, gemini.load_config().get("grammarDeckBase"))

        # Multi-Vector collision and duplicate check via RAG
        async def _collision_check():
            try:
                return await rag.search_similar(
                    vocab_kanji=vocab_kanji,
                    vocab_furigana=vocab_furigana,
                    vocab_def=vocab_def,
                    top_k=5
                )
            except Exception as e:
                logger.warning(f"RAG collision check error during mining: {e}")
                return []

        # Example sentence comes from the same persona generator as the
        # Persona Sentences tab, so mined cards match the rest of the deck.
        async def _persona_sentence():
            try:
                res = await gemini.generate_personalized_sentence(
                    vocab_kanji=vocab_kanji,
                    vocab_furigana=vocab_furigana,
                    vocab_def=vocab_def,
                    current_sentence=analysis.get("sentKanji", ""),
                    personas=req.personas,
                    jlpt_level=grammar_level or req.jlptLevel,
                    card_type="grammar" if is_grammar else "vocab"
                )
                if not res or res.get("fallback") or not (res.get("sentKanji") or "").strip():
                    return None
                return res
            except Exception as e:
                logger.warning(f"Persona sentence generation failed during mining, using analysis sentence: {e}")
                return None

        collision_matches, persona_sentence = await asyncio.gather(_collision_check(), _persona_sentence())
        sentence_src = persona_sentence or analysis
        draft_card = {
            "cardId": -1,  # Draft card indicator
            "noteId": -1,
            "deckName": target_mining,
            "modelName": gemini.mining_note_type,
            "queue": 0,
            "due": 0,
            "reps": 0,
            "lapses": 0,
            "suspended": False,
            "isDraft": True,
            "vocabKanji": vocab_kanji,
            "vocabFurigana": vocab_furigana,
            "vocabDef": vocab_def,
            "sentKanji": sentence_src.get("sentKanji", ""),
            "sentFurigana": sentence_src.get("sentFurigana", ""),
            "sentEng": sentence_src.get("sentEng", ""),
            "sentenceSource": "persona" if persona_sentence else "analysis",
            "personaSentence": {
                "themeUsed": persona_sentence.get("themeUsed", ""),
                "rationale": persona_sentence.get("rationale", ""),
            } if persona_sentence else None,
            "sentAudio": "",
            "vocabAudio": "",
            "pitchPattern": analysis.get("pitchPattern", ""),
            "pitchNum": analysis.get("pitchNum", ""),
            "notes": analysis.get("notes", "") if is_grammar else "",
            "kanjiChars": kanji_chars,
            "kanjiDetails": kanji_details,
            "collisionMatches": collision_matches,
            "cardType": "grammar" if is_grammar else "vocab",
            "jlptLevel": grammar_level,
            "tags": ["grammar", f"jlpt::{grammar_level}"] if is_grammar else []
        }
        return draft_card
    except Exception as e:
        logger.exception("Request failed")
        raise http_error(e)

def _ensure_rag_deck(deck_name: str) -> None:
    """Adds a newly used grammar deck to config.ragDecks so collision checks see it."""
    try:
        rag_decks = gemini.load_config().get("ragDecks")
        if isinstance(rag_decks, list) and deck_name not in rag_decks:
            gemini.save_config({"ragDecks": rag_decks + [deck_name]})
    except Exception as e:
        logger.warning(f"Could not add {deck_name} to ragDecks: {e}")

@app.post("/api/mining/create-card")
async def create_mined_card(req: SaveMinedCardRequest):
    try:
        cfg = gemini.load_config()
        created_card = await asyncio.to_thread(
            anki.add_mining_note,
            vocab_kanji=req.vocabKanji,
            vocab_furigana=req.vocabFurigana,
            vocab_def=req.vocabDef,
            sent_kanji=req.sentKanji,
            sent_furigana=req.sentFurigana,
            sent_eng=req.sentEng,
            notes=req.notes or "",
            pitch_pattern=req.pitchPattern or "",
            pitch_num=req.pitchNum or "",
            deck_name=req.deckName or gemini.target_mining_deck,
            card_type=req.cardType or "vocab",
            jlpt_level=req.jlptLevel,
            grammar_deck_base=cfg.get("grammarDeckBase"),
            note_type=cfg.get("miningNoteType"),
            field_map=cfg.get("miningFieldMap") or None
        )
        if req.cardType == "grammar":
            _ensure_rag_deck(created_card["deckName"])
    except ValueError as e:
        # Setup problem the user can fix (note type missing, fields don't match)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Adding mined card failed")
        raise http_error(e)
    # Index the new card so the collision radar sees it right away
    try:
        await rag.index_cards([{
            "cardId": created_card.get("cardId") or created_card.get("noteId", int(time.time())),
            "noteId": created_card.get("noteId", int(time.time())),
            "deckName": created_card.get("deckName", gemini.target_mining_deck),
            "vocabKanji": req.vocabKanji,
            "vocabFurigana": req.vocabFurigana,
            "vocabDef": req.vocabDef,
            "sentKanji": req.sentKanji,
            "sentFurigana": req.sentFurigana,
            "sentEng": req.sentEng,
            "notes": created_card.get("notes", ""),
            "suspended": False,
            "lapses": 0
        }])
    except Exception as e:
        logger.warning(f"Error auto-indexing mined card: {e}")

    return {"success": True, "card": created_card, "message": f"Added to {created_card['deckName']}"}

@app.get("/api/config")
async def get_config():
    cfg = gemini.load_config()
    key = cfg.get("apiKey", "")
    masked_key = (key[:6] + "..." + key[-4:]) if len(key) > 10 else ("***" if key else "")
    rag_stats = rag.get_stats()
    return {
        "hasKey": bool(key),
        "maskedKey": masked_key,
        **{k: cfg.get(k, DEFAULT_CONFIG.get(k)) for k in (
            "model", "persona", "mnemonicTone", "jlptLevel", "kanjiDeckName", "kanjiStrategy",
            "mnemonicStyle", "targetMiningDeck", "leechSearchQuery", "grammarDeckBase",
            "reviewScopeQuery", "miningNoteType", "miningFieldMap",
        )},
        "ragDecks": cfg.get("ragDecks"),
        "ragExcludeSuspended": cfg.get("ragExcludeSuspended", False),
        "ragStats": rag_stats
    }

@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
    updates = {}
    if getattr(req, "apiKey", None) is not None and req.apiKey.strip():
        updates["apiKey"] = req.apiKey.strip()
    if getattr(req, "model", None) is not None:
        updates["model"] = req.model
    if getattr(req, "persona", None) is not None:
        updates["persona"] = req.persona
    if getattr(req, "mnemonicTone", None) is not None:
        updates["mnemonicTone"] = req.mnemonicTone
    if getattr(req, "jlptLevel", None) is not None:
        updates["jlptLevel"] = req.jlptLevel
    if getattr(req, "kanjiDeckName", None) is not None:
        updates["kanjiDeckName"] = req.kanjiDeckName
    if getattr(req, "kanjiStrategy", None) is not None:
        updates["kanjiStrategy"] = req.kanjiStrategy
    if getattr(req, "mnemonicStyle", None) is not None:
        updates["mnemonicStyle"] = req.mnemonicStyle
    if getattr(req, "targetMiningDeck", None) is not None:
        updates["targetMiningDeck"] = req.targetMiningDeck
    if getattr(req, "leechSearchQuery", None) is not None:
        updates["leechSearchQuery"] = req.leechSearchQuery
    if getattr(req, "grammarDeckBase", None) is not None and req.grammarDeckBase.strip():
        updates["grammarDeckBase"] = req.grammarDeckBase.strip()
    if req.reviewScopeQuery is not None:
        updates["reviewScopeQuery"] = req.reviewScopeQuery.strip()
    if req.miningNoteType is not None and req.miningNoteType.strip():
        updates["miningNoteType"] = req.miningNoteType.strip()
    if req.miningFieldMap is not None:
        updates["miningFieldMap"] = req.miningFieldMap
    if getattr(req, "ragDecks", None) is not None:
        updates["ragDecks"] = req.ragDecks
    if getattr(req, "ragExcludeSuspended", None) is not None:
        updates["ragExcludeSuspended"] = req.ragExcludeSuspended
    
    gemini.save_config(updates)
    return {"success": True, "config": await get_config()}

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    ico_path = os.path.join(STATIC_DIR, "favicon.ico")
    if os.path.exists(ico_path):
        return FileResponse(ico_path, media_type="image/x-icon")
    return FileResponse(os.path.join(STATIC_DIR, "favicon.svg"), media_type="image/svg+xml")

@app.get("/favicon.svg", include_in_schema=False)
async def favicon_svg():
    return FileResponse(os.path.join(STATIC_DIR, "favicon.svg"), media_type="image/svg+xml")

@app.get("/")
async def index():
    return FileResponse(
        os.path.join(STATIC_DIR, "index.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8766)
