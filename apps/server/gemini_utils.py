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
from typing import List, Type, TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel

SERVER_DIR = Path(__file__).resolve().parent

CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-1.5-flash")
REQUEST_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "60"))
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


def _generate(
    prompt: str,
    config,
    tag: str,
    pace: bool,
    max_retries: int,
):
    client = _get_client()
    for attempt in range(1, max_retries + 1):
        if pace:
            _pace(tag)
        started = time.monotonic()
        log(
            tag,
            f"Calling {CHAT_MODEL} (attempt {attempt}, timeout {REQUEST_TIMEOUT_SECONDS}s)...",
        )
        try:
            response = client.models.generate_content(
                model=CHAT_MODEL, contents=prompt, config=config
            )
            log(tag, f"Gemini responded in {time.monotonic() - started:.1f}s.")
            return response
        except Exception as e:
            _backoff_or_raise(tag, e, attempt, max_retries)
    raise RuntimeError("Gemini returned no response.")


def generate_text(
    prompt: str,
    system_instruction: str,
    temperature: float,
    tag: str,
    pace: bool = False,
    max_retries: int = 3,
) -> str:
    """Plain-text Gemini Flash call with a hard timeout and logged retries (used by /chat/ask)."""
    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=system_instruction, temperature=temperature
    )
    response = _generate(prompt, config, tag, pace, max_retries)
    return (response.text or "").strip()


def generate_structured(
    prompt: str,
    system_instruction: str,
    schema: Type[T],
    temperature: float,
    tag: str,
) -> T:
    """Calls Gemini Flash in JSON mode with a pydantic schema, with timeout, pacing and logged retries."""
    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=schema,
    )
    response = _generate(prompt, config, tag, pace=True, max_retries=MAX_RETRIES)
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
