from types import SimpleNamespace
from typing import List

import pytest
from pydantic import BaseModel

import gemini_utils
from fakes import FakeLegacyGenai, gemini_response


class Answer(BaseModel):
    items: List[str]


@pytest.mark.parametrize(
    "message, invalid, retryable, timeout",
    [
        ("400 API_KEY_INVALID", True, False, False),
        ("403 PERMISSION_DENIED", True, False, False),
        ("429 RESOURCE_EXHAUSTED", False, True, False),
        ("503 UNAVAILABLE", False, True, False),
        ("504 DEADLINE_EXCEEDED", False, False, True),
        ("Deadline expired before operation could complete", False, True, True),
        ("The read operation timed out", False, True, True),
        ("500 INTERNAL", False, False, False),
    ],
)
def test_error_classification(message, invalid, retryable, timeout):
    error = RuntimeError(message)
    assert gemini_utils.is_invalid_key_error(error) is invalid
    assert gemini_utils.is_retryable_error(error) is retryable
    assert gemini_utils.is_timeout_error(error) is timeout


def test_friendly_errors_are_short():
    assert "timed out on every try (60s each" in gemini_utils.friendly_error(
        RuntimeError("504 DEADLINE_EXCEEDED"), 60
    )
    assert "quota" in gemini_utils.friendly_error(
        RuntimeError("429 RESOURCE_EXHAUSTED"), 60
    )
    assert "overloaded" in gemini_utils.friendly_error(
        RuntimeError("503 UNAVAILABLE"), 60
    )
    assert gemini_utils.friendly_error(RuntimeError("boom"), 60) == "boom"


def test_thinking_config_error_detection():
    assert gemini_utils.is_thinking_config_error(
        RuntimeError("400 INVALID_ARGUMENT: thinking_level is not supported")
    )
    assert not gemini_utils.is_thinking_config_error(
        RuntimeError("400 INVALID_ARGUMENT: bad schema")
    )


def test_check_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(
        gemini_utils, "SERVER_DIR", tmp_path
    )  # never read the real .env
    gemini_utils.check_environment("TEST")
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "  ")
    with pytest.raises(
        EnvironmentError, match="SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY"
    ):
        gemini_utils.check_environment("TEST")


def test_pacing_waits_only_the_remainder(monkeypatch, no_sleep):
    monkeypatch.setattr(gemini_utils, "MIN_SECONDS_BETWEEN_CALLS", 6.0)
    monkeypatch.setattr(gemini_utils, "_last_generation_call", 0.0)
    monkeypatch.setattr(gemini_utils.time, "monotonic", lambda: 100.0)
    gemini_utils._pace("TEST")  # Long since the last call: no wait
    monkeypatch.setattr(gemini_utils.time, "monotonic", lambda: 102.0)
    gemini_utils._pace("TEST")
    assert no_sleep == [4.0]


def test_backoff_or_raise(no_sleep):
    with pytest.raises(gemini_utils.GeminiKeyError):
        gemini_utils._backoff_or_raise("T", RuntimeError("API key not valid"), 1)
    with pytest.raises(RuntimeError, match="after 1 attempt"):
        gemini_utils._backoff_or_raise("T", RuntimeError("500 INTERNAL"), 1)
    with pytest.raises(RuntimeError, match="after 3 attempt"):
        gemini_utils._backoff_or_raise("T", RuntimeError("429"), 3, max_retries=3)
    gemini_utils._backoff_or_raise("T", RuntimeError("429"), 2)
    assert no_sleep == [gemini_utils.SECONDS_BETWEEN_EMBED_BATCHES * 4]


def test_finish_reason_variants():
    assert (
        gemini_utils.finish_reason(gemini_response("x", "MAX_TOKENS")) == "MAX_TOKENS"
    )
    assert gemini_utils.finish_reason(SimpleNamespace(candidates=[])) == ""
    assert (
        gemini_utils.finish_reason(
            SimpleNamespace(candidates=[SimpleNamespace(finish_reason="STOP")])
        )
        == "STOP"
    )
    assert gemini_utils.finish_reason(SimpleNamespace()) == ""


def test_generate_text_success_sets_deadline_and_skips_temperature_for_gemini_3(gemini):
    gemini.replies.append(gemini_response("  The answer.  "))
    text, model = gemini_utils.generate_text(
        "prompt", "system", 0.2, "T", max_output_tokens=512, timeout_seconds=45
    )
    assert (text, model) == ("The answer.", "gemini-3.8-flash")
    config = gemini.calls[0]["config"]
    assert config.temperature is None
    assert config.max_output_tokens == 512
    assert config.http_options.headers == {"X-Server-Timeout": "45"}
    assert config.automatic_function_calling.disable is True
    assert config.thinking_config.thinking_level is not None


def test_generate_text_sends_temperature_to_older_models(gemini, monkeypatch):
    monkeypatch.setattr(gemini_utils, "CHAT_MODEL", "gemini-2.5-flash")
    gemini.replies.append(gemini_response("ok"))
    gemini_utils.generate_text("p", "s", 0.2, "T")
    assert gemini.calls[0]["config"].temperature == 0.2
    assert gemini.calls[0]["model"] == "gemini-2.5-flash"


def test_rate_limits_are_retried_with_backoff(gemini, no_sleep):
    gemini.replies.extend(
        [RuntimeError("429 RESOURCE_EXHAUSTED"), gemini_response("done")]
    )
    text, _ = gemini_utils.generate_text("p", "s", 0.2, "T")
    assert text == "done" and len(gemini.calls) == 2 and no_sleep


