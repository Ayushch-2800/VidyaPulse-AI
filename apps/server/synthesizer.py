import re
import time
from typing import List, Dict, Any, Optional, Tuple

import cache

# CHAT_MODEL is the free-tier Gemini Flash model (GEMINI_CHAT_MODEL env), re-exported for the engines
from gemini_utils import (
    CHAT_MODEL,
    INTERACTIVE_TIMEOUT_SECONDS,
    MAX_ANSWER_TOKENS,
    generate_text,
)
from storage_utils import supabase
from query_router import hybrid_intelligent_router

NOT_COVERED = "Not covered in this lecture."
MAX_CONTEXT_CHARS = (
    24000  # Keeps the prompt small so we stay well inside free-tier token limits
)
# An overview needs the gist of each part, not every word: each sampled block is trimmed to
# this, so the prompt is about 11k chars instead of 15-24k and the free tier answers it sooner
OVERVIEW_BLOCK_CHARS = 1000
OVERVIEW_CONTEXT_CHARS = 12000
TIMESTAMP_TOLERANCE_SECONDS = 5.0

# Matches [MM:SS] (minutes may exceed 59 for long lectures, e.g. [125:30])
TIMESTAMP_PATTERN = re.compile(r"\[(\d{1,3}):([0-5]\d)\]")
# Fallback: the chunker writes "### Spoken Transcript (12.3s - 45.6s)" into composite_content
COMPOSITE_RANGE_PATTERN = re.compile(r"\((\d+(?:\.\d+)?)s\s*-\s*(\d+(?:\.\d+)?)s\)")
# The chunker puts the slide OCR after this heading, below the spoken transcript
VISUAL_HEADING = "### Visual Blackboard / Slide Context:"

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


def chunk_time_entries(rows: List[Dict[str, Any]]) -> Dict[str, list]:
    """chunk id -> [chunk_index, start, end], the compact form the cache stores."""
    return {
        str(row["id"]): [
            row.get("chunk_index"),
            row.get("start_time_seconds"),
            row.get("end_time_seconds"),
        ]
        for row in rows
        if row.get("id") is not None
    }


def remember_chunk_times(lecture_id: str, rows: List[Dict[str, Any]]) -> None:
    """Caches a lecture's chunk time ranges, so citing its answers needs no lookup."""
    times = chunk_time_entries(rows)
    if times:
        cache.set_json(
            cache.lecture_key("chunk-times", lecture_id),
            times,
            cache.SEARCH_TTL_SECONDS,
        )


def lecture_chunk_times(lecture_id: str) -> Dict[str, Dict[str, Any]]:
    """
    Task 19: Every chunk's time range for one lecture, read once and then served from the cache.
    A few small columns per chunk, so even a 4-hour lecture is one quick query.
    """
    key = cache.lecture_key("chunk-times", lecture_id)
    times = cache.get_json(key)
    if times is None:
        res = (
            supabase.table("multimodal_chunks")
            .select("id, chunk_index, start_time_seconds, end_time_seconds")
            .eq("lecture_id", lecture_id)
            .order("chunk_index")
            .execute()
        )
        times = chunk_time_entries(res.data or [])
        if times:
            cache.set_json(key, times, cache.SEARCH_TTL_SECONDS)
    return {
        chunk_id: {
            "chunk_index": index,
            "start_time_seconds": start,
            "end_time_seconds": end,
        }
        for chunk_id, (index, start, end) in times.items()
    }


