"""Test setup: point the app at a throwaway config and RAG store so running the
suite never reads or rewrites your real config.json or vector index."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="leech-doctor-tests-")
os.environ["LEECH_DOCTOR_CONFIG"] = os.path.join(_tmp, "config.json")
os.environ["LEECH_DOCTOR_RAG_DIR"] = os.path.join(_tmp, "rag")
os.environ["LEECH_DOCTOR_DB"] = os.path.join(_tmp, "leech_doctor.db")
os.environ["LEECH_DOCTOR_ALLOWED_HOSTS"] = "127.0.0.1,localhost,testserver"
# Unit tests must never read or change your real Anki collection: point AnkiConnect at a
# port nothing listens on. Integration tests (-m integration) pass the real URL explicitly.
REAL_ANKI_CONNECT_URL = os.environ.get("ANKI_CONNECT_URL", "http://127.0.0.1:8765")
os.environ["ANKI_CONNECT_URL"] = "http://127.0.0.1:9"
# Never fetch Gemini's model list in the background during tests
os.environ["LEECH_DOCTOR_MODEL_REFRESH"] = "0"
# Never read your .env, and ignore API keys from the shell running the tests
os.environ["LEECH_DOCTOR_DOTENV"] = "0"
for _var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_COMPAT_API_KEY", "NVIDIA_API_KEY"):
    os.environ.pop(_var, None)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_gemini_model_health():
    """Cooldowns and the call log are process-wide; start every test with an empty database."""
    from gemini_client import model_health
    model_health.reset()
    yield
    model_health.reset()
