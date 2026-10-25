"""
Shared Gemini free-tier helpers for /chat/ask and the background engines (cheat sheet, study set).

Every call here has a hard timeout, logs its progress, retries 429/503 with a visible
backoff and fails immediately on an invalid key. Background jobs are also paced so
back-to-back calls stay under the free-tier requests-per-minute quota.
"""

import faulthandler
import importlib
import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple, Type, TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel

SERVER_DIR = Path(__file__).resolve().parent

CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.8-flash")
# A faster model that /chat/ask and the summary switch to once CHAT_MODEL times out.
# The -latest alias always points at a current Flash-Lite model. Empty turns the fallback off.
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-flash-lite-latest").strip()
# google-genai also sends this to Gemini as the server-side deadline (X-Server-Timeout),
# so a slow answer comes back as 504 DEADLINE_EXCEEDED once it runs past it
REQUEST_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "120"))
# Deadline for the short answers a student is waiting on (/chat/ask and the summary). A healthy
# answer takes well under this; past it, waiting longer on the free tier rarely helps.
INTERACTIVE_TIMEOUT_SECONDS = int(os.getenv("GEMINI_INTERACTIVE_TIMEOUT_SECONDS", "60"))
# Output cap for those answers. Thinking tokens count toward it, so it leaves room for both.
MAX_ANSWER_TOKENS = int(os.getenv("GEMINI_MAX_ANSWER_TOKENS", "2048"))
# How long the model "thinks" before answering; lower is faster. Empty uses the model default.
THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "low").strip()
MAX_RETRIES = 5
# 6s between generation calls is ~10 requests/minute, under the Flash free-tier RPM limit
MIN_SECONDS_BETWEEN_CALLS = float(os.getenv("GEMINI_MIN_SECONDS_BETWEEN_CALLS", "6"))
EMBED_BATCH_SIZE = 10
SECONDS_BETWEEN_EMBED_BATCHES = 4
EXPECTED_DIMENSIONS = 1536
# If any startup step takes longer than this, print where it is stuck and exit
STARTUP_TIMEOUT_SECONDS = int(os.getenv("STARTUP_TIMEOUT_SECONDS", "60"))
REQUIRED_ENV_KEYS = (
    "NEXT_PUBLIC_SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "GEMINI_API_KEY",
)

T = TypeVar("T", bound=BaseModel)

_last_generation_call = 0.0
_client = None


class GeminiKeyError(RuntimeError):
    """The Gemini API rejected the key. Retrying will never help."""


def log(tag: str, message: str) -> None:
    print(f"[{tag}] {message}", flush=True)


def check_environment(tag: str) -> None:
    """Loads apps/server/.env and raises with the exact missing keys, before any network call."""
    env_path = SERVER_DIR / ".env"
    load_dotenv(dotenv_path=env_path)
    missing = [k for k in REQUIRED_ENV_KEYS if not os.getenv(k, "").strip()]
    if missing:
        raise EnvironmentError(
            f"Missing environment variables: {', '.join(missing)}. Add them to {env_path}."
        )
    log(tag, "Environment OK (Supabase URL, service-role key and Gemini key are set).")


def preload(tag: str) -> None:
    """
    Sets up the Supabase client and the Gemini SDKs one at a time with a log line per step, so a
    stall shows exactly which step it is. A watchdog prints the stuck stack trace and exits
    if any step takes longer than STARTUP_TIMEOUT_SECONDS.
    """
    from embedding_engine import get_genai
    from storage_utils import get_supabase

    steps = (
        ("Creating Supabase client", get_supabase),
        (
            "Loading the google-genai SDK",
            lambda: importlib.import_module("google.genai"),
        ),
        ("Loading and configuring the Gemini embedding SDK", get_genai),
    )
    log(
        tag,
        f"Loading Supabase and Gemini. A step stuck for {STARTUP_TIMEOUT_SECONDS}s prints its stack trace and exits.",
    )
    for label, step in steps:
        log(tag, f"{label}...")
        started = time.monotonic()
        faulthandler.dump_traceback_later(
            STARTUP_TIMEOUT_SECONDS, exit=True, file=sys.stderr
        )
        try:
            step()
        finally:
            faulthandler.cancel_dump_traceback_later()
        log(tag, f"{label}: done in {time.monotonic() - started:.1f}s.")


