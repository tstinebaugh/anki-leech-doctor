"""Which Gemini models exist, what the aliases point at, and the order to try fallbacks in.

Three sources, all kept in the SQLite database (db.py):

- the model list (GET /v1beta/models), fetched again when it is more than a week old.
  It says which models exist but not how busy they are, nor where an alias such as
  gemini-flash-latest points;
- each reply's modelVersion (or the model a quota error names), saved with the call, which
  shows where an alias points today;
- the call log, which shows how often each model answered and how long that took.

fallback_plan() turns these into the order _call_gemini tries models in: the configured
model first, then the fallbacks by expected time per answer over the last week. Fallbacks
missing from the model list, or that Gemini last answered with a 404 (the list still has
models it no longer serves to new keys, like gemini-2.5-flash), are skipped, and so is a
name that points at the same model as one already in the order, since both would share
that model's quota and overload.

Non-Gemini providers (the OpenAI-compatible fallback, logged as "openai:<model>") come last
with role "provider": they get their call-log stats but none of the model-list or alias
checks, since Gemini's list never has them.
"""
import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

import httpx

from db import Database, ModelStats

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
CATALOG_MAX_AGE = timedelta(days=7)
CATALOG_RETRY_AFTER = 3600.0     # seconds to wait after a failed refresh before trying again
NEW_MODEL_DAYS = 14              # a model added to the list this recently is flagged as new
HEALTH_WINDOW = timedelta(days=7)
# An untried model counts as having answered once in 10s: about an average model, so it
# gets tried somewhere in the middle instead of first or never.
PRIOR_MS = 10_000
# Set to 0 to never fetch the model list on its own (the tests do this)
AUTO_REFRESH = os.environ.get("LEECH_DOCTOR_MODEL_REFRESH", "1") != "0"

# Prefix of the call-log name of a model served by the OpenAI-compatible fallback provider
PROVIDER_PREFIX = "openai:"


def is_provider(name: str) -> bool:
    return name.startswith(PROVIDER_PREFIX)


# Plain text Flash models: gemini-3.8-flash, gemini-3.1-flash-lite-preview,
# gemini-flash-latest... but not the TTS, image, live or tool-specific variants.
_TEXT_FLASH = re.compile(r"^gemini-(?:\d+(?:\.\d+)?-)?flash(?:-lite)?(?:-preview(?:-\d{2}-\d{4})?|-latest)?$")


def is_text_flash(name: str) -> bool:
    return bool(_TEXT_FLASH.match(name))


def _strip(name: Optional[str]) -> Optional[str]:
    return name.removeprefix("models/") if name else None


# ---- fetching the model list ----------------------------------------------------------------

async def fetch_models(api_key: str) -> List[Dict[str, Any]]:
    """Every model the key can call with generateContent, following pagination."""
    models: List[Dict[str, Any]] = []
    token: Optional[str] = None
    async with httpx.AsyncClient(timeout=15.0) as client:
        for _ in range(20):  # a few pages at most; guards against a token that never ends
            params: Dict[str, Any] = {"pageSize": 1000}
            if token:
                params["pageToken"] = token
            resp = await client.get(f"{GEMINI_API_BASE}/models", params=params, headers={"x-goog-api-key": api_key})
            resp.raise_for_status()
            data = resp.json()
            for m in data.get("models", []):
                if "generateContent" not in m.get("supportedGenerationMethods", []):
                    continue
                models.append({
                    "name": _strip(m.get("name")),
                    "display_name": m.get("displayName") or "",
                    "version": m.get("version"),
                    "output_token_limit": m.get("outputTokenLimit"),
                    "thinking": m.get("thinking"),
                })
            token = data.get("nextPageToken")
            if not token:
                break
    return models


def catalog_fetched_at(db: Database) -> Optional[datetime]:
    rows = db.catalog()
    return max((m.last_seen_at for m in rows), default=None)


def catalog_is_stale(db: Database, now: Optional[datetime] = None) -> bool:
    fetched = catalog_fetched_at(db)
    return fetched is None or (now or datetime.now(timezone.utc)) - fetched > CATALOG_MAX_AGE


