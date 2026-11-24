"""Gemini's model list, alias tracking and the fallback order (model_catalog.py)."""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import model_catalog
from db import Database
from model_catalog import catalog_report, expected_ms, fallback_plan, is_text_flash, refresh_catalog, try_order

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
POOL = ["gemini-3-flash-preview", "gemini-3.6-flash", "gemini-flash-lite-latest", "gemini-flash-latest"]


@pytest.fixture
def database(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.migrate()
    return d


@pytest.fixture(autouse=True)
def _forget_failed_refreshes():
    model_catalog._last_failure = 0.0
    yield
    model_catalog._last_failure = 0.0


def calls(db, model, outcome, n, latency_ms, version=None, minutes_ago=60):
    for i in range(n):
        db.record_call(started_at=NOW - timedelta(minutes=minutes_ago, seconds=i), model=model, outcome=outcome,
                       http_status=200 if outcome == "ok" else 503, latency_ms=latency_ms, model_version=version)


def catalog_entry(name, display=""):
    return {"name": name, "display_name": display or name, "version": "1", "output_token_limit": 65536, "thinking": True}


def test_text_flash_filter():
    for name in ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-flash-latest", "gemini-flash-lite-latest",
                 "gemini-3-flash-preview", "gemini-3.1-flash-lite-preview", "gemini-2.5-flash"]:
        assert is_text_flash(name), name
    for name in ["gemini-3.8-flash-tts", "gemini-3.1-flash-image", "gemini-3.1-flash-lite-image", "gemini-2.5-pro",
                 "gemini-omni-1.2-flash", "gemini-3.1-pro-preview-customtools", "gemma-4-31b-it"]:
        assert not is_text_flash(name), name


def test_without_history_the_configured_order_is_kept(database):
    assert try_order("gemini-flash-lite-latest", POOL, database) == [
        "gemini-flash-lite-latest", "gemini-3-flash-preview", "gemini-3.6-flash", "gemini-flash-latest",
    ]
    assert try_order("x", POOL, None) == ["x", *POOL]


def test_expected_time_counts_failures():
    from db import ModelStats

    assert expected_ms(None) == model_catalog.PRIOR_MS
    flaky = ModelStats("m", calls=10, ok=5, ms_ok=5 * 5000, ms_lost=5 * 25000)
    steady = ModelStats("m", calls=10, ok=10, ms_ok=10 * 9000)
    assert expected_ms(steady) < expected_ms(flaky)


def test_fallbacks_are_ranked_by_last_weeks_history(database):
    calls(database, "gemini-3.6-flash", "timeout", 6, 25000)
    calls(database, "gemini-3.6-flash", "ok", 2, 16000)
    calls(database, "gemini-flash-lite-latest", "ok", 10, 5000)
    calls(database, "gemini-3-flash-preview", "ok", 10, 13000)
    # Today's real mix for the alias: instant 503s plus 25s timeouts, and never an answer
    calls(database, "gemini-flash-latest", "overloaded", 20, 500)
    calls(database, "gemini-flash-latest", "timeout", 7, 25000)
    # A month-old disaster no longer counts against the preview model
    calls(database, "gemini-3-flash-preview", "timeout", 50, 25000, minutes_ago=60 * 24 * 30)

    order = [e.model for e in fallback_plan("gemini-3.1-flash-lite", POOL, database, NOW)]
    assert order == ["gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-3-flash-preview",
                     "gemini-3.6-flash", "gemini-flash-latest"]


def test_names_pointing_at_a_model_already_tried_are_skipped(database):
    calls(database, "gemini-flash-lite-latest", "ok", 3, 2000, version="gemini-3.5-flash-lite")
    calls(database, "gemini-3.5-flash-lite", "ok", 3, 1500, version="gemini-3.5-flash-lite")
    pool = ["gemini-3.5-flash-lite", "gemini-3-flash-preview"]

    plan = {e.model: e for e in fallback_plan("gemini-flash-lite-latest", pool, database, NOW)}
    assert plan["gemini-3.5-flash-lite"].status == "duplicate"
    assert try_order("gemini-flash-lite-latest", pool, database) == ["gemini-flash-lite-latest", "gemini-3-flash-preview"]
    # Between two fallbacks, the quicker one is kept
    plan = {e.model: e for e in fallback_plan("gemini-3-flash-preview", ["gemini-flash-lite-latest", "gemini-3.5-flash-lite"], database, NOW)}
    assert (plan["gemini-3.5-flash-lite"].status, plan["gemini-flash-lite-latest"].status) == ("try", "duplicate")


def test_models_missing_from_the_list_are_skipped(database):
    database.save_catalog([catalog_entry(m) for m in ["gemini-3-flash-preview", "gemini-old-flash"]], NOW - timedelta(days=10))
    database.save_catalog([catalog_entry("gemini-3-flash-preview")], NOW)  # gemini-old-flash is gone

    plan = fallback_plan("gemini-old-flash", ["gemini-3-flash-preview", "gemini-old-flash", "gemini-never-listed"], database, NOW)
    by_model = {e.model: e for e in plan}
    assert [e.model for e in plan if e.status == "try"] == ["gemini-old-flash", "gemini-3-flash-preview"]
    assert by_model["gemini-never-listed"].status == "missing"
    # The configured model is still tried (the user picked it), with a note
    assert "not in Gemini's model list" in by_model["gemini-old-flash"].note