def is_invalid_key_error(error: Exception) -> bool:
    text = str(error)
    return any(
        s in text
        for s in ("API_KEY_INVALID", "API key not valid", "PERMISSION_DENIED", "403")
    )


def is_retryable_error(error: Exception) -> bool:
    text = str(error)
    return any(
        s in text
        for s in (
            "429",
            "RESOURCE_EXHAUSTED",
            "503",
            "UNAVAILABLE",
            "Deadline",
            "timed out",
            "Timeout",
        )
    )


def is_timeout_error(error: Exception) -> bool:
    """Gemini ran past its deadline (504 DEADLINE_EXCEEDED) or the request timed out locally."""
    text = str(error)
    return any(
        s in text
        for s in ("504", "DEADLINE_EXCEEDED", "Deadline", "timed out", "Timeout")
    )


def friendly_error(error: Exception, timeout_seconds: int) -> str:
    """A short reason for the UI; the full Gemini error stays in the server log."""
    if is_timeout_error(error):
        return (
            f"Gemini's free tier timed out on every try ({timeout_seconds}s each, 504 DEADLINE_EXCEEDED). "
            "It is usually busy for only a minute or two; try again shortly."
        )
    text = str(error)
    if "429" in text or "RESOURCE_EXHAUSTED" in text:
        return "Gemini's free-tier quota is used up for the moment (429). Wait a minute and try again."
    if "503" in text or "UNAVAILABLE" in text:
        return "Gemini is overloaded right now (503). Try again in a minute."
    return str(error)


def _pace(tag: str) -> None:
    """Sleeps just long enough to keep MIN_SECONDS_BETWEEN_CALLS between generation calls."""
    global _last_generation_call
    wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_generation_call)
    if wait > 0:
        log(
            tag,
            f"Pacing for the free tier: waiting {wait:.0f}s before the next Gemini call...",
        )
        time.sleep(wait)
    _last_generation_call = time.monotonic()


def _backoff_or_raise(
    tag: str, error: Exception, attempt: int, max_retries: int = MAX_RETRIES
) -> None:
    if is_invalid_key_error(error):
        raise GeminiKeyError(f"Gemini rejected GEMINI_API_KEY: {error}") from error
    if not is_retryable_error(error) or attempt == max_retries:
        raise RuntimeError(
            f"Gemini call failed after {attempt} attempt(s): {error}"
        ) from error
    wait = SECONDS_BETWEEN_EMBED_BATCHES * 2**attempt
    log(
        tag,
        f"Gemini rate limit or timeout ({str(error)[:80]}). Retry {attempt}/{max_retries - 1} in {wait}s...",
    )
    time.sleep(wait)


def _get_client():
    """One google-genai client for the process, with a hard per-request timeout."""
    global _client
    if _client is None:
        from google import genai
        from google.genai import types

        _client = genai.Client(
            http_options=types.HttpOptions(
                timeout=REQUEST_TIMEOUT_SECONDS * 1000,  # milliseconds
                # One attempt per call: retries happen below, where they are logged
                retry_options=types.HttpRetryOptions(attempts=1),
            )
        )
    return _client


def base_config_options() -> dict:
    """Options every generation call shares: no AFC, and a low thinking level for speed."""
    from google.genai import types

    options = {"automatic_function_calling": no_afc_config()}
    if THINKING_LEVEL:
        options["thinking_config"] = types.ThinkingConfig(thinking_level=THINKING_LEVEL)
    return options


def is_thinking_config_error(error: Exception) -> bool:
    text = str(error)
    return ("400" in text or "INVALID_ARGUMENT" in text) and "thinking" in text.lower()


def no_afc_config():
    """
    We never pass tools, but some google-genai versions still run their automatic
    function calling path on every generate_content call and log a warning about it.
    Disabling it sends the request straight to the model.
    """
    from google.genai import types

    return types.AutomaticFunctionCallingConfig(disable=True)


