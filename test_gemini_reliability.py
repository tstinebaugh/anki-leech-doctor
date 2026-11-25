"""Gemini call behaviour when models are overloaded, slow or picky about settings."""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from gemini_client import FALLBACK_MODELS, GeminiBusyError, GeminiClient, GeminiQuotaError, model_health, thinking_config_for

HELLO = [{"parts": [{"text": "hello"}]}]


def _client(model="gemini-flash-latest"):
    c = GeminiClient()
    c.config["apiKey"] = "fake-api-key"
    c.config["model"] = model
    return c


def _resp(status, body):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    r.text = str(body)
    return r


def _ok(text="ok"):
    return _resp(200, {"candidates": [{"content": {"parts": [{"text": text}]}}]})


def _err(status, message, details=None):
    return _resp(status, {"error": {"code": status, "message": message, "details": details or []}})


def _models(mock_post):
    return [call.args[0].split("/models/")[1].split(":")[0] for call in mock_post.call_args_list]


@pytest.mark.anyio
async def test_overloaded_model_is_skipped_on_the_next_call():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = [_err(503, "high demand"), _ok("first")]
        assert await client._call_gemini(HELLO) == "first"
        assert _models(mock_post) == ["gemini-flash-latest", "gemini-3-flash-preview"]

        mock_post.reset_mock()
        mock_post.side_effect = [_ok("second")]
        assert await client._call_gemini(HELLO) == "second"
        # Straight to the healthy fallback, no second wait on the overloaded model
        assert _models(mock_post) == ["gemini-3-flash-preview"]
    assert 55 < model_health.cooldown_left("gemini-flash-latest") <= 60


@pytest.mark.anyio
async def test_timed_out_model_cools_down_and_backs_off():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = [httpx.ReadTimeout("slow"), _ok()]
        await client._call_gemini(HELLO)
    first = model_health.cooldown_left("gemini-flash-latest")
    model_health.failed("gemini-flash-latest")
    assert first <= 60 and model_health.cooldown_left("gemini-flash-latest") > 110  # doubled


@pytest.mark.anyio
async def test_success_clears_the_cooldown():
    model_health.failed("gemini-flash-latest")
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        # Every healthy model fails, so the cooling one is still tried as a last resort
        mock_post.side_effect = [_err(503, "busy")] * (len(FALLBACK_MODELS) - 1) + [_ok("back")]
        assert await client._call_gemini(HELLO) == "back"
        assert _models(mock_post)[-1] == "gemini-flash-latest"
    assert model_health.cooldown_left("gemini-flash-latest") == 0


@pytest.mark.anyio
async def test_rate_limit_uses_googles_retry_delay():
    client = _client()
    retry = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17s"}]
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = [_err(429, "quota", retry), _ok()]
        await client._call_gemini(HELLO)
    assert 15 < model_health.cooldown_left("gemini-flash-latest") <= 17


@pytest.mark.anyio
async def test_requests_configured_thinking_level():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _ok()
        await client._call_gemini(HELLO, system_instruction="be brief")
    payload = mock_post.call_args.kwargs["json"]
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "medium"}
    assert payload["systemInstruction"]["parts"][0]["text"] == "be brief"


def test_thinking_config_per_model_family():
    assert thinking_config_for("gemini-3.8-flash", "low") == {"thinkingLevel": "low"}
    assert thinking_config_for("gemini-2.5-flash", "low") == {"thinkingBudget": 0}
    assert thinking_config_for("gemini-2.5-pro", "low") is None  # can't turn thinking off


@pytest.mark.anyio
async def test_rejected_thinking_setting_retries_with_model_default():
    client = _client()
    client.config["thinkingLevel"] = "minimal"
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = [_err(400, "Thinking level MINIMAL is not supported for this model."), _ok("fine")]
        assert await client._call_gemini(HELLO) == "fine"
        assert _models(mock_post) == ["gemini-flash-latest", "gemini-flash-latest"]
        assert "thinkingConfig" not in mock_post.call_args.kwargs["json"]["generationConfig"]

        # Remembered: the next call doesn't send it again
        mock_post.reset_mock()
        mock_post.side_effect = [_ok()]
        await client._call_gemini(HELLO)
        assert "thinkingConfig" not in mock_post.call_args.kwargs["json"]["generationConfig"]


