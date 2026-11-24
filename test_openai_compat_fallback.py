"""The OpenAI-compatible fallback provider (NVIDIA NIM, OpenRouter, Ollama), asked only after
every Gemini model failed. httpx is mocked: no test touches the network."""
import logging
from datetime import timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

import gemini_client
from gemini_client import (
    FALLBACK_MODELS, GeminiBusyError, GeminiClient, GeminiQuotaError, is_local_url, model_health, to_openai_messages,
)
from model_catalog import fallback_plan, try_order

HELLO = [{"parts": [{"text": "hello"}]}]
NIM = "https://integrate.api.nvidia.com/v1"
NIM_MODEL = "meta/llama-3.3-70b-instruct"
PROVIDER = f"openai:{NIM_MODEL}"
SECRET = "nvapi-super-secret-key-1234"
ALL_GEMINI = list(dict.fromkeys(["gemini-flash-latest", *FALLBACK_MODELS]))


def _client(base_url=NIM, model=NIM_MODEL, key=SECRET):
    c = GeminiClient()
    c.config["apiKey"] = "fake-api-key"
    c.config["model"] = "gemini-flash-latest"
    c.config["openaiCompatBaseUrl"] = base_url
    c.config["openaiCompatModel"] = model
    c.config["openaiCompatApiKey"] = key
    return c


def _resp(status, body, headers=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    r.text = str(body)
    r.headers = httpx.Headers(headers or {})
    return r


def _gemini_ok(text="gemini"):
    return _resp(200, {"candidates": [{"content": {"parts": [{"text": text}]}}]})


def _gemini_busy():
    return _resp(503, {"error": {"code": 503, "message": "high demand"}})


def _chat_ok(text="from the provider", model=NIM_MODEL):
    return _resp(200, {
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
    })


def _chat_err(status, message="nope", headers=None):
    return _resp(status, {"error": {"message": message}}, headers)


def _route(gemini, provider):
    """A post() side effect: Gemini URLs get `gemini`, the provider gets `provider`
    (a response, an exception, or a list of either, consumed in order)."""
    queues = {"gemini": gemini, "provider": provider}

    def post(url, **kwargs):
        key = "provider" if url.endswith("/chat/completions") else "gemini"
        item = queues[key]
        if isinstance(item, list):
            item = item.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    return post


def _targets(mock_post):
    return [
        "provider" if call.args[0].endswith("/chat/completions") else call.args[0].split("/models/")[1].split(":")[0]
        for call in mock_post.call_args_list
    ]


def _provider_call(mock_post):
    [call] = [c for c in mock_post.call_args_list if c.args[0].endswith("/chat/completions")]
    return call


@pytest.mark.anyio
async def test_provider_is_asked_only_after_every_gemini_model_failed():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_busy(), _chat_ok("rescued"))
        assert await client._call_gemini(HELLO, task="mnemonic") == "rescued"
    targets = _targets(mock_post)
    assert targets[-1] == "provider" and targets.count("provider") == 1
    assert sorted(targets[:-1]) == sorted(ALL_GEMINI)
    assert _provider_call(mock_post).args[0] == f"{NIM}/chat/completions"
    assert model_health.cooldown_left(PROVIDER) == 0


@pytest.mark.anyio
async def test_provider_is_not_asked_when_gemini_answers():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_ok("gemini"), _chat_ok())
        assert await client._call_gemini(HELLO) == "gemini"
    assert "provider" not in _targets(mock_post)


def test_messages_are_translated_to_openai_format():
    contents = [
        {"role": "user", "parts": [{"text": "Explain 〜ばかり"}]},
        {"role": "model", "parts": [{"text": "plan", "thought": True}, {"text": "It means "}, {"text": "just did."}]},
        {"parts": [{"text": "And 〜ところ?"}]},  # no role: Gemini treats it as the user
    ]
    assert to_openai_messages(contents, "You are a sensei.") == [
        {"role": "system", "content": "You are a sensei."},
        {"role": "user", "content": "Explain 〜ばかり"},
        {"role": "assistant", "content": "It means just did."},
        {"role": "user", "content": "And 〜ところ?"},
    ]
    assert to_openai_messages(HELLO, None) == [{"role": "user", "content": "hello"}]


