import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

SERVER_DIR = Path(__file__).resolve().parent
SEED_FILE = SERVER_DIR / "seeds" / "exam_topics.json"

# Free-tier pacing: small batches with a pause between them keeps us well under the RPM quota
EMBED_BATCH_SIZE = 10
SECONDS_BETWEEN_BATCHES = 4
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
EXPECTED_DIMENSIONS = 1536


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    print(f"\n[SEED ERROR] {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def check_environment() -> None:
    """Loads apps/server/.env and stops immediately if a required key is missing."""
    env_path = SERVER_DIR / ".env"
    load_dotenv(dotenv_path=env_path)
    log(
        f"[SEED] Loaded environment from {env_path}"
        if env_path.exists()
        else f"[SEED] No .env at {env_path}; using shell environment variables"
    )

    missing = [
        key
        for key in (
            "NEXT_PUBLIC_SUPABASE_URL",
            "SUPABASE_SERVICE_ROLE_KEY",
            "GEMINI_API_KEY",
        )
        if not os.getenv(key, "").strip()
    ]
    if missing:
        fail(
            f"Missing environment variables: {', '.join(missing)}. Add them to {env_path}."
        )


def topic_embedding_text(row: dict) -> str:
    """The text we embed for a topic; cheat-sheet items are compared against this."""
    return f"{row['exam']} {row['subject']}: {row['topic']}"


def embed_batch(genai, model: str, texts: list) -> list:
    """
    Embeds one batch with the same model and 1536-d settings as embedding_engine.generate_embeddings,
    but with a hard timeout, visible retries on 429/503, and loud failure on bad keys.
    """
    from google.api_core import retry as api_retry

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = genai.embed_content(
                model=model,
                content=texts,
                task_type="semantic_similarity",
                output_dimensionality=EXPECTED_DIMENSIONS,
                request_options={
                    "timeout": REQUEST_TIMEOUT_SECONDS,
                    # Disable the library's silent built-in retries; we retry below with logging
                    "retry": api_retry.Retry(predicate=api_retry.if_exception_type()),
                },
            )
            return response["embedding"]
        except Exception as e:
            error = str(e)
            if any(
                s in error
                for s in (
                    "API_KEY_INVALID",
                    "API key not valid",
                    "PERMISSION_DENIED",
                    "403",
                )
            ):
                fail(f"Gemini rejected GEMINI_API_KEY: {error}")
            retryable = any(
                s in error
                for s in (
                    "429",
                    "RESOURCE_EXHAUSTED",
                    "503",
                    "UNAVAILABLE",
                    "Deadline",
                    "timed out",
                )
            )
            if not retryable or attempt == MAX_RETRIES:
                fail(f"Gemini embedding failed after {attempt} attempt(s): {error}")
            wait = SECONDS_BETWEEN_BATCHES * 2**attempt
            log(
                f"[SEED]   Gemini rate limit or timeout ({error[:80]}). Retry {attempt}/{MAX_RETRIES - 1} in {wait}s..."
            )
            time.sleep(wait)


def seed_exam_topics() -> int:
    """
    Embeds every seeded exam topic once with the same 1536-d Gemini model used for lecture
    chunks and upserts it into exam_topics. Topics that already have an embedding are skipped,
    so a run interrupted by rate limits can simply be re-run.
    """
    check_environment()

    log("[SEED] Connecting to Supabase...")
    from storage_utils import supabase

    try:
        existing = (
            supabase.table("exam_topics")
            .select("exam, subject, topic, embedding")
            .execute()
        )
    except Exception as e:
        fail(
            f"Supabase query on exam_topics failed: {e}\n"
            "Check NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY, and that migrations/004_cheat_sheets.sql has been run."
        )
    done = {
        (r["exam"], r["subject"], r["topic"])
        for r in (existing.data or [])
        if r.get("embedding")
    }
    log(f"[SEED] Supabase OK. {len(done)} topics already embedded.")

    log("[SEED] Configuring Gemini (same embedding model used for lecture chunks)...")
    from embedding_engine import VALID_MODEL, get_genai

    genai = get_genai()
    log(f"[SEED] Using embedding model {VALID_MODEL}")

    rows = json.loads(SEED_FILE.read_text())
    todo = [r for r in rows if (r["exam"], r["subject"], r["topic"]) not in done]
    if not todo:
        log(f"[SEED] All {len(rows)} topics are already embedded. Nothing to do.")
        return 0
    log(
        f"[SEED] Embedding {len(todo)} of {len(rows)} topics in batches of {EMBED_BATCH_SIZE}..."
    )

    seeded = 0
    for start in range(0, len(todo), EMBED_BATCH_SIZE):
        batch = todo[start : start + EMBED_BATCH_SIZE]
        log(
            f"[SEED] Embedding topics {start + 1}-{start + len(batch)}/{len(todo)}: {batch[0]['topic']} ..."
        )

        embeddings = embed_batch(
            genai, VALID_MODEL, [topic_embedding_text(r) for r in batch]
        )
        if len(embeddings) != len(batch) or any(
            len(e) != EXPECTED_DIMENSIONS for e in embeddings
        ):
            fail(
                f"Gemini returned {len(embeddings)} vectors of {len(embeddings[0]) if embeddings else 0} dims; "
                f"expected {len(batch)} of {EXPECTED_DIMENSIONS}."
            )

        try:
            supabase.table("exam_topics").upsert(
                [{**row, "embedding": emb} for row, emb in zip(batch, embeddings)],
                on_conflict="exam,subject,topic",
            ).execute()
        except Exception as e:
            fail(f"Supabase upsert failed: {e}")

        seeded += len(batch)
        log(f"[SEED]   Saved {seeded}/{len(todo)}")

        if start + EMBED_BATCH_SIZE < len(todo):
            time.sleep(SECONDS_BETWEEN_BATCHES)

    log(f"[SEED] Done. Embedded and saved {seeded} topics.")
    return seeded


if __name__ == "__main__":
    seed_exam_topics()
