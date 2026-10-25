import os
import socket
import sys
import types
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Set before any app module runs load_dotenv(), which never overrides a variable that is
# already set: the suite can't pick up real keys or a real Redis from apps/server/.env.
os.environ.update(
    {
        "NEXT_PUBLIC_SUPABASE_URL": "http://supabase.test",
        "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
        "GEMINI_API_KEY": "test-gemini-key",
        "GEMINI_CHAT_MODEL": "gemini-3.8-flash",
        "GEMINI_FALLBACK_MODEL": "gemini-flash-lite-latest",
        "GEMINI_EMBEDDING_MODEL": "models/gemini-embedding-001",
        "GEMINI_MIN_SECONDS_BETWEEN_CALLS": "0",
        "GEMINI_THINKING_LEVEL": "low",
        "GEMINI_TIMEOUT_SECONDS": "120",
        "GEMINI_INTERACTIVE_TIMEOUT_SECONDS": "60",
        "GEMINI_MAX_ANSWER_TOKENS": "2048",
        "REDIS_URL": "",
        "CACHE_EMBEDDING_TTL_SECONDS": "2592000",
        "CACHE_SEARCH_TTL_SECONDS": "21600",
        "CACHE_ANSWER_TTL_SECONDS": "86400",
        "CACHE_MEMORY_MAX_ITEMS": "5000",
        "STARTUP_SLOW_IMPORT_SECONDS": "600",
        "STARTUP_TIMEOUT_SECONDS": "60",
    }
)

import cache  # noqa: E402
import storage_utils  # noqa: E402
from fakes import FakeGenaiClient, FakeLegacyGenai, FakeSupabase  # noqa: E402

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "audio: runs real faster-whisper on synthesized speech (needs ffmpeg, a TTS voice and the cached Whisper model)",
    )


@pytest.fixture(autouse=True, scope="session")
def scratch_cwd(tmp_path_factory):
    """Runs the suite in a scratch folder, so temp_chunks/ files never land in the repo."""
    previous = os.getcwd()
    os.chdir(tmp_path_factory.mktemp("cwd"))
    yield
    os.chdir(previous)


@pytest.fixture(autouse=True)
def no_network(monkeypatch, request):
    """Fails any test that tries to reach the internet, so the suite never spends API quota."""
    if request.node.get_closest_marker("audio"):
        return  # Whisper may download its model once
    real_connect = socket.socket.connect

    def guarded_connect(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if sock.family == getattr(socket, "AF_UNIX", None) or host in LOCAL_HOSTS:
            return real_connect(sock, address)
        raise RuntimeError(
            f"Tests must not use the network (tried to connect to {address})."
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.configure(cache.MemoryCache())
    yield cache
    cache.configure(None)


@pytest.fixture(autouse=True)
def db(monkeypatch):
    """Every test gets an empty in-memory Supabase behind storage_utils.supabase."""
    fake = FakeSupabase()
    monkeypatch.setattr(storage_utils, "_client", fake)
    return fake


@pytest.fixture
def no_sleep(monkeypatch):
    """Records time.sleep calls instead of waiting (pacing, backoff, OCR throttling)."""
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))
    return sleeps


@pytest.fixture
def embedder(monkeypatch):
    """A fake Gemini embedding SDK with deterministic bag-of-words vectors."""
    import embedding_engine

    fake = FakeLegacyGenai()
    monkeypatch.setattr(embedding_engine, "get_genai", lambda: fake)
    return fake


@pytest.fixture
def gemini(monkeypatch, no_sleep):
    """A fake google-genai client. Queue replies with gemini.replies.append(...)."""
    import gemini_utils

    client = FakeGenaiClient()
    monkeypatch.setattr(gemini_utils, "_client", client)
    monkeypatch.setattr(gemini_utils, "_last_generation_call", 0.0)
    return client


def stub_module(monkeypatch, name: str, **attributes) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.fixture
def stub(monkeypatch):
    """stub('faster_whisper', WhisperModel=...) puts a fake module in sys.modules for one test."""
    return lambda name, **attributes: stub_module(monkeypatch, name, **attributes)