@pytest.mark.anyio
async def test_no_connection_fails_fast_without_trying_other_models():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = httpx.ConnectError("no route")
        with pytest.raises(RuntimeError, match="internet connection"):
            await client._call_gemini(HELLO)
        assert mock_post.call_count == 1
    assert model_health.cooldown_left("gemini-flash-latest") == 0


@pytest.mark.anyio
async def test_bad_key_fails_fast():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _err(403, "API key not valid")
        with pytest.raises(RuntimeError, match="API key"):
            await client._call_gemini(HELLO)
        assert mock_post.call_count == 1


@pytest.mark.anyio
async def test_truncated_reply_is_reported_and_falls_back():
    client = _client()
    cut = _resp(200, {"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]})
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = [cut, _ok("whole")]
        assert await client._call_gemini(HELLO) == "whole"


@pytest.mark.anyio
async def test_thought_parts_are_not_returned_as_text():
    client = _client()
    body = {"candidates": [{"content": {"parts": [{"text": "pondering", "thought": True}, {"text": "answer"}]}}]}
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _resp(200, body)
        assert await client._call_gemini(HELLO) == "answer"


DAILY_QUOTA = [
    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
        "description": "Generate content requests per day limit exceeded on Free Tier.",
        "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
    }]},
    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "79789s"},
]


@pytest.mark.anyio
async def test_used_up_daily_quota_blocks_the_model_until_reset():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = [_err(429, "You exceeded your current quota", DAILY_QUOTA), _ok()]
        await client._call_gemini(HELLO)
        # Blocked for the ~22h Google reported, not the 10-minute overload cap
        assert 79780 < model_health.cooldown_left("gemini-flash-latest") <= 79789
        assert model_health.is_blocked("gemini-flash-latest")

        mock_post.reset_mock()
        # Even when every other model fails, the blocked one is not asked again
        mock_post.side_effect = [_err(503, "busy")] * (len(FALLBACK_MODELS) - 1)
        with pytest.raises(GeminiBusyError) as exc:
            await client._call_gemini(HELLO)
        assert "gemini-flash-latest" not in _models(mock_post)
        assert "daily quota used up" in str(exc.value)


@pytest.mark.anyio
async def test_daily_quota_without_retry_delay_waits_for_pacific_midnight():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = [_err(429, "quota", DAILY_QUOTA[:1]), _ok()]
        await client._call_gemini(HELLO)
    left = model_health.cooldown_left("gemini-flash-latest")
    assert 60 <= left <= 24 * 3600 and model_health.is_blocked("gemini-flash-latest")


