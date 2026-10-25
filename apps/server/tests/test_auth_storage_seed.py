import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import auth
import seed_exam_topics as seed
import storage_utils
from fakes import FakeLegacyGenai


def authenticate(token: str):
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return asyncio.run(auth.get_current_user(credentials))


def test_valid_tokens_resolve_to_the_user(db):
    db.auth.response = SimpleNamespace(
        user=SimpleNamespace(id="u1", email="s@x.in", role="authenticated")
    )
    user = authenticate(' "token-123" ')
    assert (user.id, user.email, user.role) == ("u1", "s@x.in", "authenticated")
    assert db.auth.tokens == ["token-123"]  # quotes and spaces stripped

    db.auth.response = SimpleNamespace(user={"id": "u2", "email": "d@x.in"})
    assert authenticate("t").id == "u2"


@pytest.mark.parametrize(
    "response, error, detail",
    [
        (None, None, "Invalid or expired"),
        (SimpleNamespace(user=None), None, "Invalid or expired"),
        (
            SimpleNamespace(user={"email": "no-id@x.in"}),
            None,
            "missing user identifier",
        ),
        (None, RuntimeError("JWT expired"), "Authentication error: JWT expired"),
    ],
)
def test_bad_tokens_are_401(db, response, error, detail):
    db.auth.response, db.auth.error = response, error
    with pytest.raises(HTTPException) as raised:
        authenticate("t")
    assert raised.value.status_code == 401 and detail in raised.value.detail


def test_supabase_client_is_created_once_and_lazily(monkeypatch):
    created = []
    monkeypatch.setattr(storage_utils, "_client", None)
    monkeypatch.setattr(
        storage_utils,
        "create_client",
        lambda url, key: created.append((url, key))
        or SimpleNamespace(table=lambda name: f"table:{name}"),
    )
    assert storage_utils.supabase.table("lectures") == "table:lectures"
    assert storage_utils.get_supabase() is storage_utils.get_supabase()
    assert created == [("http://supabase.test", "test-service-role-key")]


def test_storage_helpers(db):
    assert storage_utils.generate_signed_url("lectures", "u/a.mp3", 60).endswith(
        "u/a.mp3?exp=60"
    )
    assert storage_utils.upload_file_backend("lectures", "u/a.mp3", b"abc") == {
        "Key": "lectures/u/a.mp3"
    }
    db.storage.error = RuntimeError("bucket not found")
    assert storage_utils.generate_signed_url("lectures", "x", 60) == ""
    assert storage_utils.upload_file_backend("lectures", "x", b"") is None


@pytest.fixture
def seeding(monkeypatch, tmp_path, no_sleep):
    import embedding_engine

    topics = [
        {"exam": "JEE", "subject": "Maths", "topic": f"Topic {i}"} for i in range(23)
    ]
    seed_file = tmp_path / "exam_topics.json"
    seed_file.write_text(json.dumps(topics))
    monkeypatch.setattr(seed, "SEED_FILE", seed_file)
    monkeypatch.setattr(seed, "SERVER_DIR", tmp_path)  # never read the real .env
    fake = FakeLegacyGenai()
    monkeypatch.setattr(embedding_engine, "get_genai", lambda: fake)
    return SimpleNamespace(genai=fake, topics=topics, sleeps=no_sleep)


def test_seeding_embeds_new_topics_in_paced_batches(db, seeding):
    db.seed("exam_topics", [{**seeding.topics[0], "embedding": [0.1] * 1536}])
    assert seed.seed_exam_topics() == 22
    assert [len(c["content"]) for c in seeding.genai.calls] == [10, 10, 2]
    assert seeding.sleeps == [seed.SECONDS_BETWEEN_BATCHES] * 2
    assert len(db.tables["exam_topics"]) == 23
    assert seed.seed_exam_topics() == 0  # a re-run has nothing left to do


def test_seeding_retries_rate_limits_and_stops_on_bad_keys(db, seeding):
    seeding.genai.errors.append(RuntimeError("429 RESOURCE_EXHAUSTED"))
    assert seed.embed_batch(seeding.genai, "m", ["a"])
    seeding.genai.errors.append(RuntimeError("API key not valid"))
    with pytest.raises(SystemExit):
        seed.embed_batch(seeding.genai, "m", ["a"])
    seeding.genai.errors.append(RuntimeError("500 INTERNAL"))
    with pytest.raises(SystemExit):
        seed.embed_batch(seeding.genai, "m", ["a"])


def test_seeding_fails_loudly(db, seeding, monkeypatch, capsys):
    seeding.genai.dimensions = 768
    with pytest.raises(SystemExit):
        seed.seed_exam_topics()
    assert "expected 10 of 1536" in capsys.readouterr().err

    seeding.genai.dimensions = 1536
    db.fail("exam_topics:upsert", RuntimeError("relation does not exist"))
    with pytest.raises(SystemExit):
        seed.seed_exam_topics()

    db.fail("exam_topics:select", RuntimeError("relation does not exist"))
    with pytest.raises(SystemExit):
        seed.seed_exam_topics()

    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(SystemExit):
        seed.check_environment()
    assert "Missing environment variables: GEMINI_API_KEY" in capsys.readouterr().err


def test_topic_embedding_text():
    assert (
        seed.topic_embedding_text(
            {"exam": "NEET", "subject": "Biology", "topic": "Cell"}
        )
        == "NEET Biology: Cell"
    )
