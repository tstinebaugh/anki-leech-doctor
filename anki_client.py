import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from config_defaults import (
    DEFAULT_GRAMMAR_DECK_BASE,
    DEFAULT_LEECH_QUERY,
    DEFAULT_MINING_DECK,
    DEFAULT_NOTE_TYPE,
)
from utils import format_notes_for_anki

logger = logging.getLogger(__name__)

ANKI_CONNECT_URL = os.environ.get("ANKI_CONNECT_URL", "http://127.0.0.1:8765")
KANJI_REGEX = re.compile(r"[一-龯]")
JLPT_LEVELS = ("N5", "N4", "N3", "N2", "N1")
REVIEWED_TAG = "ai-mnemonic-reviewed"

# Field names tried, in order, for each role when reading or writing a note.
# Covers the "Japanese sentences" note type plus common Core / Kaishi / Basic names.
FIELD_CANDIDATES: Dict[str, List[str]] = {
    "vocabKanji": ["VocabKanji", "Expression", "Word", "Kanji", "Front"],
    "vocabFurigana": ["VocabFurigana", "Reading", "Furigana", "Word Reading"],
    "vocabDef": ["VocabDef", "Meaning", "Glossary", "English", "Word Meaning", "Back"],
    "sentKanji": ["SentKanji", "Sentence", "Example"],
    "sentFurigana": ["SentFurigana", "SentenceReading", "Sentence Furigana"],
    "sentEng": ["SentEng", "SentenceMeaning", "SentenceEng", "Sentence Meaning"],
    "sentAudio": ["SentAudio", "Sentence Audio"],
    "vocabAudio": ["VocabAudio", "Word Audio"],
    "notes": ["Notes", "Comment"],
    "pitchPattern": ["VocabPitchPattern"],
    "pitchNum": ["VocabPitchNum"],
}

STATUS_CLAUSES = {
    "active": "tag:leech -is:suspended",
    "active_leech": "tag:leech -is:suspended",
    "all": "tag:leech",
    "leech": "tag:leech",
    "all_leech": "tag:leech",
    "suspended_leech": "tag:leech is:suspended",
    "not_reviewed": f"-tag:{REVIEWED_TAG}",
    "unreviewed": f"-tag:{REVIEWED_TAG}",
    "not_reviewed_ai": f"-tag:{REVIEWED_TAG}",
}


def pick_field(fields: Dict[str, str], role: str) -> str:
    """First non-empty value among the candidate field names for a role."""
    for name in FIELD_CANDIDATES[role]:
        if fields.get(name):
            return fields[name]
    return ""


def resolve_field(model_fields: List[str], role: str, preferred: Optional[str] = None) -> Optional[str]:
    """The note type's field name for a role (case-insensitive), or None."""
    lookup = {f.lower(): f for f in model_fields}
    for name in ([preferred] if preferred else []) + FIELD_CANDIDATES.get(role, []):
        if name and name.lower() in lookup:
            return lookup[name.lower()]
    return None


def scoped_query(scope: Optional[str], clause: str) -> str:
    """Prefixes an Anki search clause with the configured review scope."""
    scope = (scope or "").strip()
    return f"({scope}) {clause}".strip() if scope else clause


def normalize_jlpt_level(level: Optional[str], default: str = "N4") -> str:
    lvl = (level or "").strip().upper()
    return lvl if lvl in JLPT_LEVELS else default


def grammar_deck_name(level: Optional[str], base: Optional[str] = None) -> str:
    """Grammar subdeck for a JLPT level, e.g. 'Mining::Grammar::N4'."""
    return f"{(base or DEFAULT_GRAMMAR_DECK_BASE).rstrip(':')}::{normalize_jlpt_level(level)}"


def is_grammar_deck(deck_name: Optional[str]) -> bool:
    return bool(deck_name) and "grammar" in deck_name.lower()


def _empty_kanji(k: str) -> Dict[str, Any]:
    return {
        "kanji": k, "found": False, "keyword": None, "myStory": None,
        "koohiiStory1": None, "koohiiStory2": None, "heisigStory": None, "heisigComment": None,
        "onYomi": None, "kunYomi": None, "constituent": None, "strokeCount": None,
        "strokeDiagram": None, "words": None,
    }