@pytest.mark.anyio
async def test_request_payload_and_bearer_auth():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_busy(), _chat_ok())
        await client._call_gemini(HELLO, system_instruction="Be brief.")
    call = _provider_call(mock_post)
    assert call.kwargs["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert "x-goog-api-key" not in call.kwargs["headers"]  # the Gemini key never leaves for another host
    assert call.kwargs["json"] == {
        "model": NIM_MODEL,
        "messages": [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hello"}],
        "temperature": 0.7,
        "max_tokens": 4096,
    }


@pytest.mark.anyio
async def test_local_server_needs_no_key_and_gets_a_longer_timeout():
    client = _client(base_url="http://localhost:11434/v1/", model="qwen2.5:14b", key="")
    timeouts = []
    real_init = httpx.AsyncClient.__init__

    def spy(self, *args, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        real_init(self, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "__init__", spy), patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_busy(), _chat_ok("ローカル", model="qwen2.5:14b"))
        assert await client._call_gemini(HELLO) == "ローカル"
    call = _provider_call(mock_post)
    assert call.args[0] == "http://localhost:11434/v1/chat/completions"
    assert "Authorization" not in call.kwargs["headers"]
    assert timeouts[-1].read == gemini_client.OPENAI_COMPAT_LOCAL_TIMEOUT
    assert timeouts[-1].read > gemini_client.OPENAI_COMPAT_TIMEOUT > gemini_client.ATTEMPT_TIMEOUT


def test_local_urls():
    for url in ["http://localhost:11434/v1", "http://127.0.0.1:1234/v1", "http://[::1]:8080/v1", "http://ollama.localhost/v1"]:
        assert is_local_url(url), url
    for url in [NIM, "https://openrouter.ai/api/v1", "http://192.168.1.20:11434/v1"]:
        assert not is_local_url(url), url


@pytest.mark.anyio
async def test_provider_failure_still_raises_busy_and_cools_it_down():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_busy(), _chat_err(503, "overloaded"))
        with pytest.raises(GeminiBusyError) as exc:
            await client._call_gemini(HELLO)
    assert f"[{PROVIDER}] HTTP 503" in str(exc.value)
    assert 55 < model_health.cooldown_left(PROVIDER) <= 60
    assert not model_health.is_blocked(PROVIDER)  # soft: still tried as the last resort


@pytest.mark.anyio
async def test_provider_timeout_is_a_soft_cooldown():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_busy(), httpx.ReadTimeout("slow"))
        with pytest.raises(GeminiBusyError):
            await client._call_gemini(HELLO)
    assert model_health.cooldown_left(PROVIDER) > 0 and not model_health.is_blocked(PROVIDER)
    assert model_health.reason(PROVIDER) == "timed out"


@pytest.mark.anyio
async def test_rate_limit_with_retry_after_blocks_the_provider():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_busy(), _chat_err(429, "Too Many Requests", {"Retry-After": "30"}))
        with pytest.raises(GeminiBusyError) as exc:
            await client._call_gemini(HELLO)
    assert exc.value.retry_after == 30
    assert model_health.is_blocked(PROVIDER) and 25 < model_health.cooldown_left(PROVIDER) <= 30

    # While blocked the next call doesn't even ask it
    model_health.reset()
    model_health.failed(PROVIDER, retry_after=30, hard=True, reason="rate limited")
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_busy(), _chat_ok())
        with pytest.raises(GeminiBusyError) as exc:
            await client._call_gemini(HELLO)
    assert "provider" not in _targets(mock_post)
    assert f"[{PROVIDER}] skipped, rate limited" in str(exc.value)


@pytest.mark.anyio
async def test_rate_limit_without_retry_after_is_soft():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_busy(), _chat_err(429, "slow down"))
        with pytest.raises(GeminiBusyError):
            await client._call_gemini(HELLO)
    assert model_health.cooldown_left(PROVIDER) > 0 and not model_health.is_blocked(PROVIDER)


@pytest.mark.anyio
async def test_provider_answers_when_every_gemini_model_is_out_of_quota():
    for m in ALL_GEMINI:
        model_health.failed(m, retry_after=3600, hard=True, reason="daily quota used up")
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_ok(), _chat_ok("still working"))
        assert await client._call_gemini(HELLO) == "still working"
    assert _targets(mock_post) == ["provider"]


