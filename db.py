"""Local SQLite storage for Gemini call history, model cooldowns and learned quotas.

SQLAlchemy 2.0 ORM over one SQLite file (LEECH_DOCTOR_DB). The schema is owned by
Alembic (migrations/); Database.migrate() upgrades the file to the latest revision on
startup, so users never run migrations by hand. See docs/design/0002-gemini-call-log.md.

Why a database here: Gemini's free tier allows about 20 requests a day per model, so the
app needs to know what it has used today, what each model's limit is, and which models
are cooling down. That is relational, append-heavy data that outlives a process, and
it is queried by time range, which is what SQLite is good at.
"""
import logging
import os
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import DateTime, Index, String, Text, TypeDecorator, case, create_engine, delete, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

logger = logging.getLogger(__name__)

APP_DIR = os.path.dirname(os.path.abspath(__file__))


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on top of SQLite, which has no timezone type."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: pass a timezone-aware value")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: Optional[datetime], dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class GeminiCall(Base):
    """One request to one Gemini model (a single app action can make several)."""

    __tablename__ = "gemini_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    model: Mapped[str] = mapped_column(String(100))
    task: Mapped[str] = mapped_column(String(50), default="")
    # ok, empty, overloaded, timeout, quota, rate_limited, not_found, error
    outcome: Mapped[str] = mapped_column(String(20))
    http_status: Mapped[Optional[int]]
    latency_ms: Mapped[int]
    prompt_tokens: Mapped[Optional[int]]
    output_tokens: Mapped[Optional[int]]
    thought_tokens: Mapped[Optional[int]]
    error: Mapped[Optional[str]] = mapped_column(Text)
    # The model that actually served the request, when Google says: the reply's modelVersion,
    # or the model named in a quota error. Shows where aliases such as gemini-flash-latest point.
    model_version: Mapped[Optional[str]] = mapped_column(String(100))

    __table_args__ = (
        Index("ix_gemini_calls_started_at", "started_at"),  # usage by day
        Index("ix_gemini_calls_model_started_at", "model", "started_at"),  # quota used per model
    )


class ModelCooldown(Base):
    """A model to avoid until `until`: hard = don't call at all (quota), soft = try last."""

    __tablename__ = "model_cooldowns"

    model: Mapped[str] = mapped_column(String(100), primary_key=True)
    until: Mapped[datetime] = mapped_column(UTCDateTime())
    hard: Mapped[bool] = mapped_column(default=False)
    reason: Mapped[str] = mapped_column(String(200), default="")
    strikes: Mapped[int] = mapped_column(default=0)


class ModelQuota(Base):
    """A model's daily request limit, as reported by Google in its last 429."""

    __tablename__ = "model_quotas"

    model: Mapped[str] = mapped_column(String(100), primary_key=True)
    daily_limit: Mapped[int]
    learned_at: Mapped[datetime] = mapped_column(UTCDateTime())


class GeminiModel(Base):
    """A model from Gemini's model list (GET /v1beta/models) that supports generateContent.

    The list is fetched about once a week (model_catalog.py). A model the latest fetch
    didn't return keeps its old last_seen_at, which is how removed models are spotted."""

    __tablename__ = "gemini_models"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    version: Mapped[Optional[str]] = mapped_column(String(100))
    output_token_limit: Mapped[Optional[int]]
    thinking: Mapped[Optional[bool]]
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime())


@dataclass
class ModelUsage:
    model: str
    requests: int = 0       # attempts made
    answered: int = 0       # HTTP 200s, which are what Google counts against the quota
    failed: int = 0
    median_ms: Optional[int] = None
    tokens: int = 0
    daily_limit: Optional[int] = None


@dataclass
class ModelStats:
    """How one model performed over a time range (see Database.model_stats)."""

    model: str
    calls: int = 0
    ok: int = 0
    overloaded: int = 0     # HTTP 5xx: "high demand"
    timeouts: int = 0       # no answer within the attempt timeout
    quota: int = 0          # 429: daily quota used up or rate limited
    other_failures: int = 0  # empty replies, bad requests, connection errors, ...
    median_ms: Optional[int] = None  # successful replies only
    p90_ms: Optional[int] = None
    fastest_ms: Optional[int] = None
    ms_lost: int = 0        # time spent waiting on attempts that failed
    ms_ok: int = 0          # time spent on attempts that answered
    avg_tokens: Optional[int] = None
    last_used: Optional[datetime] = None

    @property
    def success_rate(self) -> Optional[float]:
        return self.ok / self.calls if self.calls else None


