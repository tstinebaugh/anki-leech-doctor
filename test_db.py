"""The SQLite call log (db.py): migrations, queries, and how the Gemini client uses it."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import inspect

from db import Database, GeminiCall


@pytest.fixture
def database(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.migrate()
    return d


def test_migrations_create_the_schema_and_match_the_models(database):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from db import Base

    assert {"gemini_calls", "model_cooldowns", "model_quotas", "alembic_version"} <= set(
        inspect(database.engine).get_table_names()
    )
    with database.engine.connect() as conn:
        # Fails when a model changes without a migration (same check as `alembic check`)
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []


def test_migrations_downgrade_and_upgrade_again(database):
    from alembic import command
    from alembic.config import Config
    import os

    cfg = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
    with database.engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")
    assert "gemini_calls" not in inspect(database.engine).get_table_names()
    database.migrate()
    assert "gemini_calls" in inspect(database.engine).get_table_names()


def test_datetimes_are_stored_as_utc(database):
    tokyo = timezone(timedelta(hours=9))
    database.record_call(started_at=datetime(2026, 11, 24, 9, 0, tzinfo=tokyo), model="m", task="t",
                         outcome="ok", http_status=200, latency_ms=100)
    call = database.recent_calls(1)[0]
    assert call.started_at == datetime(2026, 11, 24, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(Exception):
        database.record_call(started_at=datetime(2026, 11, 24), model="m", outcome="ok", latency_ms=1)


def test_usage_counts_only_today_and_only_answered_requests(database):
    day_start = datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc)  # midnight Pacific
    def add(minutes, status, outcome, ms, model="gemini-flash-latest"):
        database.record_call(started_at=day_start + timedelta(minutes=minutes), model=model, task="mnemonic",
                             outcome=outcome, http_status=status, latency_ms=ms,
                             prompt_tokens=10, output_tokens=5, thought_tokens=2)
    add(-1, 200, "ok", 900)          # yesterday's quota day
    add(1, 200, "ok", 1000)
    add(2, 200, "ok", 3000)
    add(3, 503, "overloaded", 15000)
    add(4, 429, "quota", 200)

    assert database.answered_since(day_start) == {"gemini-flash-latest": 2}
    (u,) = database.usage_since(day_start)
    assert (u.requests, u.answered, u.failed, u.median_ms) == (4, 2, 2, 2000)
    assert u.tokens == 4 * 17


def test_call_log_records_every_attempt():
    from gemini_client import GeminiClient, model_health

    client = GeminiClient()
    client.config.update(apiKey="k", model="gemini-flash-latest")
    busy = MagicMock(status_code=503, text="busy")
    busy.json.return_value = {"error": {"message": "high demand"}}
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"candidates": [{"content": {"parts": [{"text": "hi"}]}}],
                            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3, "thoughtsTokenCount": 40}}
    import asyncio
    with patch("httpx.AsyncClient.post", side_effect=[busy, ok]):
        assert asyncio.run(client._call_gemini([{"parts": [{"text": "x"}]}], task="mnemonic")) == "hi"

    second, first = model_health.db.recent_calls(2)
    assert (first.model, first.outcome, first.http_status, first.task) == ("gemini-flash-latest", "overloaded", 503, "mnemonic")
    assert (second.model, second.outcome, second.task) == ("gemini-3-flash-preview", "ok", "mnemonic")
    assert (second.prompt_tokens, second.output_tokens, second.thought_tokens) == (12, 3, 40)


def test_quota_limit_is_learned_and_models_at_it_are_tried_last():
    from gemini_client import FALLBACK_MODELS, GeminiClient, model_health, quota_day_start
    import asyncio

    quota = MagicMock(status_code=429, text="quota")
    quota.json.return_value = {"error": {"message": "quota", "details": [
        {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "20"}]},
        {"retryDelay": "60s"},
    ]}}
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
    client = GeminiClient()
    client.config.update(apiKey="k", model="gemini-flash-latest")
    with patch("httpx.AsyncClient.post", side_effect=[quota, ok]):
        asyncio.run(client._call_gemini([{"parts": [{"text": "x"}]}]))
    assert model_health.db.daily_limits() == {"gemini-flash-latest": 20}

    # The preview model has used its 20 today by our count (it never got a 429)
    model_health.db.set_daily_limit("gemini-3-flash-preview", 20)
    for i in range(20):
        model_health.db.record_call(started_at=quota_day_start() + timedelta(seconds=i + 1), model="gemini-3-flash-preview",
                                    outcome="ok", http_status=200, latency_ms=1000)
    with patch("httpx.AsyncClient.post", return_value=ok) as post:
        asyncio.run(client._call_gemini([{"parts": [{"text": "x"}]}]))
    first_tried = post.call_args.args[0].split("/models/")[1].split(":")[0]
    assert first_tried == FALLBACK_MODELS[1]  # skips flash-latest (blocked) and preview (at its limit)


def test_usage_endpoint_reports_today(database):
    from fastapi.testclient import TestClient
    import app as app_module
    from gemini_client import model_health, quota_day_start

    model_health.db.record_call(started_at=quota_day_start() + timedelta(minutes=5), model="gemini-flash-latest",
                                task="mnemonic", outcome="ok", http_status=200, latency_ms=1234)
    model_health.db.set_daily_limit("gemini-flash-latest", 20)
    model_health.failed("gemini-3-flash-preview", retry_after=3600, hard=True, reason="daily quota used up")

    body = TestClient(app_module.app).get("/api/gemini/usage").json()
    rows = {r["model"]: r for r in body["models"]}
    assert rows["gemini-flash-latest"]["answered"] == 1 and rows["gemini-flash-latest"]["dailyLimit"] == 20
    assert rows["gemini-flash-latest"]["medianMs"] == 1234
    assert rows["gemini-3-flash-preview"]["status"] == "blocked"
    assert "daily quota used up" in rows["gemini-3-flash-preview"]["statusDetail"]
    assert body["resetsIn"].startswith("until")


def test_gemini_call_rows_have_no_secrets(database):
    database.record_call(model="m", outcome="error", latency_ms=1, error="x" * 2000)
    call = database.recent_calls(1)[0]
    assert isinstance(call, GeminiCall) and len(call.error) == 500


def test_legacy_cooldown_file_is_imported_once(database, tmp_path):
    import json
    import time
    from db import _import_legacy_cooldowns
    legacy = tmp_path / ".model_health.json"
    legacy.write_text(json.dumps({
        "gemini-flash-latest": {"until": time.time() + 3600, "hard": True, "reason": "daily quota used up"},
        "gemini-3-flash-preview": {"until": time.time() - 10, "hard": False, "reason": "expired"},
    }))
    _import_legacy_cooldowns(database, str(legacy))
    assert [c.model for c in database.active_cooldowns()] == ["gemini-flash-latest"]
    assert not legacy.exists()


def _seed(database, rows, now=None):
    """rows: (model, outcome, latency_ms, hours_ago)"""
    now = now or datetime.now(timezone.utc)
    for model, outcome, ms, hours_ago in rows:
        database.record_call(
            started_at=now - timedelta(hours=hours_ago), model=model, task="mnemonic", outcome=outcome,
            http_status={"ok": 200, "overloaded": 503, "quota": 429, "timeout": None}.get(outcome), latency_ms=ms,
            prompt_tokens=100 if outcome == "ok" else None, output_tokens=50 if outcome == "ok" else None,
        )


def test_model_stats_counts_outcomes_and_latency(database):
    _seed(database, [
        ("fast", "ok", 1000, 1), ("fast", "ok", 2000, 1), ("fast", "ok", 3000, 1), ("fast", "ok", 10000, 1),
        ("fast", "overloaded", 4000, 1), ("fast", "timeout", 25000, 1), ("fast", "quota", 300, 1),
        ("fast", "ok", 500, 24 * 10),  # ten days ago
        ("dead", "overloaded", 15000, 2),
    ])
    since = datetime.now(timezone.utc) - timedelta(days=7)
    stats = {s.model: s for s in database.model_stats(since)}
    fast = stats["fast"]
    assert (fast.calls, fast.ok, fast.overloaded, fast.timeouts, fast.quota, fast.other_failures) == (7, 4, 1, 1, 1, 0)
    assert (fast.median_ms, fast.p90_ms, fast.fastest_ms) == (2500, 10000, 1000)
    assert fast.ms_lost == 4000 + 25000 + 300
    assert fast.avg_tokens == 150
    assert stats["dead"].median_ms is None and stats["dead"].success_rate == 0
    # All time includes the old call
    assert {s.model: s.calls for s in database.model_stats()}["fast"] == 8


def test_performance_report_ranks_fastest_reliable_model():
    from gemini_client import model_health, performance_report
    _seed(model_health.db, [
        # quickest, but only answers half the time: not "reliable"
        ("flaky", "ok", 800, 1), ("flaky", "ok", 900, 1), ("flaky", "ok", 700, 1),
        ("flaky", "overloaded", 15000, 1), ("flaky", "overloaded", 15000, 1), ("flaky", "timeout", 25000, 1),
        ("steady", "ok", 3000, 1), ("steady", "ok", 3500, 1), ("steady", "ok", 4000, 1), ("steady", "ok", 4500, 1),
        ("slow", "ok", 9000, 1), ("slow", "ok", 9500, 1), ("slow", "ok", 9900, 1),
        ("broken", "overloaded", 5000, 1),
    ])
    report = performance_report("day")
    assert [m["model"] for m in report["models"]] == ["flaky", "steady", "slow", "broken"]
    assert report["fastestReliable"] == "steady"
    assert report["totals"]["calls"] == 14 and report["totals"]["msLost"] == 15000 * 2 + 25000 + 5000
    assert report["recentFailures"][0]["model"] == "broken"


def test_stats_endpoint_validates_the_range():
    from fastapi.testclient import TestClient
    import app as app_module
    client = TestClient(app_module.app)
    assert client.get("/api/gemini/stats?range=all").status_code == 200
    bad = client.get("/api/gemini/stats?range=year")
    assert bad.status_code == 400 and "day, week, month, all" in bad.json()["detail"]