@pytest.mark.anyio
async def test_out_of_quota_and_provider_busy_is_retryable():
    for m in ALL_GEMINI:
        model_health.failed(m, retry_after=3600, hard=True, reason="daily quota used up")
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_ok(), _chat_err(502, "bad gateway"))
        with pytest.raises(GeminiBusyError):
            await client._call_gemini(HELLO)


@pytest.mark.anyio
async def test_out_of_quota_and_provider_down_is_still_a_quota_error():
    for m in ALL_GEMINI:
        model_health.failed(m, retry_after=3600, hard=True, reason="daily quota used up")
    client = _client(base_url="http://localhost:11434/v1", model="qwen2.5:14b", key="")
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_ok(), httpx.ConnectError("connection refused"))
        with pytest.raises(GeminiQuotaError):
            await client._call_gemini(HELLO)


@pytest.mark.anyio
async def test_local_provider_answers_when_gemini_is_unreachable():
    client = _client(base_url="http://localhost:11434/v1", model="qwen2.5:14b", key="")
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(httpx.ConnectError("offline"), _chat_ok("offline answer"))
        assert await client._call_gemini(HELLO) == "offline answer"
    assert _targets(mock_post) == ["gemini-flash-latest", "provider"]


@pytest.mark.anyio
@pytest.mark.parametrize("missing", ["openaiCompatBaseUrl", "openaiCompatModel"])
async def test_skipped_entirely_when_unconfigured(missing):
    client = _client()
    client.config[missing] = ""
    assert client.openai_compat_name is None
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_busy(), _chat_ok())
        with pytest.raises(GeminiBusyError) as exc:
            await client._call_gemini(HELLO)
    assert "provider" not in _targets(mock_post)
    assert "openai:" not in str(exc.value)


@pytest.mark.anyio
async def test_reasoning_is_stripped_from_the_reply():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_busy(), _chat_ok('<think>\nLet me think.\n</think>\n{"a": 1}'))
        assert await client._call_gemini(HELLO) == '{"a": 1}'


@pytest.mark.anyio
async def test_empty_reply_is_a_failure():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_busy(), _chat_ok(""))
        with pytest.raises(GeminiBusyError) as exc:  # busy because the Gemini models were
            await client._call_gemini(HELLO)
    assert f"[{PROVIDER}] Empty reply" in str(exc.value)


@pytest.mark.anyio
async def test_callers_work_unchanged_with_the_provider():
    client = _client()
    reply = '{"vocab_kanji": "避難", "vocab_furigana": "避難[ひなん]", "vocab_def": "evacuation"}'
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_busy(), _chat_ok(reply))
        result = await client.analyze_vocab("避難")
    assert result["vocabDef"] == "evacuation" and result["vocabFurigana"] == "避難[ひなん]"


@pytest.mark.anyio
async def test_attempts_are_logged_under_the_provider_name():
    client = _client()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = _route(_gemini_busy(), [_chat_err(503), _chat_ok()])
        with pytest.raises(GeminiBusyError):
            await client._call_gemini(HELLO, task="sentence")
        await client._call_gemini(HELLO, task="sentence")
    stats = {s.model: s for s in model_health.db.model_stats()}
    assert stats[PROVIDER].calls == 2 and stats[PROVIDER].ok == 1 and stats[PROVIDER].overloaded == 1

    usage = {m["model"]: m for m in gemini_client.usage_report(client.candidate_models() + [PROVIDER])["models"]}
    assert usage[PROVIDER]["answered"] == 1
    perf = {m["model"] for m in gemini_client.performance_report("day")["models"]}
    assert PROVIDER in perf


@pytest.mark.anyio
async def test_the_api_key_is_never_logged(caplog):
    client = _client()
    with caplog.at_level(logging.DEBUG):
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = _route(_gemini_busy(), _chat_err(401, "Invalid API key"))
            with pytest.raises(GeminiBusyError) as exc:
                await client._call_gemini(HELLO)
    assert SECRET not in caplog.text and SECRET not in str(exc.value)
    assert "check openaiCompatApiKey" in str(exc.value)
    failures = model_health.db.recent_failures()
    assert failures and all(SECRET not in (f.error or "") for f in failures)