def test_replies_and_quota_errors_record_the_model_that_served_them():
    from gemini_client import GeminiClient, model_health

    quota = MagicMock(status_code=429, text="quota")
    quota.json.return_value = {"error": {
        "message": "Quota exceeded for metric: generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash",
        "details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "20"}]}],
    }}
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"modelVersion": "gemini-3.5-flash-lite",
                            "candidates": [{"content": {"parts": [{"text": "hi"}]}}]}
    client = GeminiClient()
    client.config.update(apiKey="k", model="gemini-flash-latest", fallbackModels=["gemini-flash-lite-latest"])
    with patch("httpx.AsyncClient.post", side_effect=[quota, ok]):
        assert asyncio.run(client._call_gemini([{"parts": [{"text": "x"}]}])) == "hi"

    assert model_health.db.resolved_versions() == {
        "gemini-flash-latest": "gemini-3.8-flash", "gemini-flash-lite-latest": "gemini-3.5-flash-lite",
    }


def _list_response(names, token=None):
    resp = MagicMock(status_code=200)
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "models": [{"name": f"models/{n}", "displayName": n, "supportedGenerationMethods": ["generateContent"]} for n in names]
        + [{"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]}],
        **({"nextPageToken": token} if token else {}),
    }
    return resp


def test_refresh_fetches_every_page_only_when_stale(database):
    pages = [_list_response(["gemini-3.8-flash"], token="p2"), _list_response(["gemini-3-flash-preview"])]
    with patch("httpx.AsyncClient.get", side_effect=pages) as get:
        assert asyncio.run(refresh_catalog("k", database)) is True
    assert get.call_count == 2
    assert get.call_args.kwargs["params"]["pageToken"] == "p2"
    assert "k" not in str(get.call_args.args)  # key goes in a header, never the URL
    assert [m.name for m in database.catalog()] == ["gemini-3-flash-preview", "gemini-3.8-flash"]

    with patch("httpx.AsyncClient.get") as get:
        assert asyncio.run(refresh_catalog("k", database)) is False  # fresh: no request
        get.assert_not_called()


def test_failed_refresh_keeps_the_old_list_and_backs_off(database):
    database.save_catalog([catalog_entry("gemini-3-flash-preview")], NOW - timedelta(days=30))
    with patch("httpx.AsyncClient.get", side_effect=Exception("offline")) as get:
        assert asyncio.run(refresh_catalog("k", database)) is False
        assert asyncio.run(refresh_catalog("k", database)) is False
    assert get.call_count == 1  # the second call waits for CATALOG_RETRY_AFTER
    assert [m.name for m in database.catalog()] == ["gemini-3-flash-preview"]

    with patch("httpx.AsyncClient.get", return_value=_list_response([])):
        assert asyncio.run(refresh_catalog("k", database, force=True)) is False  # an empty list isn't saved
    assert [m.name for m in database.catalog()] == ["gemini-3-flash-preview"]


def test_report_flags_models_added_after_the_first_fetch(database):
    now = datetime.now(timezone.utc)
    first = [catalog_entry(m) for m in ["gemini-3-flash-preview", "gemini-3.5-flash", "gemini-3.8-flash-tts"]]
    database.save_catalog(first, now - timedelta(days=8))
    database.save_catalog(first + [catalog_entry("gemini-3.9-flash", "Gemini 3.9 Flash")], now)

    report = catalog_report("gemini-3-flash-preview", ["gemini-3.5-flash"], database)
    assert report["stale"] is False and report["fetchedAt"]
    assert [(c["model"], c["isNew"]) for c in report["candidates"]] == [("gemini-3.9-flash", True)]
    assert [(o["model"], o["role"]) for o in report["order"]] == [
        ("gemini-3-flash-preview", "configured"), ("gemini-3.5-flash", "fallback"),
    ]


def test_models_endpoints_add_and_remove_fallbacks():
    from fastapi.testclient import TestClient
    import app as app_module

    path = app_module.gemini.config_path
    saved = open(path).read() if os.path.exists(path) else None
    try:
        client = TestClient(app_module.app)
        body = client.get("/api/gemini/models").json()
        assert body["fetchedAt"] is None and body["order"][0]["role"] == "configured"

        body = client.post("/api/gemini/fallbacks", json={"model": "gemini-3.9-flash", "include": True}).json()
        assert "gemini-3.9-flash" in [o["model"] for o in body["order"]]
        assert "gemini-3.9-flash" in json.load(open(path))["fallbackModels"]

        body = client.post("/api/gemini/fallbacks", json={"model": "gemini-3.9-flash", "include": False}).json()
        assert "gemini-3.9-flash" not in [o["model"] for o in body["order"]]

        assert client.post("/api/gemini/fallbacks", json={"model": "../etc", "include": True}).status_code == 400
    finally:
        if saved is None:
            os.path.exists(path) and os.remove(path)
        else:
            open(path, "w").write(saved)
        app_module.gemini.config = app_module.gemini.load_config()