_refresh_lock = asyncio.Lock()
_last_failure = 0.0
_background: Optional[asyncio.Task] = None


async def refresh_catalog(api_key: str, db: Optional[Database], force: bool = False) -> bool:
    """Fetches the model list if it is over a week old (or `force`). True if it was saved.

    Never raises: a failed refresh keeps the old list and waits an hour before trying again
    (unless forced)."""
    global _last_failure
    if not api_key or db is None:
        return False
    if not force and (not catalog_is_stale(db) or time.time() - _last_failure < CATALOG_RETRY_AFTER):
        return False
    async with _refresh_lock:
        if not force and not catalog_is_stale(db):
            return False  # another request refreshed it while this one waited
        try:
            models = await fetch_models(api_key)
            if not models:
                raise ValueError("the model list came back empty")
            db.save_catalog(models)
        except Exception as e:
            _last_failure = time.time()
            # str(e) of an HTTP error includes the URL, which has no key (it's sent as a header)
            logger.warning(f"Could not refresh the Gemini model list: {e}")
            return False
    logger.info(f"Refreshed the Gemini model list: {len(models)} models support generateContent")
    return True


def schedule_refresh(api_key: str, db: Optional[Database]) -> None:
    """Starts a background refresh when the list is stale, without delaying the caller."""
    global _background
    if not AUTO_REFRESH or not api_key or db is None:
        return
    if _background is not None and not _background.done():
        return
    try:
        if not catalog_is_stale(db) or time.time() - _last_failure < CATALOG_RETRY_AFTER:
            return
        _background = asyncio.get_running_loop().create_task(refresh_catalog(api_key, db))
    except Exception as e:
        logger.warning(f"Could not schedule a Gemini model list refresh: {e}")


# ---- fallback order ------------------------------------------------------------------------

def expected_ms(stats: Optional[ModelStats]) -> float:
    """Average time spent per answer, counting the attempts that failed: a model that
    answers in 5s but times out (25s) half the time costs 30s per answer.

    Sorting by this is the classic order for trying options one after another (cost of an
    attempt divided by its chance of success), so a model that fails instantly costs little
    to try, while one that makes you wait 25s for nothing sinks fast."""
    if stats is None:
        return float(PRIOR_MS)
    return (stats.ms_ok + stats.ms_lost + PRIOR_MS) / (stats.ok + 1)


@dataclass
class PlanEntry:
    model: str
    role: str                         # configured, fallback, provider (not Gemini, tried last)
    status: str                       # try, duplicate (same model as an earlier entry), missing
    expected_ms: float
    resolves_to: Optional[str] = None
    stats: Optional[ModelStats] = None
    note: str = ""


def fallback_plan(configured: str, pool: List[str], db: Optional[Database],
                  now: Optional[datetime] = None, providers: Sequence[str] = ()) -> List[PlanEntry]:
    """The configured model, then every fallback in the order to try it, then `providers`
    (non-Gemini models, tried after every Gemini model; see module docstring)."""
    now = now or datetime.now(timezone.utc)
    providers = list(dict.fromkeys([*providers, *(m for m in pool if is_provider(m))]))
    pool = [m for m in pool if not is_provider(m)]
    stats: Dict[str, ModelStats] = {}
    resolves: Dict[str, str] = {}
    present: Optional[set] = None
    rejected: set = set()
    if db is not None:
        stats = {s.model: s for s in db.model_stats(now - HEALTH_WINDOW)}
        rejected = db.models_not_found(now - HEALTH_WINDOW)
        resolves = db.resolved_versions(now - HEALTH_WINDOW)
        catalog = db.catalog()
        if catalog:
            fetched = max(m.last_seen_at for m in catalog)
            present = {m.name for m in catalog if m.last_seen_at >= fetched - timedelta(minutes=1)}

    def entry(model: str, role: str) -> PlanEntry:
        return PlanEntry(model, role, "try", expected_ms(stats.get(model)), resolves.get(model), stats.get(model))

    first = entry(configured, "configured")
    if configured in rejected:
        first.note = "Gemini answered 404: not available to this key"
    elif present is not None and configured not in present:
        first.note = "not in Gemini's model list any more"
    fallbacks = sorted(
        (entry(m, "fallback") for m in dict.fromkeys(pool) if m != configured),
        key=lambda e: e.expected_ms,  # stable: models with the same cost keep the list's order
    )
    served = {first.resolves_to or configured}
    for e in fallbacks:
        target = e.resolves_to or e.model
        if e.model in rejected:
            e.status, e.note = "missing", "Gemini answered 404: not available to this key"
        elif present is not None and e.model not in present:
            e.status, e.note = "missing", "not in Gemini's model list any more"
        elif target in served:
            e.status, e.note = "duplicate", f"points at {target}, which is already tried"
        else:
            served.add(target)
    extra = [entry(m, "provider") for m in providers]
    for e in extra:
        e.resolves_to = None  # its modelVersion is the provider's own name, not a Gemini alias
    return [first] + [e for e in fallbacks if e.status == "try"] + extra + [e for e in fallbacks if e.status != "try"]