def finish_reason(response) -> str:
    """Why Gemini stopped writing, e.g. "STOP" or "MAX_TOKENS"; "" if the response doesn't say."""
    try:
        reason = response.candidates[0].finish_reason
    except (AttributeError, IndexError, TypeError):
        return ""
    return getattr(reason, "name", None) or str(reason or "")


def _generate(
    prompt: str,
    config,
    tag: str,
    pace: bool,
    max_retries: int,
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
    fallback_model: str = "",
):
    """
    Calls CHAT_MODEL with a hard deadline and logged retries, and returns (response, model).
    With a fallback_model, a timeout switches the remaining attempts to that faster model
    straight away instead of waiting out the same deadline again.
    """
    from google.genai import types

    client = _get_client()
    # Per-call deadline. The header is set here because google-genai otherwise keeps the
    # X-Server-Timeout of its first call on the client and sends it with every later call.
    config = config.model_copy(
        update={
            "http_options": types.HttpOptions(
                timeout=timeout_seconds * 1000,  # milliseconds
                headers={"X-Server-Timeout": str(timeout_seconds)},
            )
        }
    )
    model = CHAT_MODEL
    last_problem = "Gemini returned no response."
    for attempt in range(1, max_retries + 1):
        if pace:
            _pace(tag)
        started = time.monotonic()
        log(
            tag,
            f"Calling {model} with a {len(prompt):,}-char prompt "
            f"(attempt {attempt}/{max_retries}, timeout {timeout_seconds}s)...",
        )
        try:
            response = client.models.generate_content(
                model=model, contents=prompt, config=config
            )
        except Exception as e:
            # A retired or misspelled model name: retrying won't help, so say how to fix it
            if "NOT_FOUND" in str(e) and "models/" in str(e):
                if model != CHAT_MODEL:
                    log(
                        tag,
                        f"Gemini has no model named {model!r}; set GEMINI_FALLBACK_MODEL in "
                        f"{SERVER_DIR / '.env'} to one your key can use. Going back to {CHAT_MODEL}.",
                    )
                    model, fallback_model = CHAT_MODEL, ""
                    continue
                raise RuntimeError(
                    f"Gemini has no model named {CHAT_MODEL!r}. Set GEMINI_CHAT_MODEL in "
                    f"{SERVER_DIR / '.env'} to a model your key can use. Gemini said: {e}"
                ) from e
            # Older models reject thinking_level: drop it and try again right away
            if getattr(config, "thinking_config", None) and is_thinking_config_error(e):
                log(tag, f"{model} rejected the thinking level; retrying without it.")
                config = config.model_copy(update={"thinking_config": None})
                continue
            if fallback_model and model != fallback_model and is_timeout_error(e):
                log(
                    tag,
                    f"{model} did not answer within {timeout_seconds}s ({str(e)[:60]}). "
                    f"Switching to the faster {fallback_model} now...",
                )
                model = fallback_model
                continue
            _backoff_or_raise(tag, e, attempt, max_retries)
            continue

        elapsed = time.monotonic() - started
        if (
            not (response.text or "").strip()
            and finish_reason(response) == "MAX_TOKENS"
        ):
            # The whole output budget went on thinking; another try, or the faster model, answers
            last_problem = (
                f"{model} used its whole {config.max_output_tokens}-token output budget "
                "without writing an answer (MAX_TOKENS)."
            )
            log(tag, f"{last_problem} Took {elapsed:.1f}s.")
            if fallback_model and model != fallback_model:
                model = fallback_model
            continue
        log(tag, f"{model} responded in {elapsed:.1f}s.")
        return response, model
    raise RuntimeError(last_problem)


