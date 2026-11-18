"""Test setup: point the app at a throwaway config and RAG store so running the
suite never reads or rewrites your real config.json or vector index."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="leech-doctor-tests-")
os.environ["LEECH_DOCTOR_CONFIG"] = os.path.join(_tmp, "config.json")
os.environ["LEECH_DOCTOR_RAG_DIR"] = os.path.join(_tmp, "rag")
os.environ["LEECH_DOCTOR_ALLOWED_HOSTS"] = "127.0.0.1,localhost,testserver"
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)