class Database:
    def __init__(self, url: str):
        self.url = url
        self.engine: Engine = create_engine(url)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", _sqlite_pragmas)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def migrate(self) -> None:
        """Brings the database to the latest Alembic revision."""
        from alembic import command
        from alembic.config import Config

        cfg = Config(os.path.join(APP_DIR, "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(APP_DIR, "migrations"))
        with self.engine.begin() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")

    # ---- call log ----------------------------------------------------------------------

    def record_call(self, **fields) -> None:
        fields.setdefault("started_at", utcnow())
        if fields.get("error"):
            fields["error"] = str(fields["error"])[:500]
        with self.Session.begin() as s:
            s.add(GeminiCall(**fields))

    def answered_since(self, since: datetime) -> Dict[str, int]:
        """HTTP 200 replies per model since `since`, i.e. requests used from the quota."""
        with self.Session() as s:
            rows = s.execute(
                select(GeminiCall.model).where(GeminiCall.started_at >= since, GeminiCall.http_status == 200)
            ).scalars()
            counts: Dict[str, int] = {}
            for model in rows:
                counts[model] = counts.get(model, 0) + 1
            return counts

    def usage_since(self, since: datetime) -> List[ModelUsage]:
        with self.Session() as s:
            calls = s.execute(
                select(GeminiCall).where(GeminiCall.started_at >= since).order_by(GeminiCall.started_at)
            ).scalars().all()
            limits = {q.model: q.daily_limit for q in s.execute(select(ModelQuota)).scalars()}
        by_model: Dict[str, ModelUsage] = {}
        latencies: Dict[str, List[int]] = {}
        for c in calls:
            u = by_model.setdefault(c.model, ModelUsage(c.model, daily_limit=limits.get(c.model)))
            u.requests += 1
            if c.http_status == 200:
                u.answered += 1
                latencies.setdefault(c.model, []).append(c.latency_ms)
            if c.outcome != "ok":
                u.failed += 1
            u.tokens += (c.prompt_tokens or 0) + (c.output_tokens or 0) + (c.thought_tokens or 0)
        for model, values in latencies.items():
            by_model[model].median_ms = int(statistics.median(values))
        return list(by_model.values())

    def model_stats(self, since: Optional[datetime] = None) -> List[ModelStats]:
        """Per-model counts by outcome and latency percentiles since `since` (all time if None).

        Counts are aggregated in SQL; percentiles are computed in Python because SQLite
        has no percentile function."""
        c = GeminiCall
        window = [c.started_at >= since] if since else []

        def count(condition):
            return func.sum(case((condition, 1), else_=0))

        tokens = func.coalesce(c.prompt_tokens, 0) + func.coalesce(c.output_tokens, 0) + func.coalesce(c.thought_tokens, 0)
        totals = (
            select(
                c.model,
                func.count(),
                count(c.outcome == "ok"),
                count(c.outcome == "overloaded"),
                count(c.outcome == "timeout"),
                count(c.outcome.in_(("quota", "rate_limited"))),
                func.sum(case((c.outcome != "ok", c.latency_ms), else_=0)),
                func.sum(case((c.outcome == "ok", c.latency_ms), else_=0)),
                func.avg(case((c.outcome == "ok", tokens))),
                func.max(c.started_at),
            )
            .where(*window)
            .group_by(c.model)
        )
        latencies = select(c.model, c.latency_ms).where(c.outcome == "ok", *window)
        with self.Session() as s:
            rows = s.execute(totals).all()
            by_model: Dict[str, List[int]] = {}
            for model, ms in s.execute(latencies):
                by_model.setdefault(model, []).append(ms)

        stats = []
        for model, calls, ok, overloaded, timeouts, quota, ms_lost, ms_ok, avg_tokens, last_used in rows:
            ms = sorted(by_model.get(model, []))
            stats.append(ModelStats(
                model=model, calls=calls, ok=ok, overloaded=overloaded, timeouts=timeouts, quota=quota,
                other_failures=calls - ok - overloaded - timeouts - quota,
                median_ms=int(statistics.median(ms)) if ms else None,
                p90_ms=_percentile(ms, 0.9),
                fastest_ms=ms[0] if ms else None,
                ms_lost=int(ms_lost or 0),
                ms_ok=int(ms_ok or 0),
                avg_tokens=int(avg_tokens) if avg_tokens is not None else None,
                # SQLite's max() returns the stored text, not a datetime
                last_used=_parse_utc(last_used),
            ))
        return stats

    def recent_failures(self, since: Optional[datetime] = None, limit: int = 15) -> List[GeminiCall]:
        query = select(GeminiCall).where(GeminiCall.outcome != "ok")
        if since:
            query = query.where(GeminiCall.started_at >= since)
        with self.Session() as s:
            return list(s.execute(query.order_by(GeminiCall.id.desc()).limit(limit)).scalars())

    def recent_calls(self, limit: int = 20) -> List[GeminiCall]:
        with self.Session() as s:
            return list(s.execute(select(GeminiCall).order_by(GeminiCall.id.desc()).limit(limit)).scalars())

    def resolved_versions(self, since: Optional[datetime] = None) -> Dict[str, str]:
        """The model each requested name was last served by, e.g. {"gemini-flash-latest": "gemini-3.8-flash"}."""
        query = select(GeminiCall.model, GeminiCall.model_version).where(GeminiCall.model_version.is_not(None))
        if since:
            query = query.where(GeminiCall.started_at >= since)
        with self.Session() as s:
            return {model: version for model, version in s.execute(query.order_by(GeminiCall.id))}

    # ---- model catalog -----------------------------------------------------------------

    def save_catalog(self, models: List[Dict], seen_at: Optional[datetime] = None) -> None:
        """Upserts the models from one fetch of Gemini's model list."""
        seen_at = seen_at or utcnow()
        with self.Session.begin() as s:
            known = {m.name: m for m in s.execute(select(GeminiModel)).scalars()}
            for m in models:
                row = known.get(m["name"])
                if row is None:
                    row = GeminiModel(name=m["name"], first_seen_at=seen_at)
                    s.add(row)
                row.display_name = m.get("display_name") or ""
                row.version = m.get("version")
                row.output_token_limit = m.get("output_token_limit")
                row.thinking = m.get("thinking")
                row.last_seen_at = seen_at

    def catalog(self) -> List[GeminiModel]:
        with self.Session() as s:
            return list(s.execute(select(GeminiModel).order_by(GeminiModel.name)).scalars())

    # ---- quotas ------------------------------------------------------------------------

    def set_daily_limit(self, model: str, daily_limit: int) -> None:
        with self.Session.begin() as s:
            s.merge(ModelQuota(model=model, daily_limit=daily_limit, learned_at=utcnow()))

    def daily_limits(self) -> Dict[str, int]:
        with self.Session() as s:
            return {q.model: q.daily_limit for q in s.execute(select(ModelQuota)).scalars()}

    # ---- cooldowns ---------------------------------------------------------------------

    def active_cooldowns(self) -> List[ModelCooldown]:
        with self.Session() as s:
            return list(s.execute(select(ModelCooldown).where(ModelCooldown.until > utcnow())).scalars())

    def save_cooldown(self, model: str, until: datetime, hard: bool, reason: str, strikes: int) -> None:
        with self.Session.begin() as s:
            s.merge(ModelCooldown(model=model, until=until, hard=hard, reason=reason, strikes=strikes))

    def delete_cooldown(self, model: str) -> None:
        with self.Session.begin() as s:
            s.execute(delete(ModelCooldown).where(ModelCooldown.model == model))

    def clear(self) -> None:
        """Empties every table (used by tests)."""
        with self.Session.begin() as s:
            for table in (GeminiCall, ModelCooldown, ModelQuota, GeminiModel):
                s.execute(delete(table))


def _percentile(sorted_values: List[int], q: float) -> Optional[int]:
    """Nearest-rank percentile of an already sorted list."""
    if not sorted_values:
        return None
    rank = max(0, min(len(sorted_values) - 1, int(round(q * len(sorted_values) + 0.5)) - 1))
    return sorted_values[rank]


def _parse_utc(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cur = dbapi_connection.cursor()
    # WAL lets the usage page read while a Gemini call is being logged
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


_database: Optional[Database] = None


def get_database() -> Database:
    """The app's database, created and migrated on first use."""
    global _database
    if _database is None:
        from config_defaults import DB_PATH

        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        _database = Database(f"sqlite:///{DB_PATH}")
        _database.migrate()
        _import_legacy_cooldowns(_database, os.path.join(APP_DIR, ".model_health.json"))
    return _database


def _import_legacy_cooldowns(database: Database, path: str) -> None:
    """Moves cooldowns from .model_health.json (before the database existed) into it."""
    if not os.path.exists(path):
        return
    try:
        import json

        with open(path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        now = utcnow()
        for model, entry in saved.items():
            until = datetime.fromtimestamp(float(entry["until"]), timezone.utc)
            if until > now:
                database.save_cooldown(model, until, bool(entry.get("hard")), str(entry.get("reason", "")), 1)
        os.remove(path)
        logger.info(f"Moved model cooldowns from {path} into the database")
    except Exception as e:
        logger.warning(f"Could not import {path}: {e}")
