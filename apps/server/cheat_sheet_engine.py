import sys

if __name__ == "__main__":
    # Check keys before the imports below open Supabase and Gemini connections
    from gemini_utils import check_environment, preload

    print("[CHEATSHEET] Starting...", flush=True)
    try:
        check_environment("CHEATSHEET")
    except EnvironmentError as e:
        print(f"\n[CHEATSHEET ERROR] {e}", file=sys.stderr, flush=True)
        sys.exit(1)
    # Imports Supabase and Gemini step by step, so a stall names the exact step
    preload("CHEATSHEET")

import json
import math
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, Field

from storage_utils import supabase
from gemini_utils import GeminiKeyError, embed_texts, generate_structured, log
from synthesizer import CHAT_MODEL, TIMESTAMP_PATTERN, format_timestamp

TAG = "CHEATSHEET"

# ~12k characters per Gemini call keeps a 1-hour lecture to roughly 5 requests
MAX_BATCH_CHARS = 12000
TOPIC_MATCH_THRESHOLD = 0.6  # Cosine similarity; tune after seeding real PYQ topics
TOPICS_PER_ITEM = 3
LECTURE_TOPIC_LIMIT = 10

ITEM_KINDS = ("definition", "theorem", "formula")


class CheatSheetItem(BaseModel):
    kind: str = Field(description="One of: definition, theorem, formula")
    title: str = Field(description="Short name, e.g. 'Chain rule' or 'Ohm's law'")
    latex: str = Field(
        description="The exact LaTeX of the formula or statement, without $ delimiters. Empty string if there is no math."
    )
    explanation: str = Field(
        description="One or two sentences on what it means or when to use it, as taught in the lecture"
    )
    timestamp: str = Field(
        description="The MM:SS label of the chunk it came from, copied from that chunk's header"
    )


class CheatSheetBatch(BaseModel):
    items: List[CheatSheetItem]


EXTRACTION_PROMPT = """
You are building an exam cheat sheet from ONE lecture's transcript and slide OCR.

Extract every core definition, theorem/law/rule, and formula that the lecture explicitly states, writes on a slide, or derives.

Strictly follow these rules:
1. Use ONLY the lecture chunks provided. Never add items from outside knowledge, even if they are related.
2. Copy LaTeX from the slide context exactly. If a formula is only spoken, write it in standard LaTeX.
3. Put the LaTeX in the "latex" field WITHOUT surrounding $ or $$ delimiters.
4. Set "timestamp" to the MM:SS label from the header of the chunk where the item appears. Never invent one.
5. The transcript may be code-mixed (Hinglish, Tamil-English, etc.). Write titles and explanations in English.
6. Skip greetings, examples with only numbers, and administrative talk. If nothing qualifies, return an empty list.
""".strip()


def fetch_lecture_chunks(lecture_id: str) -> List[Dict[str, Any]]:
    """Reads every chunk in lecture order. A cheat sheet must cover the whole lecture, so no vector search."""
    res = (
        supabase.table("multimodal_chunks")
        .select("chunk_index, start_time_seconds, end_time_seconds, composite_content")
        .eq("lecture_id", lecture_id)
        .order("chunk_index")
        .execute()
    )
    return res.data or []


