import os
import json
import re
import time
import logging
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from config_defaults import CONFIG_PATH as DEFAULT_CONFIG_PATH, DEFAULT_CONFIG, MODEL_HEALTH_PATH
from furigana import clean_sentence_pair, kanji_without_reading, normalize_furigana

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# ---- Gemini call reliability -----------------------------------------------------------
# Popular Gemini models are often overloaded: Google can hold a request for 15-60s and
# then answer 503. Each attempt therefore gets a short timeout, a call has a total time
# budget, and a model that just failed is skipped for a while (see ModelHealth).

# Tried in this order after the configured model. The preview and lite models were the
# ones still answering in 1-3s while the stable Flash models were overloaded.
FALLBACK_MODELS = ["gemini-3-flash-preview", "gemini-flash-lite-latest", "gemini-flash-latest"]
ATTEMPT_TIMEOUT = 25.0     # seconds to wait for one model; healthy replies take 1-10s
CONNECT_TIMEOUT = 10.0
TOTAL_TIME_BUDGET = 60.0   # seconds for one call across all models
COOLDOWN_BASE = 60.0       # first failure; doubles on each consecutive failure
COOLDOWN_MAX = 600.0
COOLDOWN_NOT_FOUND = 3600.0
COOLDOWN_QUOTA_MAX = 26 * 3600.0  # a daily quota resets within a day; ignore anything longer
QUOTA_RESET_TZ = "America/Los_Angeles"  # Gemini's daily quotas reset at midnight Pacific


class ModelHealth:
    """Remembers which models recently failed so later calls avoid them.

    Two kinds of cooldown:
    - soft (overloaded, timed out, 5xx): skipped while a healthier model is available,
      still tried as a last resort; 60s, doubling per consecutive failure up to 10 min;
    - hard (quota used up, model not found): not tried at all until it ends. For a 429
      that is when Google says the quota resets, e.g. midnight Pacific for daily quotas.

    Cooldowns use wall-clock time and are saved to a small JSON file, so restarting the
    server doesn't forget that today's quota is gone.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path
        self._until: Dict[str, float] = {}
        self._hard: set = set()
        self._reason: Dict[str, str] = {}
        self._strikes: Dict[str, int] = {}
        self.no_thinking: set = set()  # models that rejected our thinkingConfig
        self._load()

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            now = time.time()
            for model, entry in saved.items():
                if float(entry["until"]) > now:
                    self._until[model] = float(entry["until"])
                    self._reason[model] = str(entry.get("reason", ""))
                    if entry.get("hard"):
                        self._hard.add(model)
        except Exception as e:
            logger.warning(f"Ignoring unreadable model cooldown file {self.path}: {e}")

    def _save(self) -> None:
        if not self.path:
            return
        now = time.time()
        data = {
            m: {"until": t, "hard": m in self._hard, "reason": self._reason.get(m, "")}
            for m, t in self._until.items() if t > now
        }
        try:
            directory = os.path.dirname(self.path) or "."
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".model_health-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1)
            os.replace(tmp, self.path)
        except OSError as e:
            logger.warning(f"Could not save model cooldowns to {self.path}: {e}")

    def cooldown_left(self, model: str) -> float:
        return max(0.0, self._until.get(model, 0.0) - time.time())

    def available_at(self, model: str) -> float:
        return self._until.get(model, 0.0)

    def is_blocked(self, model: str) -> bool:
        return model in self._hard and self.cooldown_left(model) > 0

    def reason(self, model: str) -> str:
        return self._reason.get(model, "")

    def failed(self, model: str, retry_after: Optional[float] = None, hard: bool = False, reason: str = "") -> None:
        strikes = self._strikes.get(model, 0) + 1
        self._strikes[model] = strikes
        if retry_after:
            seconds = min(max(retry_after, 5.0), COOLDOWN_QUOTA_MAX)
        elif hard:
            seconds = COOLDOWN_NOT_FOUND
        else:
            seconds = min(COOLDOWN_BASE * 2 ** (strikes - 1), COOLDOWN_MAX)
        self._until[model] = time.time() + seconds
        self._reason[model] = reason
        if hard:
            self._hard.add(model)
        else:
            self._hard.discard(model)
        self._save()

    def succeeded(self, model: str) -> None:
        self._strikes.pop(model, None)
        if self._until.pop(model, None) is not None:
            self._hard.discard(model)
            self._reason.pop(model, None)
            self._save()

    def order(self, models: List[str]) -> Tuple[List[str], List[str]]:
        """(models to try, models blocked until their cooldown ends).

        Healthy models come first in their given order, then soft-cooling ones,
        soonest-recovering first."""
        seen: List[str] = []
        for m in models:
            if m not in seen:
                seen.append(m)
        blocked = [m for m in seen if self.is_blocked(m)]
        rest = [m for m in seen if m not in blocked]
        healthy = [m for m in rest if not self.cooldown_left(m)]
        cooling = sorted((m for m in rest if self.cooldown_left(m)), key=self.cooldown_left)
        return healthy + cooling, blocked

    def reset(self) -> None:
        self._until.clear()
        self._hard.clear()
        self._reason.clear()
        self._strikes.clear()
        self.no_thinking.clear()
        if self.path and os.path.exists(self.path):
            os.remove(self.path)


def seconds_until_quota_reset(now: Optional[float] = None) -> float:
    """Seconds until the next midnight Pacific, when Gemini's daily quotas reset."""
    try:
        tz = ZoneInfo(QUOTA_RESET_TZ)
    except Exception:
        return COOLDOWN_NOT_FOUND
    current = datetime.fromtimestamp(now if now is not None else time.time(), tz)
    midnight = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60.0, (midnight - current).total_seconds())


def describe_until(timestamp: float) -> str:
    """'until 17:00 (in 22h 10m)' in local time, for logs and error messages."""
    left = max(0, int(timestamp - time.time()))
    at = datetime.fromtimestamp(timestamp)
    day = "" if at.date() == datetime.now().date() else f" {at:%a}"
    span = f"{left // 3600}h {left % 3600 // 60}m" if left >= 3600 else f"{left // 60}m {left % 60}s"
    return f"until{day} {at:%H:%M} (in {span})"


model_health = ModelHealth(MODEL_HEALTH_PATH)


def thinking_config_for(model: str, level: str) -> Optional[Dict[str, Any]]:
    """Gemini 3+ takes a thinkingLevel cap; 2.5 takes a token budget (0 turns it off on Flash)."""
    name = model.lower()
    if "gemma" in name:
        return None
    if "2.5" in name or "2-5" in name:
        return None if "pro" in name else {"thinkingBudget": 0}
    return {"thinkingLevel": level}


def _extract_text(data: Dict[str, Any]) -> Tuple[str, str]:
    """Returns (text, problem); text is empty when the reply had no usable answer."""
    candidates = data.get("candidates", [])
    if not candidates:
        reason = (data.get("promptFeedback") or {}).get("blockReason")
        return "", f"No candidates returned in response{f' (blocked: {reason})' if reason else ''}"
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if p.get("text") and not p.get("thought"))
    if text.strip():
        return text, ""
    if candidates[0].get("finishReason") == "MAX_TOKENS":
        return "", "Reply was cut off: thinking used up the output token limit"
    return "", "Empty text parts returned"