def try_order(configured: str, pool: List[str], db: Optional[Database]) -> List[str]:
    """The Gemini models to try, in order. Providers are left out: _call_gemini asks them itself."""
    return [e.model for e in fallback_plan(configured, pool, db)
            if e.role == "configured" or (e.role == "fallback" and e.status == "try")]


# ---- report for the Settings page ----------------------------------------------------------

def catalog_report(configured: str, pool: List[str], db: Optional[Database],
                   providers: Sequence[str] = ()) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    catalog = db.catalog() if db is not None else []
    fetched = max((m.last_seen_at for m in catalog), default=None)
    first_fetch = min((m.first_seen_at for m in catalog), default=None)
    by_name = {m.name: m for m in catalog}
    plan = fallback_plan(configured, pool, db, now, providers)
    resolves = {e.model: e.resolves_to for e in plan}
    if db is not None:
        resolves = {**db.resolved_versions(now - HEALTH_WINDOW), **{k: v for k, v in resolves.items() if v}}

    def is_new(m) -> bool:
        # Everything is "first seen" on the first fetch; only later additions count as new
        return (first_fetch is not None and m.first_seen_at > first_fetch + timedelta(minutes=1)
                and now - m.first_seen_at < timedelta(days=NEW_MODEL_DAYS))

    order = []
    for e in plan:
        st = e.stats
        m = by_name.get(e.model)
        order.append({
            "model": e.model,
            "displayName": m.display_name if m else "",
            "role": e.role,
            "status": e.status,
            "note": e.note,
            "resolvesTo": e.resolves_to if e.resolves_to and e.resolves_to != e.model else None,
            "expectedMs": round(e.expected_ms),
            "calls": st.calls if st else 0,
            "ok": st.ok if st else 0,
            "successRate": st.success_rate if st else None,
            "medianMs": st.median_ms if st else None,
        })
    in_use = {configured, *pool}
    rejected = db.models_not_found(now - HEALTH_WINDOW) if db is not None else set()
    candidates = [
        {
            "model": m.name,
            "displayName": m.display_name,
            "version": m.version,
            "isNew": is_new(m),
            "firstSeen": m.first_seen_at.isoformat(),
            "resolvesTo": resolves.get(m.name) if resolves.get(m.name) != m.name else None,
        }
        for m in catalog
        if is_text_flash(m.name) and m.name not in in_use and m.name not in rejected and fetched and m.last_seen_at >= fetched - timedelta(minutes=1)
    ]
    candidates.sort(key=lambda c: (not c["isNew"], c["model"]))
    return {
        "fetchedAt": fetched.isoformat() if fetched else None,
        "stale": fetched is None or now - fetched > CATALOG_MAX_AGE,
        "maxAgeDays": CATALOG_MAX_AGE.days,
        "windowDays": HEALTH_WINDOW.days,
        "order": order,
        "candidates": candidates,
    }