def batch_chunks(chunks: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Groups consecutive chunks so each Gemini call stays under MAX_BATCH_CHARS."""
    batches, current, size = [], [], 0
    for chunk in chunks:
        length = len(chunk.get("composite_content") or "")
        if current and size + length > MAX_BATCH_CHARS:
            batches.append(current)
            current, size = [], 0
        current.append(chunk)
        size += length
    if current:
        batches.append(current)
    return batches


def build_batch_prompt(batch: List[Dict[str, Any]]) -> str:
    parts = []
    for chunk in batch:
        start = float(chunk.get("start_time_seconds") or 0.0)
        end = float(chunk.get("end_time_seconds") or start)
        parts.append(
            f"--- Chunk | timestamp {format_timestamp(start)} | covers {format_timestamp(start)} to {format_timestamp(end)} ---\n"
            f"{(chunk.get('composite_content') or '').strip()}"
        )
    return "LECTURE CHUNKS:\n\n" + "\n\n".join(parts)


def call_gemini_structured(prompt: str) -> List[CheatSheetItem]:
    """Calls Gemini Flash in JSON mode with the CheatSheetBatch schema (timeout, pacing, logged retries)."""
    return generate_structured(
        prompt, EXTRACTION_PROMPT, CheatSheetBatch, temperature=0.1, tag=TAG
    ).items


def resolve_timestamp(label: str, batch: List[Dict[str, Any]]) -> Optional[float]:
    """Returns the LLM's MM:SS label in seconds if it falls inside a chunk of this batch, else None (invented)."""
    match = TIMESTAMP_PATTERN.fullmatch(f"[{label.strip().strip('[]')}]")
    if not match:
        return None
    seconds = int(match.group(1)) * 60 + int(match.group(2))
    for chunk in batch:
        start = float(chunk.get("start_time_seconds") or 0.0)
        end = float(chunk.get("end_time_seconds") or start)
        if start - 5 <= seconds <= end + 5:
            return float(seconds)
    return None


def normalize_key(item: Dict[str, Any]) -> str:
    """Dedupe key: the LaTeX with whitespace removed, else the lowercased title."""
    latex = re.sub(r"\s+", "", item["latex"])
    return f"{item['kind']}:{latex or item['title'].strip().lower()}"


def extract_items(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map: one structured Gemini call per batch. Reduce: dedupe in Python with no extra LLM call."""
    seen: Dict[str, Dict[str, Any]] = {}

    batches = batch_chunks(chunks)
    for i, batch in enumerate(batches, start=1):
        start = format_timestamp(float(batch[0].get("start_time_seconds") or 0))
        end = format_timestamp(float(batch[-1].get("end_time_seconds") or 0))
        log(
            TAG,
            f"Gemini call {i}/{len(batches)}: {len(batch)} chunks covering {start}-{end}...",
        )
        raw_items = call_gemini_structured(build_batch_prompt(batch))
        log(TAG, f"  Batch {i}/{len(batches)} returned {len(raw_items)} items.")
        for raw in raw_items:
            kind = raw.kind.strip().lower()
            if kind not in ITEM_KINDS or not raw.title.strip():
                continue
            item = {
                "kind": kind,
                "title": raw.title.strip(),
                "latex": raw.latex.strip().strip("$").strip(),
                "explanation": raw.explanation.strip(),
                "timestamp_seconds": resolve_timestamp(raw.timestamp, batch),
            }
            # The 50-word chunk overlap repeats items; keep the earliest occurrence
            seen.setdefault(normalize_key(item), item)

    log(
        TAG,
        f"Extraction done: {len(seen)} unique items after removing overlap duplicates.",
    )
    return list(seen.values())


def parse_vector(value: Any) -> List[float]:
    """pgvector columns come back from PostgREST as a '[0.1,0.2,...]' string."""
    return json.loads(value) if isinstance(value, str) else list(value or [])


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def tag_exam_topics(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Tags each item with the closest seeded exam topics by cosine similarity, and returns
    lecture-level tags. Uses embeddings only (no generation calls). Skips if no topics are seeded.
    """
    log(TAG, "Loading seeded exam topics from Supabase...")
    res = (
        supabase.table("exam_topics")
        .select("id, exam, subject, topic, embedding")
        .execute()
    )
    topics = [
        {**row, "embedding": parse_vector(row["embedding"])}
        for row in (res.data or [])
        if row.get("embedding")
    ]
    if not topics or not items:
        if not topics:
            log(
                TAG,
                "No embedded exam topics found; skipping tagging (run seed_exam_topics.py).",
            )
        for item in items:
            item["exam_topics"] = []
        return []

    log(TAG, f"Tagging {len(items)} items against {len(topics)} exam topics...")
    texts = [f"{i['title']}: {i['explanation']} {i['latex']}".strip() for i in items]
    item_vectors = embed_texts(texts, tag=TAG)

    lecture_scores: Dict[int, Dict[str, Any]] = {}
    for item, vector in zip(items, item_vectors):
        scored = sorted(
            ((cosine_similarity(vector, t["embedding"]), t) for t in topics),
            key=lambda pair: pair[0],
            reverse=True,
        )
        matches = [
            {
                "exam": t["exam"],
                "subject": t["subject"],
                "topic": t["topic"],
                "similarity": round(score, 3),
            }
            for score, t in scored[:TOPICS_PER_ITEM]
            if score >= TOPIC_MATCH_THRESHOLD
        ]
        item["exam_topics"] = matches

        for score, t in scored[:TOPICS_PER_ITEM]:
            if score < TOPIC_MATCH_THRESHOLD:
                continue
            entry = lecture_scores.setdefault(
                t["id"],
                {
                    "exam": t["exam"],
                    "subject": t["subject"],
                    "topic": t["topic"],
                    "item_count": 0,
                    "best_similarity": 0.0,
                },
            )
            entry["item_count"] += 1
            entry["best_similarity"] = max(entry["best_similarity"], round(score, 3))

    return sorted(
        lecture_scores.values(),
        key=lambda e: (e["item_count"], e["best_similarity"]),
        reverse=True,
    )[:LECTURE_TOPIC_LIMIT]


def save_cheat_sheet(lecture_id: str, **fields: Any) -> None:
    supabase.table("cheat_sheets").upsert(
        {
            "lecture_id": lecture_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        },
        on_conflict="lecture_id",
    ).execute()


def generate_cheat_sheet(lecture_id: str) -> Dict[str, Any]:
    """
    Task 15 background worker: builds the structured cheat sheet for one lecture and stores it
    in cheat_sheets. Runs after ingestion completes, or on demand via the API.
    """
    log(TAG, f"--- GENERATING CHEAT SHEET FOR LECTURE {lecture_id} ---")

    try:
        try:
            save_cheat_sheet(
                lecture_id, status="processing", error=None, model=CHAT_MODEL
            )
        except Exception as e:
            raise RuntimeError(
                f"Supabase write to cheat_sheets failed ({e}). Check NEXT_PUBLIC_SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY, and that migrations/004_cheat_sheets.sql has been run."
            ) from e
        log(TAG, "Fetching lecture chunks from Supabase...")
        chunks = fetch_lecture_chunks(lecture_id)
        if not chunks:
            raise ValueError(
                "No indexed chunks found for this lecture. Check the lecture id and that ingestion completed."
            )
        log(
            TAG,
            f"Found {len(chunks)} chunks; {len(batch_chunks(chunks))} Gemini call(s) needed.",
        )

        items = extract_items(chunks)
        topic_tags = tag_exam_topics(items)

        content = {kind + "s": [] for kind in ITEM_KINDS}
        for item in sorted(
            items,
            key=lambda i: (i["timestamp_seconds"] is None, i["timestamp_seconds"] or 0),
        ):
            content[item["kind"] + "s"].append(item)

        log(TAG, "Saving cheat sheet to Supabase...")
        save_cheat_sheet(
            lecture_id, status="completed", content=content, topic_tags=topic_tags
        )
        log(
            TAG,
            f"--- CHEAT SHEET COMPLETE: {len(content['definitions'])} definitions, "
            f"{len(content['theorems'])} theorems, {len(content['formulas'])} formulas ---",
        )
        return {"status": "completed", "content": content, "topic_tags": topic_tags}

    except Exception as e:
        kind = "INVALID GEMINI KEY" if isinstance(e, GeminiKeyError) else "ERROR"
        print(f"\n[CHEATSHEET {kind}] {e}", file=sys.stderr, flush=True)
        try:
            save_cheat_sheet(lecture_id, status="failed", error=str(e))
        except Exception as save_error:
            print(
                f"[CHEATSHEET ERROR] Could not record the failure in Supabase: {save_error}",
                file=sys.stderr,
                flush=True,
            )
        return {"status": "failed", "error": str(e)}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python cheat_sheet_engine.py <lecture_id>")
        sys.exit(1)
    result = generate_cheat_sheet(sys.argv[1])
    sys.exit(0 if result["status"] == "completed" else 1)