def test_quota_reset_is_midnight_pacific():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from gemini_client import seconds_until_quota_reset
    eleven_pm = datetime(2026, 11, 21, 23, 0, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()
    assert seconds_until_quota_reset(eleven_pm) == 3600


@pytest.mark.anyio
async def test_all_models_blocked_fails_without_any_request():
    for m in ["gemini-flash-latest", *FALLBACK_MODELS]:
        model_health.failed(m, retry_after=3600, hard=True, reason="daily quota used up")
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        with pytest.raises(GeminiQuotaError, match="out of quota") as exc:
            await client._call_gemini(HELLO)
        assert mock_post.call_count == 0
    assert "can be used again until" in str(exc.value)


def _fresh_db(tmp_path):
    from db import Database
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.migrate()
    return database


def test_cooldowns_survive_a_restart(tmp_path):
    from gemini_client import ModelHealth
    database = _fresh_db(tmp_path)
    first = ModelHealth(database)
    first.failed("gemini-flash-latest", retry_after=3600, hard=True, reason="daily quota used up")
    first.failed("gemini-3-flash-preview", retry_after=5, reason="rate limited")

    second = ModelHealth(database)  # e.g. after uvicorn --reload: nothing in memory
    assert second.is_blocked("gemini-flash-latest")
    assert second.reason("gemini-flash-latest") == "daily quota used up"
    assert 3590 < second.cooldown_left("gemini-flash-latest") <= 3600

    second.succeeded("gemini-flash-latest")
    assert not ModelHealth(database).is_blocked("gemini-flash-latest")


def test_expired_cooldowns_are_ignored(tmp_path):
    from datetime import datetime, timedelta, timezone
    from gemini_client import ModelHealth
    database = _fresh_db(tmp_path)
    database.save_cooldown("gemini-flash-latest", until=datetime.now(timezone.utc) - timedelta(seconds=1),
                           hard=True, reason="old", strikes=1)
    health = ModelHealth(database)
    assert not health.cooldown_left("gemini-flash-latest")
    assert health.order(["gemini-flash-latest"]) == (["gemini-flash-latest"], [])


@pytest.mark.anyio
async def test_overloaded_everywhere_is_reported_as_busy():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _err(503, "high demand")
        with pytest.raises(GeminiBusyError) as exc:
            await client._call_gemini(HELLO)
    assert exc.value.retry_after > 0


@pytest.mark.anyio
async def test_quota_plus_overload_is_busy_and_retry_skips_the_quota_models():
    """The case from the logs: two models out of daily quota, the rest overloaded."""
    client = _client()
    quota = _err(429, "You exceeded your current quota", DAILY_QUOTA)
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = [quota, quota] + [_err(503, "high demand")] * (len(FALLBACK_MODELS) - 1)
        with pytest.raises(GeminiBusyError):
            await client._call_gemini(HELLO)
        blocked = _models(mock_post)[:2]

        # The retry the frontend makes a few seconds later only asks the overloaded ones
        mock_post.reset_mock()
        mock_post.side_effect = [_ok("finally")]
        assert await client._call_gemini(HELLO) == "finally"
        assert _models(mock_post)[0] not in blocked


@pytest.mark.anyio
async def test_other_failures_are_not_retryable():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _err(400, "Invalid argument")
        with pytest.raises(RuntimeError) as exc:
            await client._call_gemini(HELLO)
    assert not isinstance(exc.value, GeminiBusyError)


def test_busy_and_quota_errors_map_to_retryable_http_statuses():
    from fastapi.testclient import TestClient
    import app as app_module

    client = TestClient(app_module.app)
    payload = {"vocabKanji": "避難", "vocabFurigana": "ひなん", "vocabDef": "evacuation", "kanjiDetails": {}, "confusableCards": []}
    with patch.object(app_module.gemini, "generate_mnemonic", side_effect=GeminiBusyError("all busy", retry_after=7)):
        res = client.post("/api/generate-mnemonic", json=payload)
    assert res.status_code == 503 and res.headers["Retry-After"] == "7"

    with patch.object(app_module.gemini, "generate_mnemonic", side_effect=GeminiQuotaError("out of quota until 17:00", 0)):
        res = client.post("/api/generate-mnemonic", json=payload)
    assert res.status_code == 429 and "17:00" in res.json()["detail"]


def test_busy_errors_are_logged_without_a_traceback(caplog):
    """'All models busy' is expected and retried by the frontend; only real errors get a traceback."""
    import logging
    from fastapi.testclient import TestClient
    import app as app_module

    client = TestClient(app_module.app)
    payload = {"vocabKanji": "避難", "vocabFurigana": "ひなん", "vocabDef": "evacuation", "kanjiDetails": {}, "confusableCards": []}
    with caplog.at_level(logging.WARNING, logger="app"):
        with patch.object(app_module.gemini, "generate_mnemonic", side_effect=GeminiBusyError("all busy", retry_after=7)):
            client.post("/api/generate-mnemonic", json=payload)
        with patch.object(app_module.gemini, "generate_mnemonic", side_effect=GeminiQuotaError("out of quota", 0)):
            client.post("/api/generate-mnemonic", json=payload)
    assert [(r.levelname, r.exc_info) for r in caplog.records] == [("WARNING", None), ("WARNING", None)]

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app"):
        with patch.object(app_module.gemini, "generate_mnemonic", side_effect=RuntimeError("boom")):
            assert client.post("/api/generate-mnemonic", json=payload).status_code == 500
    assert [r.levelname for r in caplog.records] == ["ERROR"] and caplog.records[0].exc_info
