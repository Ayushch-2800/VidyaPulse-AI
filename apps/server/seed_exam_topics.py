import json
from pathlib import Path

from storage_utils import supabase
from embedding_engine import generate_embeddings

SEED_FILE = Path(__file__).resolve().parent / "seeds" / "exam_topics.json"
EMBED_BATCH_SIZE = 100  # Gemini batch-embedding request limit


def topic_embedding_text(row: dict) -> str:
    """The text we embed for a topic; cheat-sheet items are compared against this."""
    return f"{row['exam']} {row['subject']}: {row['topic']}"


def seed_exam_topics() -> int:
    """
    Embeds every seeded exam topic once with the same 1536-d Gemini model used for
    lecture chunks and upserts it into exam_topics. Safe to re-run after editing the JSON.
    """
    rows = json.loads(SEED_FILE.read_text())
    seeded = 0

    for start in range(0, len(rows), EMBED_BATCH_SIZE):
        batch = rows[start : start + EMBED_BATCH_SIZE]
        embeddings = generate_embeddings([topic_embedding_text(r) for r in batch])
        if len(embeddings) != len(batch):
            raise RuntimeError(
                f"Embedding failed for topics {start}-{start + len(batch)}"
            )

        payload = [{**row, "embedding": emb} for row, emb in zip(batch, embeddings)]
        supabase.table("exam_topics").upsert(
            payload, on_conflict="exam,subject,topic"
        ).execute()
        seeded += len(payload)
        print(f"[SEED] Upserted {seeded}/{len(rows)} exam topics")

    return seeded


if __name__ == "__main__":
    seed_exam_topics()
