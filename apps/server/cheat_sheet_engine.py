import json
import math
import re
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from storage_utils import supabase
from embedding_engine import generate_embeddings
from synthesizer import CHAT_MODEL, TIMESTAMP_PATTERN, format_timestamp

# ~12k characters per Gemini call keeps a 1-hour lecture to roughly 5 requests
MAX_BATCH_CHARS = 12000
EMBED_BATCH_SIZE = 100
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


def call_gemini_structured(prompt: str, max_retries: int = 4) -> List[CheatSheetItem]:
    """Calls Gemini Flash in JSON mode with the CheatSheetBatch schema, backing off on 429/503."""
    client = genai.Client()

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=CHAT_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=EXTRACTION_PROMPT,
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=CheatSheetBatch,
                ),
            )
            if isinstance(response.parsed, CheatSheetBatch):
                return response.parsed.items
            return CheatSheetBatch.model_validate_json(response.text or "{}").items
        except Exception as e:
            retryable = "429" in str(e) or "503" in str(e)
            if retryable and attempt < max_retries - 1:
                wait_time = (attempt + 1) * 10
                print(f"[CHEATSHEET WARNING] Gemini busy. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise
    return []


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
        print(
            f"[CHEATSHEET] Extracting batch {i}/{len(batches)} ({len(batch)} chunks)..."
        )
        for raw in call_gemini_structured(build_batch_prompt(batch)):
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
        for item in items:
            item["exam_topics"] = []
        return []

    texts = [f"{i['title']}: {i['explanation']} {i['latex']}".strip() for i in items]
    item_vectors: List[List[float]] = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        item_vectors.extend(
            generate_embeddings(texts[start : start + EMBED_BATCH_SIZE])
        )
    if len(item_vectors) != len(items):
        raise RuntimeError("Failed to embed cheat-sheet items for topic tagging.")

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
    print(f"--- GENERATING CHEAT SHEET FOR LECTURE {lecture_id} ---")
    save_cheat_sheet(lecture_id, status="processing", error=None, model=CHAT_MODEL)

    try:
        chunks = fetch_lecture_chunks(lecture_id)
        if not chunks:
            raise ValueError("No indexed chunks found for this lecture.")

        items = extract_items(chunks)
        topic_tags = tag_exam_topics(items)

        content = {kind + "s": [] for kind in ITEM_KINDS}
        for item in sorted(
            items,
            key=lambda i: (i["timestamp_seconds"] is None, i["timestamp_seconds"] or 0),
        ):
            content[item["kind"] + "s"].append(item)

        save_cheat_sheet(
            lecture_id, status="completed", content=content, topic_tags=topic_tags
        )
        print(
            f"--- CHEAT SHEET COMPLETE: {len(content['definitions'])} definitions, "
            f"{len(content['theorems'])} theorems, {len(content['formulas'])} formulas ---"
        )
        return {"status": "completed", "content": content, "topic_tags": topic_tags}

    except Exception as e:
        print(f"[CHEATSHEET ERROR]: {e}")
        save_cheat_sheet(lecture_id, status="failed", error=str(e))
        return {"status": "failed", "error": str(e)}


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python cheat_sheet_engine.py <lecture_id>")
        sys.exit(1)
    generate_cheat_sheet(sys.argv[1])