def generate_text(
    prompt: str,
    system_instruction: str,
    temperature: float,
    tag: str,
    pace: bool = False,
    max_retries: int = 3,
    max_output_tokens: Optional[int] = None,
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
    fallback: bool = False,
) -> Tuple[str, str]:
    """
    Plain-text Gemini Flash call with a hard timeout and logged retries (used by /chat/ask and the
    summary). With fallback=True a timeout switches to FALLBACK_MODEL. Returns (text, model).
    Failures raise with a short reason the UI can show.
    """
    from google.genai import types

    options = base_config_options()
    # Google recommends leaving Gemini 3 models at their default temperature (1.0): lower values
    # can make them loop, and a looping answer runs until the deadline and ends in a 504
    if not CHAT_MODEL.startswith("gemini-3"):
        options["temperature"] = temperature
    if max_output_tokens:
        options["max_output_tokens"] = max_output_tokens
    config = types.GenerateContentConfig(
        system_instruction=system_instruction, **options
    )
    fallback_model = FALLBACK_MODEL if fallback and FALLBACK_MODEL != CHAT_MODEL else ""
    try:
        response, model = _generate(
            prompt, config, tag, pace, max_retries, timeout_seconds, fallback_model
        )
    except GeminiKeyError:
        raise
    except Exception as e:
        log(tag, f"Giving up: {e}")
        raise RuntimeError(friendly_error(e, timeout_seconds)) from e

    text = (response.text or "").strip()
    if finish_reason(response) == "MAX_TOKENS":
        # Cut off mid-sentence: keep the complete lines rather than a dangling fragment
        cut = text.rfind("\n")
        if cut > len(text) // 2:
            text = text[:cut].rstrip()
        log(
            tag,
            f"{model} hit the {max_output_tokens}-token cap; kept {len(text):,} chars.",
        )
    return text, model


def generate_structured(
    prompt: str,
    system_instruction: str,
    schema: Type[T],
    temperature: Optional[float],
    tag: str,
    pace: bool = True,
    max_retries: int = MAX_RETRIES,
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
    fallback: bool = False,
) -> T:
    """
    Calls Gemini Flash in JSON mode with a pydantic schema, with timeout, pacing and logged
    retries. temperature=None leaves the model's default. Background jobs keep the defaults;
    a call a student is waiting on passes pace=False, a shorter timeout and fallback=True.
    """
    from google.genai import types

    options = base_config_options()
    if temperature is not None:
        options["temperature"] = temperature
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=schema,
        **options,
    )
    fallback_model = FALLBACK_MODEL if fallback and FALLBACK_MODEL != CHAT_MODEL else ""
    response, _ = _generate(
        prompt, config, tag, pace, max_retries, timeout_seconds, fallback_model
    )
    if isinstance(response.parsed, schema):
        return response.parsed
    return schema.model_validate_json(response.text or "{}")


def embed_texts(texts: List[str], tag: str) -> List[List[float]]:
    """
    Embeds texts with the same model and 1536-d settings as embedding_engine.generate_embeddings,
    in small paced batches with a hard timeout and logged retries. Raises instead of returning [].
    """
    from google.api_core import retry as api_retry
    from embedding_engine import VALID_MODEL, get_genai

    legacy_genai = get_genai()

    vectors: List[List[float]] = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start : start + EMBED_BATCH_SIZE]
        log(
            tag,
            f"Embedding {start + 1}-{start + len(batch)}/{len(texts)} with {VALID_MODEL}...",
        )

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = legacy_genai.embed_content(
                    model=VALID_MODEL,
                    content=batch,
                    task_type="semantic_similarity",
                    output_dimensionality=EXPECTED_DIMENSIONS,
                    request_options={
                        "timeout": REQUEST_TIMEOUT_SECONDS,
                        # Disable the library's silent built-in retries
                        "retry": api_retry.Retry(
                            predicate=api_retry.if_exception_type()
                        ),
                    },
                )
                batch_vectors = response["embedding"]
                break
            except Exception as e:
                _backoff_or_raise(tag, e, attempt)

        if len(batch_vectors) != len(batch) or any(
            len(v) != EXPECTED_DIMENSIONS for v in batch_vectors
        ):
            raise RuntimeError(
                f"Gemini returned {len(batch_vectors)} vectors; expected {len(batch)} of {EXPECTED_DIMENSIONS} dims."
            )
        vectors.extend(batch_vectors)

        if start + EMBED_BATCH_SIZE < len(texts):
            time.sleep(SECONDS_BETWEEN_EMBED_BATCHES)

    return vectors