class AnkiClient:
    DEFAULT_MINING_DECK = DEFAULT_MINING_DECK

    def __init__(self, url: str = ANKI_CONNECT_URL):
        self.url = url

    def invoke(self, action: str, **params) -> Any:
        payload = json.dumps({"action": action, "version": 6, "params": params}).encode("utf-8")
        req = urllib.request.Request(self.url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if len(result) != 2:
                    raise Exception("Response has an unexpected number of fields")
                if "error" not in result:
                    raise Exception("Response is missing required error field")
                if "result" not in result:
                    raise Exception("Response is missing required result field")
                if result["error"] is not None:
                    raise Exception(result["error"])
                return result["result"]
        except urllib.error.URLError as e:
            raise ConnectionError(f"Could not connect to AnkiConnect at {self.url}. Is Anki running with the AnkiConnect add-on installed?") from e

    def is_connected(self) -> bool:
        try:
            return self.invoke("version") == 6
        except Exception:
            return False

    def get_decks(self) -> List[str]:
        return self.invoke("deckNames")

    def ensure_mining_deck(self, deck_name: Optional[str] = None) -> str:
        target_deck = deck_name or self.DEFAULT_MINING_DECK
        try:
            for d in self.get_decks():
                if d.lower() == target_deck.lower():
                    return d
            self.invoke("createDeck", deck=target_deck)
        except ConnectionError:
            raise
        except Exception as e:
            logger.warning(f"Could not verify or create deck {target_deck!r}: {e}")
        return target_deck

    def find_cards_many(self, queries: List[str]) -> List[List[int]]:
        """Runs many findCards queries in ONE AnkiConnect request via `multi`.

        AnkiConnect serves each HTTP request on Anki's main thread, so dozens of
        separate round trips cost seconds even on localhost; one batch is ~0.2s.
        """
        if not queries:
            return []
        actions = [{"action": "findCards", "version": 6, "params": {"query": q}} for q in queries]
        results = self.invoke("multi", actions=actions)
        out: List[List[int]] = []
        for q, r in zip(queries, results):
            if isinstance(r, dict):
                if r.get("error"):
                    raise Exception(f"findCards failed for {q!r}: {r['error']}")
                out.append(r.get("result") or [])
            else:
                out.append(r or [])
        return out

    def get_deck_stats(self, review_scope: Optional[str] = None, mining_deck: Optional[str] = None) -> Dict[str, Any]:
        all_decks = self.get_decks()
        per_deck_clauses = [
            ("totalCount", ""),
            ("leechCount", " tag:leech is:suspended"),
            ("suspendedCount", " is:suspended"),
            ("activeLeechCount", " tag:leech -is:suspended"),
            ("notReviewedCount", f" -tag:{REVIEWED_TAG}"),
        ]
        # Collection totals (parent decks would double-count subdecks), limited to the review scope
        global_queries = [
            ("totalLeeches", scoped_query(review_scope, "tag:leech is:suspended")),
            ("totalSuspended", scoped_query(review_scope, "is:suspended")),
            ("totalActiveLeeches", scoped_query(review_scope, "tag:leech -is:suspended")),
            ("totalAllLeeches", scoped_query(review_scope, "tag:leech")),
            ("totalNotReviewed", scoped_query(review_scope, f"-tag:{REVIEWED_TAG}")),
        ]
        queries = [f'deck:"{d}"{clause}' for d in all_decks for _, clause in per_deck_clauses]
        queries += [q for _, q in global_queries]
        results = self.find_cards_many(queries)

        mining_lower = (mining_deck or "").lower()
        deck_stats = []
        width = len(per_deck_clauses)
        for i, d in enumerate(all_decks):
            counts = {key: len(results[i * width + j]) for j, (key, _) in enumerate(per_deck_clauses)}
            if not counts["totalCount"]:
                continue
            deck_stats.append({
                "name": d,
                **counts,
                "isMiningDeck": "mining" in d.lower() or (bool(mining_lower) and d.lower() == mining_lower),
                "isGrammarDeck": is_grammar_deck(d),
            })

        offset = len(all_decks) * width
        totals = {key: len(results[offset + k]) for k, (key, _) in enumerate(global_queries)}
        return {"decks": deck_stats, **totals}

    def find_leech_cards(
        self,
        deck_query: Optional[str] = None,
        custom_query: Optional[str] = None,
        default_query: Optional[str] = None,
        mining_deck: Optional[str] = None,
        leech_status: Optional[str] = "suspended",
        search_term: Optional[str] = None,
        review_scope: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        target_mining = mining_deck or self.DEFAULT_MINING_DECK
        status_clause = STATUS_CLAUSES.get(leech_status or "", "is:suspended")

        if custom_query:
            card_ids = self.invoke("findCards", query=custom_query)
        elif search_term and search_term.strip():
            st = search_term.strip().replace('"', "")
            base = f'deck:"{deck_query}" "{st}"' if deck_query else scoped_query(review_scope, f'"{st}"')
            # Status-filtered first, then any card matching the search
            card_ids = self.invoke("findCards", query=f"{base} {status_clause}")
            if not card_ids:
                card_ids = self.invoke("findCards", query=base)
        elif deck_query:
            card_ids = self.invoke("findCards", query=f'deck:"{deck_query}" {status_clause}')
            if not card_ids and ("mining" in deck_query.lower() or is_grammar_deck(deck_query)) and leech_status not in ("suspended_leech", "active", "active_leech", "not_reviewed"):
                # Mining/grammar deck with no matches: show every card in it
                card_ids = self.invoke("findCards", query=f'deck:"{deck_query}"')
        else:
            if leech_status == "suspended_leech":
                query = scoped_query(review_scope, default_query or DEFAULT_LEECH_QUERY)
            else:
                query = scoped_query(review_scope, status_clause)
            card_ids = self.invoke("findCards", query=query)

            # Mined cards always belong in the general review list
            if target_mining:
                try:
                    for cid in self.invoke("findCards", query=f'deck:"{target_mining}" {status_clause}'):
                        if cid not in card_ids:
                            card_ids.append(cid)
                except Exception as e:
                    logger.warning(f"Could not include mining deck cards: {e}")

        if not card_ids:
            return []
        card_ids = card_ids[:1000]

        cards_info = self.invoke("cardsInfo", cards=card_ids)
        if not cards_info:
            return []

        note_tags: Dict[int, List[str]] = {}
        try:
            note_ids = list({c["note"] for c in cards_info if "note" in c})
            if note_ids:
                for n in self.invoke("notesInfo", notes=note_ids) or []:
                    if isinstance(n, dict) and "noteId" in n:
                        note_tags[n["noteId"]] = n.get("tags", [])
        except Exception as e:
            logger.warning(f"Could not fetch notesInfo for tags: {e}")

        parsed_cards = []
        for c in cards_info:
            fields = {k: v["value"] for k, v in c["fields"].items()}
            vocab_kanji = pick_field(fields, "vocabKanji").strip()
            note_id = c.get("note")
            tags = note_tags.get(note_id, [])
            parsed_cards.append({
                "cardId": c["cardId"],
                "noteId": note_id,
                "deckName": c["deckName"],
                "modelName": c.get("modelName", ""),
                "queue": c.get("queue"),
                "due": c.get("due"),
                "reps": c.get("reps"),
                "lapses": c.get("lapses"),
                "suspended": c.get("queue") == -1,
                "tags": tags,
                "isLeech": any(t.lower() == "leech" for t in tags),
                "vocabKanji": vocab_kanji,
                "vocabFurigana": pick_field(fields, "vocabFurigana"),
                "vocabDef": pick_field(fields, "vocabDef"),
                "sentKanji": pick_field(fields, "sentKanji"),
                "sentFurigana": pick_field(fields, "sentFurigana"),
                "sentEng": pick_field(fields, "sentEng"),
                "sentAudio": pick_field(fields, "sentAudio"),
                "vocabAudio": pick_field(fields, "vocabAudio"),
                "notes": pick_field(fields, "notes"),
                "kanjiChars": list(dict.fromkeys(KANJI_REGEX.findall(vocab_kanji))),
            })
        return parsed_cards

    def get_all_cards_for_indexing(
        self,
        deck_names: Optional[List[str]] = None,
        limit: int = 15000,
        exclude_suspended: bool = False,
        jlpt_level: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieves all vocabulary/sentence cards across specified decks (or all non-kanji decks)
        for RAG vector indexing. Automatically respects JLPT level deck filtering and suspension flags.
        """
        if not deck_names:
            all_decks = self.get_decks()
            # Skip single-character kanji reference decks
            filtered_decks = [d for d in all_decks if not d.lower().endswith("kanji")]

            # With a JLPT level set (e.g. N3), skip decks for higher levels you haven't reached
            if jlpt_level and jlpt_level.upper() in JLPT_LEVELS:
                order = ["n5", "n4", "n3", "n2", "n1"]
                excluded_levels = order[order.index(jlpt_level.lower()) + 1:]
                if excluded_levels:
                    filtered_decks = [
                        d for d in filtered_decks
                        if not any(f"tango {ex}" in d.lower() or f"jlpt {ex}" in d.lower() or f" {ex}" in d.lower() for ex in excluded_levels)
                    ]

            deck_names = filtered_decks if filtered_decks else all_decks

        # Uses notesInfo (fields only) instead of cardsInfo, whose reply is ~90% rendered
        # question/answer HTML and CSS: ~10x less data and memory for a full sync.
        all_parsed_cards = []
        seen_card_ids = set()

        for d in deck_names:
            try:
                base_query = f'deck:"{d}"'
                if exclude_suspended:
                    base_query += " -is:suspended"
                card_ids = (self.invoke("findCards", query=base_query) or [])[:limit]
                card_ids = [cid for cid in card_ids if cid not in seen_card_ids]
                if not card_ids:
                    continue
                wanted = set(card_ids)

                deck_of = {cid: deck for deck, cids in (self.invoke("getDecks", cards=card_ids) or {}).items() for cid in cids}
                suspended_of = dict(zip(card_ids, self.invoke("areSuspended", cards=card_ids) or []))
                note_ids = self.invoke("findNotes", query=base_query) or []

                for i in range(0, len(note_ids), 500):
                    for note in self.invoke("notesInfo", notes=note_ids[i:i + 500]) or []:
                        fields = {k: v["value"] for k, v in (note.get("fields") or {}).items()}
                        vocab_kanji = pick_field(fields, "vocabKanji").strip()
                        if not vocab_kanji:
                            continue
                        record = {
                            "noteId": note["noteId"],
                            "vocabKanji": vocab_kanji,
                            "vocabFurigana": pick_field(fields, "vocabFurigana"),
                            "vocabDef": pick_field(fields, "vocabDef"),
                            "sentKanji": pick_field(fields, "sentKanji"),
                            "sentEng": pick_field(fields, "sentEng"),
                        }
                        for cid in note.get("cards") or []:
                            if cid not in wanted or cid in seen_card_ids:
                                continue
                            seen_card_ids.add(cid)
                            all_parsed_cards.append({
                                "cardId": cid,
                                **record,
                                "deckName": deck_of.get(cid, d),
                                "suspended": bool(suspended_of.get(cid, False)),
                            })
            except Exception as e:
                logger.warning(f"Error fetching cards for deck {d}: {e}")

        return all_parsed_cards

    def get_kanji_details(self, kanji_chars: List[str], deck_name: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Looks up each kanji in your kanji story deck (or any deck named *Kanji* if none is set)."""
        kanji_data = {}
        for k in kanji_chars:
            try:
                found_cards = []
                if deck_name:
                    found_cards = self.invoke("findCards", query=f'deck:"{deck_name}" "kanji:{k}"')
                    if not found_cards:
                        found_cards = self.invoke("findCards", query=f'deck:"{deck_name}" {k}')
                if not found_cards:
                    found_cards = self.invoke("findCards", query=f'deck:*Kanji* "kanji:{k}"')

                if not found_cards:
                    kanji_data[k] = _empty_kanji(k)
                    continue

                card_info = self.invoke("cardsInfo", cards=[found_cards[0]])[0]
                f = {name: val["value"] for name, val in card_info["fields"].items()}
                entry = {
                    "kanji": k,
                    "found": True,
                    "keyword": f.get("keyword") or f.get("Keyword") or f.get("Meaning") or None,
                    "myStory": f.get("myStory") or f.get("Story") or f.get("CustomStory") or None,
                    "koohiiStory1": f.get("koohiiStory1") or f.get("Story1") or None,
                    "koohiiStory2": f.get("koohiiStory2") or f.get("Story2") or None,
                    "heisigStory": f.get("heisigStory") or f.get("HeisigStory") or None,
                    "heisigComment": f.get("heisigComment") or None,
                    "onYomi": f.get("onYomi") or f.get("Onyomi") or f.get("On") or None,
                    "kunYomi": f.get("kunYomi") or f.get("Kunyomi") or f.get("Kun") or None,
                    "constituent": f.get("constituent") or None,
                    "strokeCount": f.get("strokeCount") or None,
                    "strokeDiagram": f.get("strokeDiagram") or None,
                    "words": f.get("words") or None,
                }
                kanji_data[k] = {key: (val.strip() or None) if isinstance(val, str) else val for key, val in entry.items()}
            except Exception as e:
                logger.warning(f"Error fetching kanji info for {k}: {e}")
                kanji_data[k] = _empty_kanji(k)
        return kanji_data

    def get_model_field_names(self, note_type: str) -> List[str]:
        try:
            return self.invoke("modelFieldNames", modelName=note_type)
        except ConnectionError:
            raise
        except Exception as e:
            raise ValueError(
                f'Note type "{note_type}" was not found in Anki. Set "Mining note type" in Settings '
                f"to one of your note types (Anki: Tools → Manage Note Types)."
            ) from e

    def add_mining_note(
        self,
        vocab_kanji: str,
        vocab_furigana: str,
        vocab_def: str,
        sent_kanji: str,
        sent_furigana: str,
        sent_eng: str,
        notes: str = "",
        pitch_pattern: str = "",
        pitch_num: str = "",
        deck_name: Optional[str] = None,
        card_type: str = "vocab",
        jlpt_level: Optional[str] = None,
        grammar_deck_base: Optional[str] = None,
        note_type: Optional[str] = None,
        field_map: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        model = note_type or DEFAULT_NOTE_TYPE
        model_fields = self.get_model_field_names(model)
        field_map = field_map or {}

        tags = ["mined", REVIEWED_TAG]
        if card_type == "grammar":
            level = normalize_jlpt_level(jlpt_level)
            deck_name = grammar_deck_name(level, grammar_deck_base)
            tags += ["grammar", f"jlpt::{level}"]

        formatted_notes = format_notes_for_anki(notes.strip()) if notes else ""
        values = {
            "vocabKanji": vocab_kanji.strip(),
            "vocabFurigana": vocab_furigana.strip(),
            "vocabDef": vocab_def.strip(),
            "sentKanji": sent_kanji.strip(),
            "sentFurigana": sent_furigana.strip(),
            "sentEng": sent_eng.strip(),
            "notes": formatted_notes,
            "pitchPattern": (pitch_pattern or "").strip(),
            "pitchNum": str(pitch_num or "").strip(),
        }
        if not resolve_field(model_fields, "vocabKanji", field_map.get("vocabKanji")):
            raise ValueError(
                f'Note type "{model}" has no field for the word. Its fields are: {", ".join(model_fields)}. '
                'Add "miningFieldMap" to config.json, e.g. {"vocabKanji": "' + (model_fields[0] if model_fields else "Front") + '"}.'
            )
        fields: Dict[str, str] = {}
        for role, value in values.items():
            name = resolve_field(model_fields, role, field_map.get(role))
            if name and name not in fields:
                fields[name] = value

        deck = self.ensure_mining_deck(deck_name)
        note_id = self.invoke("addNote", note={
            "deckName": deck,
            "modelName": model,
            "fields": fields,
            "options": {"allowDuplicate": False, "duplicateScope": "deck"},
            "tags": tags,
        })
        if not note_id:
            raise RuntimeError("AnkiConnect could not add the note (it might be a duplicate or model mismatch).")

        cards_for_note = self.invoke("findCards", query=f"nid:{note_id}")
        return {
            "cardId": cards_for_note[0] if cards_for_note else 0,
            "noteId": note_id,
            "deckName": deck,
            "modelName": model,
            "queue": 0,
            "due": 0,
            "reps": 0,
            "lapses": 0,
            "suspended": False,
            **{k: values[k] for k in ("vocabKanji", "vocabFurigana", "vocabDef", "sentKanji", "sentFurigana", "sentEng")},
            "sentAudio": "",
            "vocabAudio": "",
            "notes": formatted_notes,
            "tags": tags,
            "isLeech": False,
            "kanjiChars": list(dict.fromkeys(KANJI_REGEX.findall(values["vocabKanji"]))),
        }

    def update_note_fields(self, note_id: int, fields_to_update: Dict[str, str]) -> bool:
        formatted_fields = dict(fields_to_update)
        if formatted_fields.get("Notes"):
            formatted_fields["Notes"] = format_notes_for_anki(formatted_fields["Notes"])
        self.invoke("updateNoteFields", note={"id": note_id, "fields": formatted_fields})
        return True

    def update_note_by_role(self, note_id: int, values: Dict[str, str]) -> Dict[str, str]:
        """Writes values keyed by role (vocabDef, sentKanji, notes, ...) to whichever
        fields this note's type actually has. Returns the field names written."""
        info = self.invoke("notesInfo", notes=[int(note_id)])
        model_fields = list((info[0] if info else {}).get("fields", {}).keys())
        to_update: Dict[str, str] = {}
        for role, value in values.items():
            name = resolve_field(model_fields, role)
            if name:
                to_update[name] = format_notes_for_anki(value) if role == "notes" and value else value
        if not to_update:
            raise ValueError(
                f"This card's note type has none of the fields to update ({', '.join(values)}). "
                f"Its fields are: {', '.join(model_fields) or 'unknown'}."
            )
        self.invoke("updateNoteFields", note={"id": int(note_id), "fields": to_update})
        return to_update

    def update_vocab_fields(self, note_id: int, vocab_kanji: str, vocab_furigana: str, vocab_def: str) -> bool:
        self.update_note_by_role(note_id, {
            "vocabKanji": vocab_kanji.strip(),
            "vocabFurigana": vocab_furigana.strip(),
            "vocabDef": vocab_def.strip(),
        })
        return True

    def unsuspend_and_unleech(self, card_id: int, note_id: int) -> bool:
        self.invoke("unsuspend", cards=[card_id])
        self.invoke("removeTags", notes=[note_id], tags="leech")
        self.invoke("addTags", notes=[note_id], tags=REVIEWED_TAG)
        return True

    def resuspend_and_releech(self, card_id: int, note_id: int) -> bool:
        """Reverses unsuspend_and_unleech."""
        self.invoke("suspend", cards=[card_id])
        self.invoke("addTags", notes=[note_id], tags="leech")
        self.invoke("removeTags", notes=[note_id], tags=REVIEWED_TAG)
        return True

    def toggle_suspend(self, card_id: int, suspend: bool) -> bool:
        self.invoke("suspend" if suspend else "unsuspend", cards=[card_id])
        return True

    def add_note_tags(self, note_id: int, tags: str) -> bool:
        self.invoke("addTags", notes=[note_id], tags=tags)
        return True

    def delete_note(self, note_id: int) -> bool:
        """Deletes a note and all its associated cards from Anki."""
        self.invoke("deleteNotes", notes=[int(note_id)])
        return True

    def delete_card_or_note(self, card_id: Optional[int] = None, note_id: Optional[int] = None) -> bool:
        """Deletes a card/note from Anki, resolving note ID from card ID if necessary."""
        resolved_note_id = note_id
        if not resolved_note_id and card_id:
            try:
                cards_info = self.invoke("cardsInfo", cards=[int(card_id)])
                if cards_info:
                    resolved_note_id = cards_info[0].get("note")
            except Exception as e:
                logger.warning(f"Error fetching noteId for card {card_id}: {e}")

        if not resolved_note_id:
            raise ValueError("A valid noteId or resolvable cardId is required to delete a card from Anki.")

        return self.delete_note(int(resolved_note_id))
