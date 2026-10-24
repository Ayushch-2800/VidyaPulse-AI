import os
import re
import time
from typing import List, Dict, Any, Tuple

from google import genai
from google.genai import types

from storage_utils import supabase
from query_router import hybrid_intelligent_router

# Same free-tier Gemini key as the OCR engine. Override the model via env if Google renames it.
CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.8-flash")
NOT_COVERED = "Not covered in this lecture."
MAX_CONTEXT_CHARS = (
    24000  # Keeps the prompt small so we stay well inside free-tier token limits
)
TIMESTAMP_TOLERANCE_SECONDS = 5.0

# Matches [MM:SS] (minutes may exceed 59 for long lectures, e.g. [125:30])
TIMESTAMP_PATTERN = re.compile(r"\[(\d{1,3}):([0-5]\d)\]")
# Fallback: the chunker writes "### Spoken Transcript (12.3s - 45.6s)" into composite_content
COMPOSITE_RANGE_PATTERN = re.compile(r"\((\d+(?:\.\d+)?)s\s*-\s*(\d+(?:\.\d+)?)s\)")

SYSTEM_PROMPT = f"""
You are VidyaPulse AI, a study assistant that answers questions about ONE lecture.

Strictly follow these rules:
1. Answer ONLY from the lecture context blocks provided. Never use outside knowledge, even if you know the answer.
2. Every factual sentence must cite where it came from using the timestamp of its context block in [MM:SS] format, e.g. "The derivative of sin x is cos x [04:12]."
3. Only use timestamps that appear in the context block headers. Never invent timestamps.
4. If the context does not contain the answer, reply with exactly: "{NOT_COVERED}" and nothing else. A request to summarize or give an overview of the lecture is always answerable from the context provided.
5. Preserve all mathematics as LaTeX: use $...$ for inline math and $$...$$ for block equations. Copy formulas from the slide context exactly.
6. The spoken transcript may be code-mixed (Hinglish, Tamil-English, etc.). Reply in the language the student used in their question.
7. Be concise and structured. Use short markdown paragraphs or bullet points. No conversational filler.
""".strip()


def format_timestamp(seconds: float) -> str:
    """Converts raw seconds into the [MM:SS] citation format."""
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def hydrate_timestamps(context_blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    The match_multimodal_chunks RPC only returns id, composite_content and similarity,
    so we look up start/end seconds by id without touching the RPC. If that lookup
    fails, we fall back to the time range the chunker embedded in composite_content.
    """
    ids = [block["id"] for block in context_blocks if block.get("id") is not None]
    time_map: Dict[Any, Dict[str, Any]] = {}

    if ids:
        try:
            res = (
                supabase.table("multimodal_chunks")
                .select("id, chunk_index, start_time_seconds, end_time_seconds")
                .in_("id", ids)
                .execute()
            )
            time_map = {row["id"]: row for row in (res.data or [])}
        except Exception as e:
            print(f"[SYNTHESIZER WARNING] Timestamp lookup failed, using fallback: {e}")

    hydrated = []
    for block in context_blocks:
        row = time_map.get(block.get("id"), {})
        start = row.get("start_time_seconds")
        end = row.get("end_time_seconds")

        if start is None:
            match = COMPOSITE_RANGE_PATTERN.search(block.get("composite_content", ""))
            if match:
                start, end = float(match.group(1)), float(match.group(2))

        hydrated.append(
            {
                **block,
                "chunk_index": row.get("chunk_index"),
                "start_time_seconds": float(start) if start is not None else None,
                "end_time_seconds": float(end) if end is not None else None,
            }
        )

    # Present the lecture to the LLM in chronological order
    hydrated.sort(
        key=lambda b: (b["start_time_seconds"] is None, b["start_time_seconds"] or 0)
    )
    return hydrated


def build_context_prompt(blocks: List[Dict[str, Any]]) -> str:
    """Wraps each chunk in a header carrying its [MM:SS] citation label."""
    parts = []
    used_chars = 0

    for i, block in enumerate(blocks, start=1):
        start = block.get("start_time_seconds")
        end = block.get("end_time_seconds")
        if start is not None:
            header = f"--- Context Block {i} | cite as [{format_timestamp(start)}] | covers {format_timestamp(start)} to {format_timestamp(end or start)} ---"
        else:
            header = f"--- Context Block {i} | no timestamp available ---"

        body = block.get("composite_content", "").strip()
        entry = f"{header}\n{body}"

        if used_chars + len(entry) > MAX_CONTEXT_CHARS:
            break
        parts.append(entry)
        used_chars += len(entry)

    return "\n\n".join(parts)


def validate_citations(
    answer: str, blocks: List[Dict[str, Any]]
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Keeps only [MM:SS] citations that fall inside a retrieved chunk's time window,
    and strips any timestamp the LLM hallucinated so the UI never seeks to a wrong spot.
    """
    windows = [
        (b["start_time_seconds"], b["end_time_seconds"] or b["start_time_seconds"], b)
        for b in blocks
        if b.get("start_time_seconds") is not None
    ]
    citations: List[Dict[str, Any]] = []
    seen = set()

    def check(match: re.Match) -> str:
        seconds = int(match.group(1)) * 60 + int(match.group(2))
        for start, end, block in windows:
            if (
                start - TIMESTAMP_TOLERANCE_SECONDS
                <= seconds
                <= end + TIMESTAMP_TOLERANCE_SECONDS
            ):
                if seconds not in seen:
                    seen.add(seconds)
                    citations.append(
                        {
                            "label": match.group(0)[1:-1],
                            "seconds": seconds,
                            "chunk_id": block.get("id"),
                        }
                    )
                return match.group(0)
        print(f"[SYNTHESIZER] Dropping hallucinated citation {match.group(0)}")
        return ""

    cleaned = TIMESTAMP_PATTERN.sub(check, answer)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned).strip()
    return cleaned, citations


