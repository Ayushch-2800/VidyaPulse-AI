"""Synthetic lectures for edge-case tests: a 4-hour code-mixed transcript with slides."""

from typing import Any, Dict, List

from fakes import fake_vector

FOUR_HOURS = 4 * 3600
# Whisper segments run 3-8 s; 6 s at ~150 words a minute is about 15 words each
SEGMENT_SECONDS = 6.0
TOPICS = [
    "limits and continuity",
    "the derivative as a rate of change",
    "the chain rule for composite functions",
    "integration by parts",
    "definite integrals and area",
    "differential equations",
    "taylor series expansion",
    "vectors and the dot product",
]
# Code-mixed lines, as Whisper writes Hinglish and Tamil-English
FILLERS = [
    "toh students yeh concept bahut important hai exam ke liye",
    "so let us write the formula on the board carefully",
    "இப்போது நாம் இந்த example பார்ப்போம் okay",
    "ab dekhiye agar hum x ko zero ke paas le jaayen",
    "notice how each term simplifies when we substitute",
]


def topic_at(seconds: float) -> str:
    return TOPICS[int(seconds // (FOUR_HOURS / len(TOPICS))) % len(TOPICS)]


def four_hour_transcript() -> List[Dict[str, Any]]:
    segments = []
    t, i = 0.0, 0
    while t < FOUR_HOURS:
        end = min(t + SEGMENT_SECONDS, FOUR_HOURS)
        segments.append(
            {
                "start_time_seconds": t,
                "end_time_seconds": end,
                "text": f"{topic_at(t)} {FILLERS[i % len(FILLERS)]}",
            }
        )
        t, i = end, i + 1
    return segments


def four_hour_keyframes(every_seconds: float = 90.0) -> List[Dict[str, Any]]:
    return [
        {
            "timestamp_seconds": float(t),
            "storage_path": f"user/lec-4h/{int(t)}.jpg",
            "extracted_text": f"Slide: {topic_at(t)} $$\\int_0^{{{int(t)}}} f(x)\\,dx$$",
        }
        for t in range(0, FOUR_HOURS, int(every_seconds))
    ]


def seed_four_hour_lecture(db, lecture_id: str = "lec-4h") -> List[Dict[str, Any]]:
    """Chunks a 4-hour lecture with the real chunker and stores it, embedded, in the fake db."""
    from temporal_chunker import align_multimodal_chunks

    chunks = align_multimodal_chunks(
        four_hour_transcript(), four_hour_keyframes(), lecture_id, 300, 50, "hi"
    )
    db.seed(
        "lectures",
        [{"id": lecture_id, "user_id": "user-1", "title": "4-hour marathon"}],
    )
    return db.seed(
        "multimodal_chunks",
        [
            {
                "lecture_id": lecture_id,
                "chunk_index": c["chunk_index"],
                "start_time_seconds": c["start_time_seconds"],
                "end_time_seconds": c["end_time_seconds"],
                "duration_seconds": c["duration_seconds"],
                "transcript_text": c["transcript_text"],
                "visual_context_count": c["visual_context_count"],
                "composite_content": c["composite_content"],
                "language": c["language"],
                "embedding": fake_vector(c["composite_content"]),
            }
            for c in chunks
        ],
    )