def test_provider_is_never_a_gemini_fallback():
    client = _client()
    client.config["fallbackModels"] = ["gemini-3.6-flash", PROVIDER]
    assert client.fallback_models == ["gemini-3.6-flash"]
    assert PROVIDER not in client.candidate_models()


def test_fallback_plan_lists_the_provider_last_and_never_missing():
    db = model_health.db
    db.save_catalog([{"name": m, "display_name": m, "version": "1", "output_token_limit": 65536, "thinking": True}
                     for m in ["gemini-flash-latest", "gemini-3.6-flash"]])
    for _ in range(3):
        db.record_call(model=PROVIDER, task="mnemonic", outcome="ok", http_status=200, latency_ms=4000,
                       model_version="meta/llama-3.3-70b-instruct-fp8")
    db.record_call(model=PROVIDER, task="mnemonic", outcome="not_found", http_status=404, latency_ms=100,
                   started_at=gemini_client.datetime.now(gemini_client.timezone.utc) - timedelta(days=30))

    plan = fallback_plan("gemini-flash-latest", ["gemini-3.6-flash", "gemini-gone"], db, providers=[PROVIDER])
    by_model = {e.model: e for e in plan}
    provider = by_model[PROVIDER]
    assert provider.role == "provider" and provider.status == "try" and provider.note == ""
    assert provider.resolves_to is None  # not treated as a Gemini alias
    assert provider.stats.ok == 3
    assert [e.model for e in plan if e.status == "try"][-1] == PROVIDER
    assert by_model["gemini-gone"].status == "missing"
    # The Gemini try order leaves it out: _call_gemini asks the provider itself
    assert PROVIDER not in try_order("gemini-flash-latest", ["gemini-3.6-flash", PROVIDER], db)


@pytest.fixture
def api():
    from fastapi.testclient import TestClient
    import app as app_module

    yield TestClient(app_module.app), app_module
    # Other tests load the same temporary config.json: turn the provider off again
    app_module.gemini.save_config({"openaiCompatBaseUrl": "", "openaiCompatModel": "", "openaiCompatApiKey": ""})


def test_settings_save_and_mask_the_provider_key(api):
    client, app_module = api
    res = client.post("/api/config", json={
        "openaiCompatBaseUrl": "https://openrouter.ai/api/v1/",
        "openaiCompatModel": "deepseek/deepseek-chat-v3:free",
        "openaiCompatApiKey": "sk-or-v1-0123456789abcdef",
    })
    assert res.status_code == 200
    cfg = client.get("/api/config").json()
    assert cfg["openaiCompatBaseUrl"] == "https://openrouter.ai/api/v1"
    assert cfg["openaiCompatModel"] == "deepseek/deepseek-chat-v3:free"
    assert cfg["hasOpenaiCompatKey"] and cfg["maskedOpenaiCompatKey"] == "sk-or-...cdef"
    assert "sk-or-v1-0123456789abcdef" not in res.text + str(cfg)
    assert app_module.gemini.openai_compat_name == "openai:deepseek/deepseek-chat-v3:free"

    # An empty key field keeps the saved key; the checkbox removes it
    client.post("/api/config", json={"openaiCompatApiKey": ""})
    assert app_module.gemini.openai_compat_api_key == "sk-or-v1-0123456789abcdef"
    client.post("/api/config", json={"clearOpenaiCompatApiKey": True})
    assert app_module.gemini.openai_compat_api_key == ""

    assert client.post("/api/config", json={"openaiCompatBaseUrl": "integrate.api.nvidia.com"}).status_code == 400
    client.post("/api/config", json={"openaiCompatBaseUrl": "", "openaiCompatModel": ""})
    assert app_module.gemini.openai_compat_name is None


# ---- keys from the environment (or .env) ------------------------------------------------------

ENV_KEY = "nvapi-from-the-environment-9876"