def _parse_error(resp: httpx.Response) -> Tuple[str, Optional[float], bool]:
    """(message, seconds until Google says to retry, whether a daily quota ran out)."""
    try:
        err = resp.json().get("error", {})
    except Exception:
        return resp.text, None, False
    retry_after = None
    daily = False
    for detail in err.get("details", []) or []:
        delay = str(detail.get("retryDelay", ""))
        if delay.endswith("s"):
            try:
                retry_after = float(delay[:-1])
            except ValueError:
                pass
        for violation in detail.get("violations", []) or []:
            quota = f"{violation.get('quotaId', '')} {violation.get('description', '')}".lower()
            if "perday" in quota or "per day" in quota:
                daily = True
    return err.get("message", resp.text), retry_after, daily


KANJI_CHARS = r"\u4e00-\u9faf々〆ヶ"

def _strip_json_fences(raw: str) -> str:
    """Removes ```json fences a model sometimes wraps around a JSON reply."""
    clean = (raw or "").strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1]
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
    return clean.strip()


def keep_target_bold(sent_furigana: str, target: str) -> str:
    """Removes <b> from spans that don't contain the target word, when at least one does.

    Models sometimes bold extra words ('<b>猫</b>が<b>王様</b>のように<b>振る舞う</b>').
    """
    kanji = re.findall(rf"[{KANJI_CHARS}]", target)

    def has_target(span: str) -> bool:
        plain = re.sub(r"\[[^\]]*\]|\s", "", span)
        return any(k in plain for k in kanji) if kanji else target.strip("〜～ ") in plain

    spans = re.findall(r"<b>(.*?)</b>", sent_furigana)
    if len(spans) < 2 or not any(has_target(sp) for sp in spans):
        return sent_furigana
    return re.sub(r"<b>(.*?)</b>", lambda m: m.group(0) if has_target(m.group(1)) else m.group(1), sent_furigana)


def validate_persona_sentence(parsed: Dict[str, Any], vocab_kanji: str, is_grammar: bool = False) -> Tuple[bool, List[str]]:
    """
    Validates formatting of generated persona sentence:
    1. Target word bold tags in both sent_kanji and sent_furigana.
    2. sent_kanji must NOT contain any furigana, bracket readings [...], or ruby tags.
    3. sent_furigana must contain bracket furigana [reading] on every kanji word.

    For grammar points (is_grammar=True) the bolded span is a conjugated chunk
    (e.g. <b>食べたばかり</b> for 〜ばかり), so only the presence of bold tags is required.
    """
    errors = []
    if not isinstance(parsed, dict):
        return False, ["Response is not a valid JSON object."]

    sent_kanji = str(parsed.get("sent_kanji", "")).strip()
    sent_furigana = str(parsed.get("sent_furigana", "")).strip()

    if not sent_kanji:
        errors.append("sent_kanji is empty.")
    if not sent_furigana:
        errors.append("sent_furigana is empty.")

    if not sent_kanji or not sent_furigana:
        return False, errors

    kanji_in_target = re.findall(rf"[{KANJI_CHARS}]", vocab_kanji)

    # Check 1: Target word bold tags in sent_kanji
    bold_kanji_matches = re.findall(r"<b>(.*?)</b>", sent_kanji)
    if not bold_kanji_matches:
        errors.append("Target word is missing <b>...</b> bold tags in sent_kanji.")
    elif not is_grammar:
        bold_text = "".join(bold_kanji_matches)
        if kanji_in_target:
            if not any(k in bold_text for k in kanji_in_target):
                errors.append(f"Bold tag in sent_kanji ('{bold_text}') does not contain target kanji '{vocab_kanji}'.")
        else:
            if vocab_kanji not in bold_text:
                errors.append(f"Bold tag in sent_kanji ('{bold_text}') does not contain target word '{vocab_kanji}'.")

    # Check 2: Target word bold tags in sent_furigana
    bold_furi_matches = re.findall(r"<b>(.*?)</b>", sent_furigana)
    if not bold_furi_matches:
        errors.append("Target word is missing <b>...</b> bold tags in sent_furigana.")
    elif not is_grammar:
        bold_furi_text = "".join(bold_furi_matches)
        if kanji_in_target:
            if not any(k in bold_furi_text for k in kanji_in_target):
                errors.append(f"Bold tag in sent_furigana ('{bold_furi_text}') does not contain target kanji '{vocab_kanji}'.")
        else:
            clean_bold_furi = re.sub(r"\[[^\]]+\]", "", bold_furi_text)
            if vocab_kanji not in clean_bold_furi:
                errors.append(f"Bold tag in sent_furigana does not contain target word '{vocab_kanji}'.")

    # Check 3: sent_kanji must NOT contain any furigana
    if re.search(r"\[[^\]]+\]", sent_kanji):
        errors.append("sent_kanji contains bracket furigana '[...]'. It must be clean text without furigana.")
    if re.search(r"</?(?:ruby|rt)>", sent_kanji, re.IGNORECASE):
        errors.append("sent_kanji contains ruby tags. It must be clean text without furigana.")
    if re.search(rf"[{KANJI_CHARS}]+[（(][\u3040-\u309F\u30A0-\u30FF]+[）)]", sent_kanji):
        errors.append("sent_kanji contains parenthetical kana reading. It must be clean text without furigana.")

    # Check 4: In sent_furigana, every kanji word must have bracket furigana
    # (checked on the normalized text with Anki's own block rule, so 振る舞[ふるま]う passes)
    missing = kanji_without_reading(sent_furigana)
    if missing:
        errors.append(
            f"In sent_furigana, the following kanji are missing bracket furigana [reading]: '{missing}'. "
            "Every single kanji word must have [reading] so Anki displays readings above the kanji."
        )

    is_valid = len(errors) == 0
    return is_valid, errors

