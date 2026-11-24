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

from sqlalchemy import DateTime, Index, String, Text, TypeDecorator, create_engine, delete, event, select
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


@dataclass
class ModelUsage:
    model: str
    requests: int = 0       # attempts made
    answered: int = 0       # HTTP 200s, which are what Google counts against the quota
    failed: int = 0
    median_ms: Optional[int] = None
    tokens: int = 0
    daily_limit: Optional[int] = None


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

    def recent_calls(self, limit: int = 20) -> List[GeminiCall]:
        with self.Session() as s:
            return list(s.execute(select(GeminiCall).order_by(GeminiCall.id.desc()).limit(limit)).scalars())

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
            for table in (GeminiCall, ModelCooldown, ModelQuota):
                s.execute(delete(table))


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