def test_timeout_switches_to_the_fallback_model(gemini):
    gemini.replies.extend(
        [RuntimeError("504 DEADLINE_EXCEEDED"), gemini_response("fast answer")]
    )
    text, model = gemini_utils.generate_text("p", "s", 0.2, "T", fallback=True)
    assert (text, model) == ("fast answer", "gemini-flash-lite-latest")
    assert [c["model"] for c in gemini.calls] == [
        "gemini-3.8-flash",
        "gemini-flash-lite-latest",
    ]


def test_unknown_fallback_model_goes_back_to_the_chat_model(gemini):
    gemini.replies.extend(
        [
            RuntimeError("504 DEADLINE_EXCEEDED"),
            RuntimeError("404 NOT_FOUND models/gemini-flash-lite-latest is not found"),
            gemini_response("slow answer"),
        ]
    )
    text, model = gemini_utils.generate_text("p", "s", 0.2, "T", fallback=True)
    assert (text, model) == ("slow answer", "gemini-3.8-flash")


def test_unknown_chat_model_says_how_to_fix_it(gemini):
    gemini.replies.append(RuntimeError("404 NOT_FOUND models/gemini-3.8-flash"))
    with pytest.raises(RuntimeError, match="Set GEMINI_CHAT_MODEL"):
        gemini_utils.generate_text("p", "s", 0.2, "T")


def test_thinking_level_rejection_retries_without_it(gemini):
    gemini.replies.extend(
        [
            RuntimeError("400 INVALID_ARGUMENT: thinking_level unsupported"),
            gemini_response("ok"),
        ]
    )
    gemini_utils.generate_text("p", "s", 0.2, "T")
    assert gemini.calls[1]["config"].thinking_config is None


def test_empty_max_tokens_reply_switches_to_the_fallback(gemini):
    gemini.replies.extend(
        [gemini_response("", "MAX_TOKENS"), gemini_response("answer")]
    )
    text, model = gemini_utils.generate_text(
        "p", "s", 0.2, "T", max_output_tokens=100, fallback=True
    )
    assert (text, model) == ("answer", "gemini-flash-lite-latest")


def test_cut_off_answers_keep_complete_lines(gemini):
    gemini.replies.append(
        gemini_response("line one\nline two\nline three\ncut mid-sen", "MAX_TOKENS")
    )
    text, _ = gemini_utils.generate_text("p", "s", 0.2, "T", max_output_tokens=100)
    assert text == "line one\nline two\nline three"


def test_giving_up_raises_a_friendly_error(gemini):
    gemini.replies.extend([gemini_response("", "MAX_TOKENS")] * 3)
    with pytest.raises(RuntimeError, match="MAX_TOKENS"):
        gemini_utils.generate_text("p", "s", 0.2, "T", max_output_tokens=100)

    gemini.replies.append(RuntimeError("API_KEY_INVALID"))
    with pytest.raises(gemini_utils.GeminiKeyError):
        gemini_utils.generate_text("p", "s", 0.2, "T")


def test_generate_structured_parses_json(gemini):
    gemini.replies.append(gemini_response(parsed=Answer(items=["a"])))
    assert gemini_utils.generate_structured("p", "s", Answer, 0.1, "T").items == ["a"]
    gemini.replies.append(gemini_response('{"items": ["b", "c"]}'))
    assert gemini_utils.generate_structured("p", "s", Answer, 0.1, "T").items == [
        "b",
        "c",
    ]
    config = gemini.calls[0]["config"]
    assert config.response_mime_type == "application/json" and config.temperature == 0.1


def test_embed_texts_batches_and_checks_dimensions(monkeypatch, no_sleep):
    import embedding_engine

    fake = FakeLegacyGenai()
    monkeypatch.setattr(embedding_engine, "get_genai", lambda: fake)
    vectors = gemini_utils.embed_texts([f"topic {i}" for i in range(23)], "T")
    assert len(vectors) == 23
    assert [len(c["content"]) for c in fake.calls] == [10, 10, 3]
    assert no_sleep == [gemini_utils.SECONDS_BETWEEN_EMBED_BATCHES] * 2

    fake.errors.append(RuntimeError("503 UNAVAILABLE"))
    assert len(gemini_utils.embed_texts(["retry me"], "T")) == 1

    fake.dimensions = 768
    with pytest.raises(RuntimeError, match="expected 1 of 1536"):
        gemini_utils.embed_texts(["x"], "T")


def test_get_client_is_created_once(monkeypatch):
    monkeypatch.setattr(gemini_utils, "_client", None)
    client = gemini_utils._get_client()
    assert gemini_utils._get_client() is client


def test_preload_runs_each_step(monkeypatch, capsys):
    import embedding_engine
    import storage_utils

    calls = []
    watchdog = SimpleNamespace(
        dump_traceback_later=lambda *a, **k: calls.append("watch"),
        cancel_dump_traceback_later=lambda: calls.append("cancel"),
    )
    monkeypatch.setattr(gemini_utils, "faulthandler", watchdog)
    monkeypatch.setattr(embedding_engine, "get_genai", lambda: calls.append("genai"))
    monkeypatch.setattr(storage_utils, "get_supabase", lambda: calls.append("supabase"))
    gemini_utils.preload("TEST")
    assert [c for c in calls if c not in ("watch", "cancel")] == ["supabase", "genai"]
    assert calls.count("watch") == calls.count("cancel") == 3
    assert "Loading the google-genai SDK: done" in capsys.readouterr().out