def hydrate_timestamps(
    context_blocks: List[Dict[str, Any]], lecture_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    The match_multimodal_chunks RPC only returns id, composite_content and similarity,
    so we look up start/end seconds by id without touching the RPC. If that lookup
    fails, we fall back to the time range the chunker embedded in composite_content.
    Blocks that already carry their times (literal and overview routes) need no lookup, and
    with a lecture_id the lookup is the lecture's cached time map instead of a query.
    """
    missing = [
        block["id"]
        for block in context_blocks
        if block.get("id") is not None and block.get("start_time_seconds") is None
    ]
    time_map: Dict[Any, Dict[str, Any]] = {}

    if missing:
        try:
            if lecture_id:
                times = lecture_chunk_times(lecture_id)
                time_map = {i: times[str(i)] for i in missing if str(i) in times}
            else:
                res = (
                    supabase.table("multimodal_chunks")
                    .select("id, chunk_index, start_time_seconds, end_time_seconds")
                    .in_("id", missing)
                    .execute()
                )
                time_map = {row["id"]: row for row in (res.data or [])}
        except Exception as e:
            print(f"[SYNTHESIZER WARNING] Timestamp lookup failed, using fallback: {e}")

    hydrated = []
    for block in context_blocks:
        row = time_map.get(block.get("id")) or block
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


def shorten(text: str, limit: int) -> str:
    """Cuts text to about `limit` chars at a word boundary."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " …"


def trim_block(body: str, limit: int) -> str:
    """Keeps the start of the transcript (2/3 of the budget) and of the slide text (1/3)."""
    if len(body) <= limit:
        return body
    transcript, _, visual = body.partition(VISUAL_HEADING)
    if not visual.strip():
        return shorten(body, limit)
    return (
        f"{shorten(transcript, limit * 2 // 3)}\n\n"
        f"{VISUAL_HEADING}\n{shorten(visual, limit // 3)}"
    )


def build_context_prompt(
    blocks: List[Dict[str, Any]],
    max_chars: int = MAX_CONTEXT_CHARS,
    max_block_chars: Optional[int] = None,
) -> str:
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
        if max_block_chars:
            body = trim_block(body, max_block_chars)
        entry = f"{header}\n{body}"

        if used_chars + len(entry) > max_chars:
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


def call_gemini(prompt: str) -> Tuple[str, str]:
    """
    Calls Gemini Flash for a student who is waiting: a short deadline, a capped answer length,
    and a switch to the faster fallback model after a timeout. Returns (answer, model).
    """
    return generate_text(
        prompt,
        SYSTEM_PROMPT,
        temperature=0.2,
        tag="SYNTHESIZER",
        max_output_tokens=MAX_ANSWER_TOKENS,
        timeout_seconds=INTERACTIVE_TIMEOUT_SECONDS,
        fallback=True,
    )


def synthesize_answer(
    query: str, lecture_id: str, use_cache: bool = True
) -> Dict[str, Any]:
    """
    Task 14: Routes the query (Task 13), then generates a grounded,
    timestamp-cited answer from the retrieved multimodal chunks.
    Task 19: a grounded answer is cached per lecture and question, so asking the same thing
    again (any case or spacing) returns at once with no Gemini call. use_cache=False always
    writes a fresh answer, e.g. when the student presses Regenerate on the summary.
    """
    started = time.perf_counter()
    answer_key = cache.lecture_key(
        "answer", lecture_id, CHAT_MODEL, cache.text_hash(query)
    )
    if use_cache:
        stored = cache.get_json(answer_key)
        if stored is not None:
            print("[SYNTHESIZER] Answer served from the cache (no Gemini call).")
            return {
                **stored,
                "cached": True,
                "timings_ms": {"total_ms": elapsed_ms(started)},
            }

    routed = hybrid_intelligent_router(query, lecture_id)
    context_blocks = routed["context_blocks"]
    timings = dict(routed.get("timings_ms") or {})

    # No retrieved context means nothing to ground on, so skip the Gemini call entirely
    if not context_blocks:
        return {
            "query": query,
            "intent": routed["intent"],
            "answer": NOT_COVERED,
            "grounded": False,
            "citations": [],
            "sources": [],
            "model": None,
            "cached": False,
            "timings_ms": {**timings, "total_ms": elapsed_ms(started)},
        }

    step = time.perf_counter()
    blocks = hydrate_timestamps(context_blocks, lecture_id)
    timings["timestamps_ms"] = elapsed_ms(step)
    overview = routed["intent"] == "overview"
    if overview:
        context = build_context_prompt(
            blocks, OVERVIEW_CONTEXT_CHARS, OVERVIEW_BLOCK_CHARS
        )
    else:
        context = build_context_prompt(blocks)
    prompt = f"LECTURE CONTEXT:\n\n{context}\n\nSTUDENT QUESTION:\n{query}"
    if overview:
        prompt += (
            f"\n\nNOTE: The student wants an overview. The {len(blocks)} blocks above are excerpts sampled "
            "evenly across the whole lecture, in order. Summarize the lecture's main topics in the order they "
            "are taught, citing each block's timestamp. Keep it under 250 words: one sentence on what the "
            "lecture is about, then at most 8 bullet points. Do not reply that it is not covered."
        )

    print(
        f"[SYNTHESIZER] Generating answer with {CHAT_MODEL} from {len(blocks)} blocks..."
    )
    step = time.perf_counter()
    raw_answer, model = call_gemini(prompt)
    timings["generation_ms"] = elapsed_ms(step)

    if not raw_answer or NOT_COVERED.lower() in raw_answer.lower():
        answer, citations, grounded = NOT_COVERED, [], False
    else:
        answer, citations = validate_citations(raw_answer, blocks)
        grounded = True

    result = {
        "query": query,
        "intent": routed["intent"],
        "answer": answer,
        "grounded": grounded,
        "citations": citations,
        "model": model,
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
    # A "Not covered" reply may be Gemini having a bad moment, so only grounded answers are kept
    if use_cache and grounded:
        cache.set_json(answer_key, result, cache.ANSWER_TTL_SECONDS)
    timings["total_ms"] = elapsed_ms(started)
    print(
        "[SYNTHESIZER] Timings (ms): "
        + ", ".join(f"{k[:-3]} {v:.0f}" for k, v in timings.items())
    )
    return {**result, "cached": False, "timings_ms": timings}


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