@pytest.fixture
def no_env_keys(monkeypatch):
    for var in gemini_client.OPENAI_COMPAT_KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_key_falls_back_to_env_vars_in_order(no_env_keys):
    client = _client(key="")
    assert client.openai_compat_api_key == "" and client.openai_compat_key_source is None
    no_env_keys.setenv("NVIDIA_API_KEY", "nvapi-nvidia")
    assert client.openai_compat_api_key == "nvapi-nvidia" and client.openai_compat_key_source == "NVIDIA_API_KEY"
    no_env_keys.setenv("OPENAI_COMPAT_API_KEY", "sk-generic")
    assert client.openai_compat_api_key == "sk-generic" and client.openai_compat_key_source == "OPENAI_COMPAT_API_KEY"
    client.config["openaiCompatApiKey"] = "sk-from-settings"
    assert client.openai_compat_api_key == "sk-from-settings" and client.openai_compat_key_source == "config"


def test_nvidia_key_alone_defaults_the_base_url_to_nim(no_env_keys):
    client = _client(base_url="", key="")
    assert client.openai_compat_name is None
    no_env_keys.setenv("NVIDIA_API_KEY", ENV_KEY)
    assert client.openai_compat_base_url == NIM and client.openai_compat_name == PROVIDER

    client.config["openaiCompatBaseUrl"] = "http://localhost:11434/v1"
    assert client.openai_compat_base_url == "http://localhost:11434/v1"  # a configured URL wins
    client.config["openaiCompatBaseUrl"] = ""

    # Another key in use: never send it to NVIDIA by default
    no_env_keys.setenv("OPENAI_COMPAT_API_KEY", "sk-or-openrouter")
    assert client.openai_compat_base_url == "" and client.openai_compat_name is None
    no_env_keys.delenv("OPENAI_COMPAT_API_KEY")
    client.config["openaiCompatApiKey"] = "sk-or-openrouter"
    assert client.openai_compat_base_url == ""


@pytest.mark.anyio
async def test_nvidia_env_key_and_a_model_are_enough(no_env_keys, caplog):
    no_env_keys.setenv("NVIDIA_API_KEY", ENV_KEY)
    client = _client(base_url="", key="")
    with caplog.at_level(logging.DEBUG):
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = _route(_gemini_busy(), [_chat_err(500, "oops"), _chat_ok("nim")])
            with pytest.raises(GeminiBusyError) as exc:
                await client._call_gemini(HELLO)
            assert await client._call_gemini(HELLO) == "nim"
    calls = [c for c in mock_post.call_args_list if c.args[0].endswith("/chat/completions")]
    assert calls[-1].args[0] == f"{NIM}/chat/completions"
    assert calls[-1].kwargs["headers"]["Authorization"] == f"Bearer {ENV_KEY}"
    assert ENV_KEY not in caplog.text and ENV_KEY not in str(exc.value)


def test_settings_show_an_env_key_masked(api, no_env_keys):
    client, app_module = api
    no_env_keys.setenv("NVIDIA_API_KEY", ENV_KEY)
    app_module.gemini.save_config({"openaiCompatModel": NIM_MODEL})
    res = client.get("/api/config")
    cfg = res.json()
    assert cfg["openaiCompatKeySource"] == "NVIDIA_API_KEY"
    assert cfg["maskedOpenaiCompatKey"] == "nvapi-...9876" and cfg["hasOpenaiCompatKey"]
    assert cfg["openaiCompatBaseUrl"] == "" and cfg["openaiCompatEffectiveBaseUrl"] == NIM
    assert ENV_KEY not in res.text


def test_dotenv_file_is_loaded_without_overriding_the_environment(tmp_path, no_env_keys):
    import config_defaults

    (tmp_path / ".env").write_text(f"NVIDIA_API_KEY={ENV_KEY}\nOPENAI_COMPAT_API_KEY=from-dotenv\n")
    no_env_keys.setenv("OPENAI_COMPAT_API_KEY", "from-the-shell")
    no_env_keys.setattr(config_defaults, "APP_DIR", str(tmp_path))

    no_env_keys.setenv("LEECH_DOCTOR_DOTENV", "0")
    config_defaults.load_dotenv_file()
    assert "NVIDIA_API_KEY" not in gemini_client.os.environ

    no_env_keys.setenv("LEECH_DOCTOR_DOTENV", "1")
    config_defaults.load_dotenv_file()
    assert gemini_client.os.environ["NVIDIA_API_KEY"] == ENV_KEY
    assert gemini_client.os.environ["OPENAI_COMPAT_API_KEY"] == "from-the-shell"
