import math
import time

import pytest

from temporal_chunker import (
    align_multimodal_chunks,
    interpolate_word_timestamps,
    visual_only_chunks,
)
from lecture_factory import four_hour_keyframes, four_hour_transcript


def test_interpolation_spreads_words_across_the_segment():
    words = interpolate_word_timestamps(
        [
            {
                "start_time_seconds": 10.0,
                "end_time_seconds": 14.0,
                "text": "one two three four",
            }
        ]
    )
    assert [(w["word"], w["start_time"], w["end_time"]) for w in words] == [
        ("one", 10.0, 11.0),
        ("two", 11.0, 12.0),
        ("three", 12.0, 13.0),
        ("four", 13.0, 14.0),
    ]


def test_interpolation_handles_messy_asr_segments():
    words = interpolate_word_timestamps(
        [
            {
                "start_time": 5.0,
                "end_time": 6.0,
                "text": "later",
            },  # alternate keys, out of order
            {"start_time_seconds": 0.0, "end_time_seconds": 0.0, "text": "zero length"},
            {"start_time_seconds": 2.0, "end_time_seconds": 1.0, "text": "backwards"},
            {"start_time_seconds": 3.0, "end_time_seconds": 4.0, "text": "   "},
            {"start_time_seconds": 3.5, "end_time_seconds": 4.0, "text": None},
        ]
    )
    assert [w["word"] for w in words] == ["zero", "length", "backwards", "later"]
    assert all(w["end_time"] >= w["start_time"] for w in words)


def test_windows_overlap_by_the_configured_word_count():
    segments = [
        {
            "start_time_seconds": float(i),
            "end_time_seconds": float(i + 1),
            "text": f"w{i}",
        }
        for i in range(25)
    ]
    chunks = align_multimodal_chunks(
        segments, [], "lec", window_size=10, overlap_size=4
    )
    assert [c["word_count"] for c in chunks] == [10, 10, 10, 7]
    assert (
        chunks[0]["transcript_text"].split()[-4:]
        == chunks[1]["transcript_text"].split()[:4]
    )
    assert [c["chunk_index"] for c in chunks] == [0, 1, 2, 3]
    assert chunks[-1]["end_time_seconds"] == 25.0


def test_keyframes_bind_to_their_window_with_ocr_in_the_composite():
    segments = [
        {"start_time_seconds": 0.0, "end_time_seconds": 20.0, "text": "a " * 20}
    ]
    keyframes = [
        {
            "timestamp_seconds": 5.0,
            "storage_path": "u/l/1.jpg",
            "extracted_text": "$$E=mc^2$$",
        },
        {
            "timestamp": 8.0,
            "extracted_content": "  ",
        },  # no text: kept as context, not embedded
        {"timestamp_seconds": 99.0, "extracted_text": "outside"},
    ]
    (chunk,) = align_multimodal_chunks(segments, keyframes, "lec", language="hi")
    assert chunk["visual_context_count"] == 2
    assert chunk["language"] == "hi"
    assert chunk["composite_content"].startswith(
        "### Spoken Transcript (0.0s - 20.0s):"
    )
    assert "[Visual at 5.0s]:\n$$E=mc^2$$" in chunk["composite_content"]
    assert "outside" not in chunk["composite_content"]


def test_without_slide_text_the_composite_is_the_transcript():
    segments = [
        {"start_time_seconds": 0.0, "end_time_seconds": 2.0, "text": "plain words"}
    ]
    (chunk,) = align_multimodal_chunks(segments, [], "lec")
    assert chunk["composite_content"] == "plain words"


def test_code_mixed_scripts_survive_chunking():
    text = "आज हम derivative पढ़ेंगे. இன்று நாம் integration படிப்போம். Sine x ka derivative cos x hai."
    (chunk,) = align_multimodal_chunks(
        [{"start_time_seconds": 0.0, "end_time_seconds": 9.0, "text": text}], [], "lec"
    )
    assert chunk["transcript_text"] == " ".join(text.split())


def test_no_speech_falls_back_to_slide_only_chunks():
    keyframes = [
        {
            "timestamp_seconds": 30.0,
            "storage_path": "b.jpg",
            "extracted_text": "Chain rule",
        },
        {"timestamp_seconds": 0.0, "storage_path": "a.jpg", "extracted_text": "Limits"},
        {"timestamp_seconds": 15.0, "extracted_text": ""},
    ]
    chunks = align_multimodal_chunks(
        [{"start_time_seconds": 0, "end_time_seconds": 1, "text": ""}], keyframes, "lec"
    )
    assert [(c["start_time_seconds"], c["end_time_seconds"]) for c in chunks] == [
        (0.0, 30.0),
        (30.0, 30.0),
    ]
    assert chunks[0]["composite_content"] == (
        "### Visual Blackboard / Slide Context (0.0s - 30.0s):\n[Visual at 0.0s]:\nLimits"
    )
    assert chunks[1]["transcript_text"] == "" and chunks[1]["chunk_index"] == 1


def test_no_speech_and_no_slides_gives_nothing():
    assert align_multimodal_chunks([], [], "lec") == []
    assert (
        visual_only_chunks(
            [{"timestamp_seconds": 1.0, "extracted_text": None}], "lec", "en"
        )
        == []
    )


def test_four_hour_lecture_chunks_quickly_and_covers_the_whole_lecture():
    segments = four_hour_transcript()
    keyframes = four_hour_keyframes()
    total_words = sum(len(s["text"].split()) for s in segments)

    started = time.perf_counter()
    chunks = align_multimodal_chunks(
        segments, keyframes, "lec-4h", window_size=300, overlap_size=50
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 3.0, f"Chunking a 4-hour lecture took {elapsed:.1f}s"
    assert len(chunks) == math.ceil((total_words - 300) / 250) + 1
    assert chunks[0]["start_time_seconds"] == 0.0
    assert chunks[-1]["end_time_seconds"] == pytest.approx(4 * 3600, abs=1)
    starts = [c["start_time_seconds"] for c in chunks]
    assert starts == sorted(starts)
    bound = {v["timestamp_seconds"] for c in chunks for v in c["visual_contexts"]}
    assert bound == {k["timestamp_seconds"] for k in keyframes}
    assert max(len(c["composite_content"]) for c in chunks) < 6000