def call_gemini(prompt: str, max_retries: int = 4) -> str:
    """Calls Gemini Flash with backoff on free-tier 429/503 responses."""
    client = genai.Client()  # Picks up GEMINI_API_KEY from the environment

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=CHAT_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.2,
                ),
            )
            return (response.text or "").strip()
        except Exception as e:
            retryable = "429" in str(e) or "503" in str(e)
            if retryable and attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5
                print(f"[SYNTHESIZER WARNING] Gemini busy. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise


def synthesize_answer(query: str, lecture_id: str) -> Dict[str, Any]:
    """
    Task 14: Routes the query (Task 13), then generates a grounded,
    timestamp-cited answer from the retrieved multimodal chunks.
    """
    routed = hybrid_intelligent_router(query, lecture_id)
    context_blocks = routed["context_blocks"]

    # No retrieved context means nothing to ground on, so skip the Gemini call entirely
    if not context_blocks:
        return {
            "query": query,
            "intent": routed["intent"],
            "answer": NOT_COVERED,
            "grounded": False,
            "citations": [],
            "sources": [],
        }

    blocks = hydrate_timestamps(context_blocks)
    prompt = (
        f"LECTURE CONTEXT:\n\n{build_context_prompt(blocks)}\n\n"
        f"STUDENT QUESTION:\n{query}"
    )
    if routed["intent"] == "overview":
        prompt += (
            f"\n\nNOTE: The student wants an overview. The {len(blocks)} blocks above are sampled evenly "
            "across the whole lecture, in order. Summarize the lecture's main topics in the order they "
            "are taught, citing each block's timestamp. Do not reply that it is not covered."
        )

    print(
        f"[SYNTHESIZER] Generating answer with {CHAT_MODEL} from {len(blocks)} blocks..."
    )
    raw_answer = call_gemini(prompt)

    if not raw_answer or NOT_COVERED.lower() in raw_answer.lower():
        answer, citations, grounded = NOT_COVERED, [], False
    else:
        answer, citations = validate_citations(raw_answer, blocks)
        grounded = True

    return {
        "query": query,
        "intent": routed["intent"],
        "answer": answer,
        "grounded": grounded,
        "citations": citations,
        "sources": [
            {
                "id": b.get("id"),
                "start_time_seconds": b.get("start_time_seconds"),
                "end_time_seconds": b.get("end_time_seconds"),
                "similarity": b.get("similarity"),
            }
            for b in blocks
        ],
    }