class GeminiClient:
    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        merged = dict(DEFAULT_CONFIG)
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
                    merged.update(user_cfg)
            except Exception:
                pass
        return merged

    def save_config(self, new_config: Dict[str, Any]) -> None:
        # Write only what the user set, so defaults can still change in later versions
        user_cfg: Dict[str, Any] = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
            except Exception:
                user_cfg = {}
        user_cfg.update(new_config)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(user_cfg, f, indent=2, ensure_ascii=False)
        self.config = self.load_config()

    @property
    def api_key(self) -> str:
        return self.config.get("apiKey") or os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))

    @property
    def model(self) -> str:
        return self.config.get("model", DEFAULT_CONFIG["model"])

    @property
    def persona(self) -> str:
        return self.config.get("persona", DEFAULT_CONFIG["persona"])

    @property
    def jlpt_level(self) -> str:
        return self.config.get("jlptLevel", DEFAULT_CONFIG["jlptLevel"])

    @property
    def kanji_deck_name(self) -> str:
        return self.config.get("kanjiDeckName", DEFAULT_CONFIG["kanjiDeckName"])

    @property
    def kanji_strategy(self) -> str:
        return self.config.get("kanjiStrategy", DEFAULT_CONFIG["kanjiStrategy"])

    @property
    def mnemonic_style(self) -> str:
        return self.config.get("mnemonicStyle", DEFAULT_CONFIG["mnemonicStyle"])

    @property
    def mnemonic_tone(self) -> str:
        return self.config.get("mnemonicTone", DEFAULT_CONFIG["mnemonicTone"])

    @property
    def target_mining_deck(self) -> str:
        return self.config.get("targetMiningDeck", DEFAULT_CONFIG["targetMiningDeck"])

    @property
    def leech_search_query(self) -> str:
        return self.config.get("leechSearchQuery", DEFAULT_CONFIG["leechSearchQuery"])

    @property
    def review_scope_query(self) -> str:
        return self.config.get("reviewScopeQuery", DEFAULT_CONFIG["reviewScopeQuery"])

    @property
    def mining_note_type(self) -> str:
        return self.config.get("miningNoteType") or DEFAULT_CONFIG["miningNoteType"]

    def _auth_headers(self) -> Dict[str, str]:
        # Header instead of ?key= so the key never lands in URLs, logs or tracebacks
        return {"x-goog-api-key": self.api_key}

    async def list_available_models(self) -> List[str]:
        default_fallback = [
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-3-flash-preview",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
        ]
        if not self.api_key:
            return default_fallback
        url = f"{GEMINI_API_BASE}/models"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=self._auth_headers())
                if resp.status_code == 200:
                    data = resp.json()
                    models = [
                        m["name"].replace("models/", "")
                        for m in data.get("models", [])
                        if "generateContent" in m.get("supportedGenerationMethods", [])
                        and ("flash" in m["name"] or "pro" in m["name"])
                    ]
                    # Sort prioritizing flash-latest, flash-lite-latest, 3-flash-preview, 3.7, 3.6, 3.5
                    priority = [
                        "gemini-flash-latest",
                        "gemini-flash-lite-latest",
                        "gemini-3-flash-preview",
                        "gemini-3.7-flash",
                        "gemini-3.6-flash",
                        "gemini-3.5-flash",
                        "gemini-pro-latest"
                    ]
                    sorted_models = [m for m in priority if m in models] + [m for m in sorted(models) if m not in priority]
                    return sorted_models if sorted_models else default_fallback
        except Exception as e:
            logger.warning(f"Failed to fetch dynamic models list: {e}")
        return default_fallback

    async def _call_gemini(self, contents: List[Dict[str, Any]], system_instruction: Optional[str] = None) -> str:
        if not self.api_key:
            raise ValueError("Gemini API key is not configured. Please set your API key in the UI settings or config.json.")

        candidates_in_order = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        models_to_try, blocked = model_health.order(candidates_in_order)
        level = self.config.get("thinkingLevel") or DEFAULT_CONFIG["thinkingLevel"]
        deadline = time.monotonic() + TOTAL_TIME_BUDGET

        errors_by_model: Dict[str, str] = {
            m: f"skipped, {model_health.reason(m) or 'unavailable'} {describe_until(model_health.available_at(m))}"
            for m in blocked
        }
        if not models_to_try:
            soonest = min(blocked, key=model_health.available_at)
            raise RuntimeError(
                f"All Gemini models are out of quota or unavailable. {soonest} can be used again "
                f"{describe_until(model_health.available_at(soonest))}. "
                f"Details: {'; '.join(f'[{m}] {e}' for m, e in errors_by_model.items())}"
            )
        for model_name in models_to_try:
            remaining = deadline - time.monotonic()
            if remaining < 3:
                errors_by_model[model_name] = f"not tried, the {TOTAL_TIME_BUDGET:.0f}s time limit ran out"
                continue
            cooling = model_health.cooldown_left(model_name)
            if cooling:
                logger.info(f"Trying {model_name} although it is cooling down ({cooling:.0f}s left): no healthier model answered")

            thinking = None if model_name in model_health.no_thinking else thinking_config_for(model_name, level)
            attempt_timeout = httpx.Timeout(min(ATTEMPT_TIMEOUT, remaining), connect=CONNECT_TIMEOUT)
            try:
                async with httpx.AsyncClient(timeout=attempt_timeout) as client:
                    resp = await client.post(
                        f"{GEMINI_API_BASE}/models/{model_name}:generateContent",
                        json=self._build_payload(contents, system_instruction, thinking),
                        headers=self._auth_headers(),
                    )
                    if resp.status_code == 400 and thinking and "thinking" in resp.text.lower():
                        # This model rejects our thinking setting: remember that and retry with its default
                        model_health.no_thinking.add(model_name)
                        logger.info(f"{model_name} rejected thinkingConfig {thinking}; retrying with the model default")
                        resp = await client.post(
                            f"{GEMINI_API_BASE}/models/{model_name}:generateContent",
                            json=self._build_payload(contents, system_instruction, None),
                            headers=self._auth_headers(),
                        )
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                # Every model lives on the same host, so trying the others won't help
                raise RuntimeError(
                    f"Can't reach the Gemini API ({type(e).__name__}). Check your internet connection and try again."
                ) from e
            except httpx.TimeoutException:
                err_msg = f"Request timed out on {model_name} after {attempt_timeout.read:.0f}s"
                errors_by_model[model_name] = err_msg
                model_health.failed(model_name, reason="timed out")
                logger.warning(f"{err_msg}; skipping it {describe_until(model_health.available_at(model_name))}")
                continue
            except Exception as e:
                err_msg = f"Error calling {model_name}: {str(e)}"
                errors_by_model[model_name] = err_msg
                logger.warning(err_msg)
                continue

            if resp.status_code == 200:
                text, problem = _extract_text(resp.json())
                if text:
                    model_health.succeeded(model_name)
                    if model_name != self.model:
                        logger.info(f"Fallback model '{model_name}' answered because '{self.model}' was unavailable.")
                    return text
                errors_by_model[model_name] = problem
                continue

            error_detail, retry_after, daily_quota = _parse_error(resp)
            err_msg = f"HTTP {resp.status_code}: {error_detail}"
            errors_by_model[model_name] = err_msg
            if resp.status_code in (401, 403):
                # A bad or restricted key fails the same way on every model
                raise RuntimeError(f"Gemini rejected the API key: {err_msg}")
            if resp.status_code == 429:
                if daily_quota and not retry_after:
                    retry_after = seconds_until_quota_reset()
                # With a known reset time the model will refuse until then: don't try it at all
                model_health.failed(
                    model_name, retry_after=retry_after, hard=retry_after is not None,
                    reason="daily quota used up" if daily_quota else "rate limited",
                )
            elif resp.status_code == 404:
                model_health.failed(model_name, hard=True, reason="model not found")
            elif resp.status_code in (500, 502, 503, 504):
                model_health.failed(model_name, reason=f"overloaded (HTTP {resp.status_code})")
            if model_health.cooldown_left(model_name):
                logger.warning(f"Gemini call to {model_name} failed: {err_msg}; skipping it {describe_until(model_health.available_at(model_name))}")
            else:
                logger.warning(f"Gemini call to {model_name} failed: {err_msg}")

        primary_err = errors_by_model.get(self.model, "Unknown error")
        details = [f"[{m}] {err}" for m, err in errors_by_model.items()]
        raise RuntimeError(
            f"Configured Gemini model '{self.model}' failed: {primary_err}. "
            f"All attempted models failed: {'; '.join(details)}"
        )

    @staticmethod
    def _build_payload(
        contents: List[Dict[str, Any]], system_instruction: Optional[str], thinking: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        generation_config: Dict[str, Any] = {
            "temperature": 0.7,
            # Thinking tokens count towards this limit, so leave room for them
            "maxOutputTokens": 4096,
        }
        if thinking:
            generation_config["thinkingConfig"] = thinking
        payload: Dict[str, Any] = {"contents": contents, "generationConfig": generation_config}
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        return payload

    async def analyze_vocab(
        self,
        vocab_input: str,
        custom_hint: str = "",
        jlpt_level: Optional[str] = None
    ) -> Dict[str, Any]:
        target_jlpt = jlpt_level or self.jlpt_level

        system_instruction = (
            "You are a master Japanese lexicographer, linguist, and Anki vocabulary expert. "
            "The user will provide a Japanese vocabulary word, phrase, or sentence to mine into Anki. "
            "Your task is to analyze this vocabulary item and return accurate linguistic metadata. "
            "Rules:\n"
            "1. 'vocab_kanji': The canonical Japanese dictionary form or expression (e.g. '限界', '見失う', '一目惚れ', 'バイク').\n"
            "2. 'vocab_furigana': Standard bracket furigana syntax (e.g. '限界[げんかい]', '見失[みうしな]う', '一目惚[ひとめぼ]れ', 'バイク').\n"
            "3. 'vocab_def': Crisp, concise, natural English definition (e.g. 'limit; boundary; bound').\n"
            "4. 'pitch_num': Pitch accent number string if known (e.g. '0', '1', '2', etc.), otherwise ''.\n"
            "5. 'pitch_pattern': Pitch pattern description (e.g. 'Heiban', 'Atamadaka', 'Nakadaka', 'Odaka') if known, otherwise ''.\n"
            "6. 'sent_kanji': If the user's input or hint provided an explicit Japanese sentence, format it here with the target word in <b>word</b> tags. Otherwise return ''.\n"
            "7. 'sent_furigana': If an explicit sentence was provided, format with bracket furigana and <b>...</b> tags. Otherwise return ''.\n"
            "8. 'sent_eng': If an explicit sentence was provided, provide its English translation. Otherwise return ''.\n"
            "Return strict JSON only without markdown formatting."
        )

        prompt = f"""
Input Japanese Expression: {vocab_input}
Optional Context / Hint: {custom_hint if custom_hint else 'None'}
Target JLPT / Level: {target_jlpt}

Return valid JSON with keys:
- vocab_kanji
- vocab_furigana
- vocab_def
- pitch_num
- pitch_pattern
- sent_kanji
- sent_furigana
- sent_eng
"""
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        raw_resp = await self._call_gemini(contents, system_instruction=system_instruction)
        clean_json = raw_resp.strip()
        if clean_json.startswith("```"):
            clean_json = clean_json.split("\n", 1)[-1]
            if clean_json.endswith("```"):
                clean_json = clean_json.rsplit("```", 1)[0]
        clean_json = clean_json.strip()

        try:
            parsed = json.loads(clean_json)
            sent_kanji, sent_furigana = clean_sentence_pair(
                str(parsed.get("sent_kanji", "") or ""), str(parsed.get("sent_furigana", "") or "")
            )
            return {
                "vocabKanji": parsed.get("vocab_kanji", vocab_input.strip()),
                "vocabFurigana": normalize_furigana(str(parsed.get("vocab_furigana") or vocab_input.strip())),
                "vocabDef": parsed.get("vocab_def", ""),
                "pitchNum": str(parsed.get("pitch_num", "") or ""),
                "pitchPattern": parsed.get("pitch_pattern", ""),
                "sentKanji": sent_kanji,
                "sentFurigana": sent_furigana,
                "sentEng": parsed.get("sent_eng", ""),
            }
        except Exception:
            return {
                "vocabKanji": vocab_input.strip(),
                "vocabFurigana": vocab_input.strip(),
                "vocabDef": "",
                "pitchNum": "",
                "pitchPattern": "",
                "sentKanji": "",
                "sentFurigana": "",
                "sentEng": "",
            }

    async def analyze_grammar(
        self,
        pattern_input: str,
        custom_hint: str = "",
        jlpt_level: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyzes a Japanese grammar point (e.g. '〜ばかり', '〜ようにする') for mining into
        the 'Japanese sentences' note type. The pattern goes in the Vocab fields, the
        example sentence bolds the conjugated grammar chunk, and formation/nuance go in Notes.
        """
        target_jlpt = (jlpt_level or self.jlpt_level or "N4").upper()

        system_instruction = (
            "You are a master Japanese grammar teacher and JLPT N5-N3 exam coach building Anki grammar cards. "
            "The user will provide a Japanese grammar point (pattern), optionally with a sentence where they saw it. "
            "Rules:\n"
            "1. 'pattern': The canonical dictionary-style grammar pattern using 〜 for the attachment slot (e.g. '〜ばかり', '〜ようにする', '〜わけではない', '〜てしまう').\n"
            "2. 'pattern_furigana': EXACTLY the same characters as 'pattern', adding bracket furigana only after kanji that already appear in 'pattern' (e.g. '〜に 関[かん]して'). If 'pattern' has no kanji, return it unchanged. NEVER add or substitute kanji (だけ stays だけ, よう stays よう).\n"
            "3. 'meaning': Crisp English meaning(s) separated by '; ' (e.g. 'just did ~; nothing but ~').\n"
            "4. 'formation': Conjugation/attachment rules in compact form (e.g. 'V-た + ばかり (just did) / N + ばかり (nothing but)').\n"
            "5. 'nuance': 1-3 short sentences on nuance, register, and the most common JLPT trap or confusion.\n"
            "6. 'similar': 1-3 similar/confusable patterns with a short contrast each (e.g. '〜たところ: just finished, more precise in time').\n"
            "7. 'jlpt_level': The JLPT level this grammar point is usually taught at (N5, N4, N3, N2, N1).\n"
            "8. 'sent_kanji': A short natural example sentence (or the user's sentence if they gave one) with the FULL conjugated grammar chunk wrapped in <b>...</b> (e.g. '日本に来た<b>ばかり</b>です。' or '<b>食べたばかり</b>'). NO furigana.\n"
            "9. 'sent_furigana': Same sentence with bracket furigana [reading] on EVERY kanji word, a leading space before each kanji block, and the same <b>...</b> span.\n"
            "10. 'sent_eng': Natural English translation.\n"
            f"Keep the example sentence at JLPT {target_jlpt} difficulty or easier apart from the grammar point itself.\n"
            "Return strict JSON only without markdown formatting."
        )

        prompt = f"""
Grammar Point: {pattern_input}
Sentence / Context Hint: {custom_hint if custom_hint else 'None'}
Learner's Target JLPT Level: {target_jlpt}

Return valid JSON with keys:
- pattern
- pattern_furigana
- meaning
- formation
- nuance
- similar
- jlpt_level
- sent_kanji
- sent_furigana
- sent_eng
"""
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        raw_resp = await self._call_gemini(contents, system_instruction=system_instruction)
        try:
            parsed = json.loads(_strip_json_fences(raw_resp))
        except Exception:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}

        pattern = str(parsed.get("pattern") or pattern_input).strip()
        level = str(parsed.get("jlpt_level") or target_jlpt).strip().upper()
        if level not in ("N5", "N4", "N3", "N2", "N1"):
            level = target_jlpt

        notes_parts = []
        if parsed.get("formation"):
            notes_parts.append(f"**Formation:** {parsed['formation']}")
        if parsed.get("nuance"):
            notes_parts.append(f"**Nuance:** {parsed['nuance']}")
        similar = parsed.get("similar")
        if isinstance(similar, list):
            similar = "\n".join(f"- {s}" for s in similar if s)
        if similar:
            notes_parts.append(f"**Similar patterns:**\n{similar}")

        raw_furigana = str(parsed.get("sent_furigana", "") or "")
        pattern_furigana = str(parsed.get("pattern_furigana") or pattern).strip()
        # Guard against invented kanji: with readings stripped, the furigana
        # form must spell exactly the pattern (e.g. '〜 堂[だけ]でなく' -> rejected).
        if re.sub(r"\s|\[[^\]]*\]", "", pattern_furigana) != re.sub(r"\s", "", pattern):
            pattern_furigana = pattern
        sent_kanji, sent_furigana = clean_sentence_pair(str(parsed.get("sent_kanji", "") or ""), raw_furigana)
        return {
            "vocabKanji": pattern,
            "vocabFurigana": normalize_furigana(pattern_furigana),
            "vocabDef": str(parsed.get("meaning", "") or "").strip(),
            "pitchNum": "",
            "pitchPattern": "",
            "sentKanji": sent_kanji,
            "sentFurigana": sent_furigana,
            "sentEng": str(parsed.get("sent_eng", "") or "").strip(),
            "notes": "\n\n".join(notes_parts),
            "jlptLevel": level,
        }

    async def generate_mnemonic(
        self,
        vocab_kanji: str,
        vocab_furigana: str,
        vocab_def: str,
        kanji_details: Dict[str, Dict[str, Any]],
        notes: str = "",
        custom_instructions: str = "",
        mnemonic_style: Optional[str] = None,
        tone: Optional[str] = None,
        confusable_cards: Optional[List[Dict[str, Any]]] = None,
        card_type: str = "vocab",
    ) -> Dict[str, Any]:
        style = (mnemonic_style or self.mnemonic_style).lower()
        active_tone = tone or self.mnemonic_tone

        if card_type == "grammar":
            return await self._generate_grammar_mnemonic(
                pattern=vocab_kanji,
                meaning=vocab_def,
                notes=notes,
                custom_instructions=custom_instructions,
                style=style,
                tone=active_tone,
                confusable_cards=confusable_cards,
            )

        if style in ["historical", "etymology", "etymological"]:
            style_mission = (
                "You are a master Japanese etymologist and kanji historian. "
                "Your mission is to decompose the constituent kanji into their genuine historical origins, ancient pictographic radicals "
                "(oracle bone / bronze script roots), and traditional semantic evolutions, weaving them into a deeply fascinating, historically "
                "grounded memory synthesis that explains WHY the character means what it does."
            )
            story_header = "### 🏛️ Etymological Synthesis Story"
            story_desc = "[Historically grounded narrative explaining the ancient pictographs, radical origins, and character evolution. Always include the actual kanji character alongside its meaning, e.g. 魔 (witch/demon) and 邪 (wicked/crooked)]"
        elif style == "cinematic":
            style_mission = (
                "You are a master cinematic visual storyteller and director. "
                "Your mission is to craft a high-stakes, cinematic scene rich in sensory detail (colors, lighting, sound effects, textures, and tension) "
                "blending the kanji primitives/stories into an unforgettable movie moment."
            )
            story_header = "### 🎬 Cinematic Synthesis Scene"
            story_desc = "[High-intensity, sensory-rich cinematic scene blending the constituent kanji elements into a vivid movie moment. Always include the actual kanji character alongside its keyword, e.g. 魔 (witch) and 邪 (wicked)]"
        elif style == "minimalist":
            style_mission = (
                "You are a minimalist memory coach. "
                "Your mission is to create ultra-condensed, rapid-fire mnemonic associations stripped of all fluff, "
                "focusing purely on direct radical-to-meaning bridges and instant phonetic triggers for high-speed flashcard review."
            )
            story_header = "### ⚡ Rapid Mnemonic Link"
            story_desc = "[Ultra-concise, rapid-association bridge directly linking each kanji character to the meaning, e.g. 魔 (witch) + 邪 (wicked) = obstruction/nuisance]"
        else:
            # Default: Playful / Modern
            style_mission = (
                "You are an elite Japanese language mnemonics coach and RTK (Remembering the Kanji) expert. "
                "Your mission is to synthesize the user's personal RTK kanji keywords and their custom "
                "kanji stories into an unforgettable, high-impact composite mnemonic for the target vocabulary word."
            )
            story_header = "### 🧠 RTK Synthesis Story"
            story_desc = "[Entertaining, vivid composite narrative blending the constituent kanji keywords/stories into the meaning. Always include the actual kanji character alongside its keyword, e.g. 魔 (witch) and 邪 (wicked)]"

        contrast_instruction = (
            f"   - **🔍 Contrast & Disambiguation Hook**: Explicitly contrast the Target word against each of the {len(confusable_cards)} conflicting cards selected from the deck (highlighting differing radicals, pronunciations, or nuances to permanently eliminate interference).\n"
        ) if confusable_cards else ""

        system_instruction = (
            f"{style_mission}\n\n"
            "CRITICAL RULES:\n"
            "1. If a constituent kanji was not found in the user's RTK deck or deck lookup is disabled, do NOT say 'Unknown' or treat 'Unknown' as a concept. Instead, naturally decompose the kanji into its standard primitives/radicals on the fly (e.g. 女 woman + 喜 rejoice/drum for 嬉) and weave them directly into your synthesis.\n"
            "2. **Explicit Kanji Character Anchoring**: When referencing constituent kanji keywords or radicals inside the TL;DR Hook and Synthesis Story, ALWAYS explicitly include the actual Japanese kanji character directly alongside its English keyword/concept (e.g. write '魔 (witch)' and '邪 (wicked)', '現 (present) + 金 (money)', or '牙 (tusk)'). Never refer to a keyword in isolation without its corresponding kanji character.\n"
            "3. NO introductory chatter, greetings, or filler lines (do NOT say 'Here is your elite mnemonic synthesis...', 'Sure, here is...', etc.). Start directly with the TL;DR Hook.\n"
            "4. NO meta-commentary or concluding fluff at the end (do NOT include 'Why this works for you', 'Why this sticks', 'Breakdown', etc.).\n"
            "5. Structure the output strictly in this exact order:\n"
            "   - **🎯 TL;DR Hook**: A punchy 1-sentence summary combining the kanji characters/meanings (e.g. 魔 witch + 邪 wicked), reading pun, and definition for rapid Anki flashcard review.\n"
            f"   - **{story_header.replace('### ', '')}**: The core synthesis story according to the chosen style, explicitly tagging each kanji character.\n"
            "   - **🔊 Phonetic Reading Link**: An English sound-alike pun/bridge explicitly connecting the kana reading to the situation.\n"
            f"{contrast_instruction}"
            f"Mnemonic Tone / Style Guidelines: {active_tone}\n"
            f"User Persona Context: {self.persona}\n"
            "Keep the output clean, direct, punchy, and distraction-free."
        )

        kanji_summary_lines = []
        for k, info in (kanji_details or {}).items():
            if not info or not info.get("found") or not info.get("keyword") or info.get("keyword") in ["Unknown", "Error", "None", "N/A"]:
                kanji_summary_lines.append(
                    f"- Kanji: 【{k}】 (Not in deck)\n"
                    f"  Instruction: Decompose the radicals/components of 【{k}】 on the fly and craft a natural, memorable story connecting to the word's meaning."
                )
            else:
                kw = info.get("keyword")
                story = info.get("myStory") or info.get("koohiiStory1") or info.get("heisigStory") or "No custom story recorded."
                kanji_summary_lines.append(f"- Kanji: 【{k}】 (Keyword: \"{kw}\")\n  User's Story/Mnemonic: {story}")

        kanji_section = "\n".join(kanji_summary_lines) if kanji_summary_lines else "None (Kana-only word)"

        confusable_section = ""
        if confusable_cards:
            conf_lines = []
            for i, c in enumerate(confusable_cards, 1):
                vk = c.get("vocabKanji", "")
                vf = c.get("vocabFurigana", "")
                vd = c.get("vocabDef", "")
                deck = c.get("deckName", "").split("::")[-1]
                reasons = ", ".join(c.get("collisionReasons", [])) or "Similar card in deck"
                conf_lines.append(f"{i}. 【{vk}】 ({vf}) [{deck}] - '{vd}'\n   Interference: {reasons}")
            confusable_section = "\nConfusable / Conflicting Cards Selected from User's Deck:\n" + "\n".join(conf_lines) + "\n"

        prompt = f"""
Target Vocabulary: {vocab_kanji}
Reading/Furigana: {vocab_furigana}
English Meaning: {vocab_def}

Constituent Kanji & Stories:
{kanji_section}
{confusable_section}
Existing Card Notes:
{notes if notes else 'None'}

Custom User Instruction / Context:
{custom_instructions if custom_instructions else 'None'}

Generate the mnemonic formatted strictly as follows (no intro sentence, no 'Why this works' section at the end):

### 🎯 TL;DR Hook
[1-sentence rapid-review punchline linking kanji characters & keywords (e.g. 魔 witch + 邪 wicked) + reading pun + definition]

{story_header}
{story_desc}

### 🔊 Phonetic Reading Link
[Clever English sound-alike pun connecting the reading to the scene]
"""
        if confusable_cards:
            prompt += f"""
### 🔍 Contrast & Disambiguation Hook
[1-3 sentences explicitly contrasting the target word against all {len(confusable_cards)} selected confusable card(s) above, highlighting differing radicals, pronunciations, and nuance to permanently eliminate interference]
"""

        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        mnemonic_text = await self._call_gemini(contents, system_instruction=system_instruction)
        
        # Clean up any stray conversational intro lines or footer sections if model generated them
        lines = mnemonic_text.strip().split("\n")
        while lines and (
            lines[0].lower().startswith("here is")
            or lines[0].lower().startswith("here's")
            or lines[0].lower().startswith("sure")
            or lines[0].lower().startswith("certainly")
        ):
            lines.pop(0)
            if lines and not lines[0].strip():
                lines.pop(0)
        
        cleaned_text = "\n".join(lines).strip()
        
        # Strip out any trailing "Why this works for you" / "Why this sticks" section
        for footer_marker in [
            "### Why this works", "## Why this works", "# Why this works", "**Why this works",
            "### Why this sticks", "## Why this sticks", "# Why this sticks", "**Why this sticks",
            "### Why It Works", "## Why It Works", "# Why It Works", "**Why It Works"
        ]:
            if footer_marker.lower() in cleaned_text.lower():
                idx = cleaned_text.lower().find(footer_marker.lower())
                if idx != -1:
                    cleaned_text = cleaned_text[:idx].strip()

        return {
            "vocab": vocab_kanji,
            "mnemonic": cleaned_text,
            "style": style
        }

    async def _generate_grammar_mnemonic(
        self,
        pattern: str,
        meaning: str,
        notes: str,
        custom_instructions: str,
        style: str,
        tone: str,
        confusable_cards: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Memory hook for a grammar point: meaning + formation, no kanji decomposition."""
        contrast_rule = (
            "   - **🔍 Contrast & Disambiguation Hook**: Explicitly contrast the target pattern against the confusable patterns/cards listed.\n"
        ) if confusable_cards else ""
        system_instruction = (
            "You are an elite Japanese grammar coach preparing a learner for the JLPT. "
            "Create an unforgettable memory hook for a GRAMMAR POINT (not a vocabulary word). "
            "Focus on what the pattern means, how it attaches (formation), and the nuance that separates it from look-alike patterns. "
            "Do NOT decompose kanji or radicals.\n"
            "CRITICAL RULES:\n"
            "1. NO introductory chatter or concluding fluff. Start directly with the TL;DR Hook.\n"
            "2. Structure the output strictly in this order:\n"
            "   - **🎯 TL;DR Hook**: One punchy sentence tying the pattern's sound/shape to its meaning.\n"
            "   - **🎬 Scene**: A short vivid scene (2-4 sentences) that makes the meaning and nuance stick.\n"
            "   - **🔧 Formation Cue**: A one-line trick for remembering how it attaches (e.g. 'た-form + ばかり = the paint is still wet').\n"
            f"{contrast_rule}"
            f"Mnemonic style: {style}. Tone guidelines: {tone}\n"
            f"User Persona Context: {self.persona}\n"
        )
        confusable_section = ""
        if confusable_cards:
            lines = [f"- {c.get('vocabKanji', '')}: {c.get('vocabDef', '')}" for c in confusable_cards]
            confusable_section = "Confusable patterns/cards:\n" + "\n".join(lines) + "\n"
        prompt = f"""
Target Grammar Point: {pattern}
Meaning: {meaning}
Existing Card Notes (formation / nuance):
{notes if notes else 'None'}
{confusable_section}
Custom User Instruction / Context:
{custom_instructions if custom_instructions else 'None'}

Generate the mnemonic formatted strictly as follows:

### 🎯 TL;DR Hook
[1 sentence]

### 🎬 Scene
[2-4 sentences]

### 🔧 Formation Cue
[1 line]
"""
        if confusable_cards:
            prompt += "\n### 🔍 Contrast & Disambiguation Hook\n[1-3 sentences]\n"
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        text = await self._call_gemini(contents, system_instruction=system_instruction)
        lines = text.strip().split("\n")
        while lines and lines[0].lower().startswith(("here is", "here's", "sure", "certainly")):
            lines.pop(0)
            if lines and not lines[0].strip():
                lines.pop(0)
        return {"vocab": pattern, "mnemonic": "\n".join(lines).strip(), "style": style}

    async def generate_personalized_sentence(
        self,
        vocab_kanji: str,
        vocab_furigana: str,
        vocab_def: str,
        current_sentence: str = "",
        personas: Optional[List[str]] = None,
        custom_topic: str = "",
        jlpt_level: Optional[str] = None,
        card_type: str = "vocab"
    ) -> Dict[str, str]:
        is_grammar = card_type == "grammar"
        target_jlpt = jlpt_level or self.jlpt_level
        is_general = not target_jlpt or target_jlpt.lower() == "general"

        active_personas = personas if personas and len(personas) > 0 else [
            "Software Engineering & Debugging",
            "Motorcycle Riding & Mechanics",
            "Witty & Absurd Everyday Tokyo Comedy",
            "Dark Sci-Fi & Cyberpunk"
        ]

        if is_general:
            level_rule = "1. **Difficulty Calibration**: Use natural, everyday conversational grammar and common vocabulary."
            reminder_text = "Keep the Japanese sentence SHORT, punchy, and natural with NO obscure kanji clutter."
        else:
            level_rule = f"1. **JLPT {target_jlpt} Difficulty Calibration**: Use natural grammar and common vocabulary strictly calibrated for JLPT {target_jlpt} learners (avoid grammar or kanji above JLPT {target_jlpt})."
            reminder_text = f"Keep the Japanese sentence SHORT, punchy, and strictly at JLPT {target_jlpt} difficulty with NO obscure kanji clutter."

        system_instruction = (
            f"You are an expert Japanese tutor creating custom Anki example sentences tailored for {('JLPT ' + target_jlpt) if not is_general else 'general Japanese'} study. "
            f"The student's baseline background: {self.persona}. "
            "The student has provided an active pool of favorite personas and interest domains. "
            "Your job is to examine the target vocabulary word and intelligently pick whichever persona "
            "from the student's active pool yields the most natural, memorable, witty, or vivid scenario for this specific word. "
            "\n"
            "CRITICAL SENTENCE RULES:\n"
            f"{level_rule}\n"
            + (
            "GRAMMAR MODE: The target is a GRAMMAR POINT, not a vocabulary word. Write a sentence that uses the grammar pattern naturally and "
            "wrap the FULL conjugated grammar chunk in <b>...</b> (e.g. for 〜ばかり: '日本に 来[き]た<b>ばかり</b>です' or '<b>食べたばかり</b>'). "
            "Do NOT write the 〜 symbol in the sentence. Rule 2 below applies to that bolded grammar chunk.\n"
            if is_grammar else ""
            ) +
            "2. **Target Word Bold Tags in BOTH Sentences**: You MUST enclose the target vocabulary word in <b>...</b> tags in BOTH 'sent_kanji' and 'sent_furigana' (e.g. sent_kanji: 'テストの<b>最中</b>に...', sent_furigana: 'テストの<b> 最中[さいちゅう]</b>に...'). Never omit the <b> tags in either field!\n"
            "3. **sent_kanji (STRICTLY NO FURIGANA)**: 'sent_kanji' is the clean Japanese sentence WITHOUT ANY FURIGANA. It MUST NOT contain any bracket furigana [...], ruby tags, or parenthetical readings. It must be clean kanji/kana only with <b> tags around the target word.\n"
            "4. **sent_furigana (EVERY KANJI WORD MUST HAVE FURIGANA & LEADING SPACE)**: In 'sent_furigana', EVERY SINGLE kanji word in the entire sentence MUST have bracket furigana [reading] so Anki displays the reading on top of each kanji character. Furthermore, every kanji block with furigana MUST have a leading space preceding it (including inside <b> tags, e.g. ' 来週[らいしゅう]の 社員[しゃいん] 旅行[りょこう]に<b> 参加[さんか]</b>します。').\n"
            "5. **Concise & Punchy**: Keep the sentence SHORT and easy to read during rapid Anki flashcard reviews (target 12-25 characters). Avoid long, winding compound sentences.\n"
            "6. **Zero Kanji Clutter**: Do NOT introduce difficult, rare, or overly advanced kanji in the surrounding text. The target vocabulary word MUST be the main focal point.\n"
            "\n"
            "Output strict JSON with five fields:\n"
            "1. 'theme_used': The name and emoji of the chosen persona/theme (e.g. '🏍️ Motorcycle Riding & Mechanics' or '💻 Software Engineering').\n"
            "2. 'sent_kanji': Japanese sentence with the target word in <b>word</b> tags and NO furigana.\n"
            "3. 'sent_furigana': Japanese sentence with bracket furigana on EVERY kanji, proper leading spaces before each kanji block, and target word inside <b>.\n"
            "4. 'sent_eng': Concise, natural English translation.\n"
            "5. 'rationale': A brief 1-sentence note explaining why this scenario makes the word stick.\n"
            "Output JSON only, no markdown backticks."
        )

        persona_bullet_list = "\n".join(f"- {p}" for p in active_personas)
        if is_grammar:
            furigana_example = "' 日本[にほん]に 来[き]た<b>ばかり</b>です。'"
        else:
            furigana_example = f"' 彼女[かのじょ]は<b> {vocab_kanji}[{vocab_furigana if vocab_furigana else 'reading'}]</b>に 行[い]きました。'"

        prompt = f"""
{"Target Grammar Point" if is_grammar else "Target Vocabulary"}: {vocab_kanji} ({vocab_furigana})
Definition: {vocab_def}
Target Difficulty Level: {target_jlpt if not is_general else 'General Conversational'}
Original Sentence in Card (for reference): {current_sentence if current_sentence else 'None'}

Active User Personas Pool (pick the best fit):
{persona_bullet_list}

Additional Specific Scenario / Custom Hint (if any):
{custom_topic if custom_topic else 'None'}

Remember: {reminder_text}
CRITICAL FORMATTING CHECKLIST:
- 'sent_kanji': Plain sentence with NO furigana, NO brackets [...], NO ruby tags. {"The full conjugated grammar chunk MUST be in <b>...</b> tags." if is_grammar else f"Target word MUST be in <b>{vocab_kanji}</b> tags."}
- 'sent_furigana': Every kanji word MUST have bracket furigana [reading] and a leading space before each kanji block (e.g. {furigana_example}). Target word MUST be in <b>...</b> tags.
- 'sent_eng': Natural English translation.
Return valid JSON with keys: theme_used, sent_kanji, sent_furigana, sent_eng, rationale.
"""
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        MAX_RETRIES = 2
        attempt = 0
        conversation_history = contents.copy()
        parsed = None
        raw_resp = ""

        while attempt <= MAX_RETRIES:
            raw_resp = await self._call_gemini(conversation_history, system_instruction=system_instruction)
            clean_json = raw_resp.strip()
            if clean_json.startswith("```"):
                clean_json = clean_json.split("\n", 1)[-1]
                if clean_json.endswith("```"):
                    clean_json = clean_json.rsplit("```", 1)[0]
            clean_json = clean_json.strip()

            try:
                parsed = json.loads(clean_json)
            except Exception:
                parsed = None

            if parsed and isinstance(parsed, dict):
                # Fix spacing, okurigana and stray readings in code first, so only problems
                # that need the model (missing readings or bold tags) cost a retry
                furigana = str(parsed.get("sent_furigana", "") or "")
                if not is_grammar:
                    furigana = keep_target_bold(furigana, vocab_kanji)
                parsed["sent_kanji"], parsed["sent_furigana"] = clean_sentence_pair(
                    str(parsed.get("sent_kanji", "") or ""), furigana
                )
                is_valid, errors = validate_persona_sentence(parsed, vocab_kanji, is_grammar=is_grammar)
                if is_valid:
                    return {
                        "themeUsed": parsed.get("theme_used", active_personas[0]),
                        "sentKanji": parsed["sent_kanji"],
                        "sentFurigana": parsed["sent_furigana"],
                        "sentEng": str(parsed.get("sent_eng", "")).strip(),
                        "rationale": str(parsed.get("rationale", "")).strip()
                    }
                else:
                    attempt += 1
                    if attempt <= MAX_RETRIES:
                        feedback = (
                            f"FORMATTING VALIDATION FAILED (Attempt {attempt} of {MAX_RETRIES}):\n"
                            + "\n".join(f"- {err}" for err in errors) + "\n\n"
                            "CRITICAL INSTRUCTIONS TO FIX:\n"
                            f"1. Target word '{vocab_kanji}' MUST be wrapped in <b>...</b> bold tags in BOTH sent_kanji and sent_furigana.\n"
                            "2. sent_kanji MUST NOT contain any bracket furigana [...] or ruby tags or readings. Keep it clean Japanese text.\n"
                            "3. sent_furigana MUST have bracket furigana [reading] on EVERY single kanji word, with a leading space before each kanji block (e.g. ' 漢字[かんじ]').\n"
                            "Regenerate the entire JSON response correcting all listed issues. Return JSON only."
                        )
                        conversation_history.append({"role": "model", "parts": [{"text": raw_resp}]})
                        conversation_history.append({"role": "user", "parts": [{"text": feedback}]})
            else:
                attempt += 1
                if attempt <= MAX_RETRIES:
                    feedback = "Response was not valid JSON. Please return a strict JSON object with keys: theme_used, sent_kanji, sent_furigana, sent_eng, rationale."
                    conversation_history.append({"role": "model", "parts": [{"text": raw_resp}]})
                    conversation_history.append({"role": "user", "parts": [{"text": feedback}]})

        # Sanitize fallback if retries exhausted:
        if parsed and isinstance(parsed, dict):
            sent_kanji = str(parsed.get("sent_kanji", "")).strip()
            # Strip accidental bracket furigana from sent_kanji
            sent_kanji = re.sub(r"\[[^\]]+\]", "", sent_kanji)
            if "<b>" not in sent_kanji and vocab_kanji in sent_kanji:
                sent_kanji = sent_kanji.replace(vocab_kanji, f"<b>{vocab_kanji}</b>", 1)

            sent_furigana = str(parsed.get("sent_furigana", "")).strip()
            if "<b>" not in sent_furigana and vocab_kanji in sent_furigana:
                sent_furigana = sent_furigana.replace(vocab_kanji, f"<b>{vocab_kanji}</b>", 1)
            formatted_furigana = normalize_furigana(sent_furigana)

            return {
                "themeUsed": parsed.get("theme_used", active_personas[0]),
                "sentKanji": sent_kanji,
                "sentFurigana": formatted_furigana,
                "sentEng": str(parsed.get("sent_eng", "")).strip(),
                "rationale": str(parsed.get("rationale", "")).strip()
            }

        return {
            "themeUsed": active_personas[0] if active_personas else "General",
            "sentKanji": f"<b>{vocab_kanji}</b>を使います。",
            "sentFurigana": f"<b> {vocab_kanji}[{vocab_furigana if vocab_furigana else 'つかい'}]</b>を 使[つか]います。",
            "sentEng": f"Raw generated response: {raw_resp}",
            "rationale": "",
            "fallback": True
        }

    async def chat_tutor(
        self,
        vocab_kanji: str,
        vocab_furigana: str,
        vocab_def: str,
        kanji_details: Dict[str, Dict[str, Any]],
        conversation_history: List[Dict[str, str]],
        user_message: str,
        jlpt_level: Optional[str] = None,
        confusable_cards: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        target_jlpt = jlpt_level or self.jlpt_level
        is_general = not target_jlpt or target_jlpt.lower() == "general"
        level_phrase = f"JLPT {target_jlpt}" if not is_general else "everyday Japanese conversation"

        system_instruction = (
            "You are a dedicated, deeply knowledgeable Japanese Sensei and Language Tutor. "
            "You are doing a hand-by-hand card review with the user to diagnose why this specific vocabulary card "
            "is a leech in Anki. "
            "Help the user:\n"
            f"- Understand subtle nuances and common confusion traps (e.g. why they confuse this word with similar words/readings).\n"
            f"- Provide direct, honest advice on whether this word is critical for {level_phrase} and real-life conversational use in Japan.\n"
            "- Brainstorm custom mnemonics, sound mnemonics, or collocations.\n"
            f"User Persona: {self.persona}\n"
            "Keep your tone encouraging, sharp, direct, and insightful."
        )

        kanji_summary = ", ".join([f"{k} (Keyword: {v.get('keyword')}, Story: {v.get('myStory') or v.get('koohiiStory1') or 'None'})" for k, v in kanji_details.items()])

        confusable_str = ""
        if confusable_cards:
            conf_items = []
            for c in confusable_cards:
                vk = c.get("vocabKanji", "")
                vf = c.get("vocabFurigana", "")
                reasons = ", ".join(c.get("collisionReasons", [])) or "Look-alike / Sound-alike"
                conf_items.append(f"{vk} ({vf} - {reasons})")
            confusable_str = f" | Confusable Deck Neighbors: {', '.join(conf_items)}"

        card_context = (
            f"[Current Card Context: Vocab: {vocab_kanji} | Furigana: {vocab_furigana} | "
            f"Meaning: {vocab_def} | Constituent Kanji: {kanji_summary}{confusable_str} | Target Level: {target_jlpt}]"
        )

        gemini_contents: List[Dict[str, Any]] = []
        
        # Inject card context into first message or history
        gemini_contents.append({
            "role": "user",
            "parts": [{"text": f"Let's review this card:\n{card_context}"}]
        })
        gemini_contents.append({
            "role": "model",
            "parts": [{"text": f"Ready to review **{vocab_kanji}** ({vocab_furigana} - {vocab_def}). What's giving you trouble with this word?"}]
        })

        for msg in conversation_history:
            role = "user" if msg.get("role") == "user" else "model"
            gemini_contents.append({
                "role": role,
                "parts": [{"text": msg.get("content", "")}]
            })

        gemini_contents.append({
            "role": "user",
            "parts": [{"text": user_message}]
        })

        return await self._call_gemini(gemini_contents, system_instruction=system_instruction)
