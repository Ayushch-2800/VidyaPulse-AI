from typing import List, Dict, Any, Optional
import math


def interpolate_word_timestamps(
    transcript_segments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Expands sentence/segment-level transcript items into individual words
    with estimated start and end timestamps via linear interpolation.
    """
    words_with_timing = []

    def segment_start(segment: Dict[str, Any]) -> float:
        return float(segment.get("start_time_seconds", segment.get("start_time", 0.0)))

    # Whisper emits segments in order, but a merged or retried transcript may not be
    for segment in sorted(transcript_segments, key=segment_start):
        text = (segment.get("text") or "").strip()
        if not text:
            continue

        start_time = segment_start(segment)
        end_time = float(
            segment.get("end_time_seconds", segment.get("end_time", start_time))
        )
        duration = max(0.01, end_time - start_time)

        words = text.split()
        num_words = len(words)
        if num_words == 0:
            continue

        time_per_word = duration / num_words

        for i, word in enumerate(words):
            word_start = start_time + (i * time_per_word)
            word_end = start_time + ((i + 1) * time_per_word)
            words_with_timing.append(
                {
                    "word": word,
                    "start_time": round(word_start, 2),
                    "end_time": round(word_end, 2),
                }
            )

    return words_with_timing


def keyframe_timestamp(keyframe: Dict[str, Any]) -> float:
    return float(keyframe.get("timestamp_seconds", keyframe.get("timestamp", 0.0)))


def keyframe_text(keyframe: Dict[str, Any]) -> str:
    return (
        keyframe.get("extracted_text", keyframe.get("extracted_content", "")) or ""
    ).strip()


def visual_only_chunks(
    keyframes_data: List[Dict[str, Any]], lecture_id: str, language: str
) -> List[Dict[str, Any]]:
    """
    Task 19: When Whisper finds no speech (silent or music-only audio, or audio too noisy to
    transcribe) the slides are still worth searching. One chunk per slide with text, covering
    the time until the next slide.
    """
    slides = sorted(
        (kf for kf in keyframes_data if keyframe_text(kf)), key=keyframe_timestamp
    )
    chunks = []
    for index, kf in enumerate(slides):
        start = keyframe_timestamp(kf)
        end = (
            keyframe_timestamp(slides[index + 1]) if index + 1 < len(slides) else start
        )
        visual = {
            "timestamp_seconds": start,
            "storage_path": kf.get("storage_path", ""),
            "ocr_content": keyframe_text(kf),
        }
        chunks.append(
            {
                "chunk_index": index,
                "lecture_id": lecture_id,
                "start_time_seconds": start,
                "end_time_seconds": end,
                "duration_seconds": round(end - start, 2),
                "word_count": 0,
                "transcript_text": "",
                "visual_contexts": [visual],
                "visual_context_count": 1,
                "language": language,
                "composite_content": (
                    f"### Visual Blackboard / Slide Context ({start:.1f}s - {end:.1f}s):\n"
                    f"[Visual at {start:.1f}s]:\n{visual['ocr_content']}"
                ),
            }
        )
    return chunks


def align_multimodal_chunks(
    transcript_segments: List[Dict[str, Any]],
    keyframes_data: List[Dict[str, Any]],
    lecture_id: str,
    window_size: int = 300,
    overlap_size: int = 50,
    language: str = "hi-IN",
) -> List[Dict[str, Any]]:
    """
    Slices transcript into sliding windows of `window_size` words with `overlap_size` words,
    temporal-binds OCR/diagram keyframes within [start_time, end_time], and compiles
    unified text blocks for vectorization.
    """
    words = interpolate_word_timestamps(transcript_segments)
    if not words:
        return visual_only_chunks(keyframes_data, lecture_id, language)

    stride = max(1, window_size - overlap_size)
    unified_chunks = []
    chunk_index = 0

    total_words = len(words)
    start_idx = 0

    while start_idx < total_words:
        end_idx = min(start_idx + window_size, total_words)
        chunk_words = words[start_idx:end_idx]

        window_start_time = chunk_words[0]["start_time"]
        window_end_time = chunk_words[-1]["end_time"]
        transcript_text = " ".join([w["word"] for w in chunk_words])

        # Find keyframes that fall strictly inside the current temporal window
        matched_keyframes = [
            kf
            for kf in keyframes_data
            if window_start_time <= keyframe_timestamp(kf) <= window_end_time
        ]

        # Structure visual context payloads
        visual_contexts = []
        visual_texts_for_embedding = []

        for kf in matched_keyframes:
            ts = keyframe_timestamp(kf)
            storage_path = kf.get("storage_path", "")
            ocr_content = keyframe_text(kf)

            visual_contexts.append(
                {
                    "timestamp_seconds": ts,
                    "storage_path": storage_path,
                    "ocr_content": ocr_content,
                }
            )

            if ocr_content:
                visual_texts_for_embedding.append(
                    f"[Visual at {ts:.1f}s]:\n{ocr_content}"
                )

        # Build composite textual representation for dense vector embeddings
        visual_block = "\n\n".join(visual_texts_for_embedding)
        if visual_block:
            embedding_content = (
                f"### Spoken Transcript ({window_start_time:.1f}s - {window_end_time:.1f}s):\n"
                f"{transcript_text}\n\n"
                f"### Visual Blackboard / Slide Context:\n"
                f"{visual_block}"
            )
        else:
            embedding_content = transcript_text

        chunk_payload = {
            "chunk_index": chunk_index,
            "lecture_id": lecture_id,
            "start_time_seconds": window_start_time,
            "end_time_seconds": window_end_time,
            "duration_seconds": round(window_end_time - window_start_time, 2),
            "word_count": len(chunk_words),
            "transcript_text": transcript_text,
            "visual_contexts": visual_contexts,
            "visual_context_count": len(visual_contexts),
            "language": language,
            "composite_content": embedding_content,
        }

        unified_chunks.append(chunk_payload)
        chunk_index += 1

        # Break if the current window consumed up to the last word
        if end_idx == total_words:
            break

        start_idx += stride

    return unified_chunks


# --- VERIFICATION TEST HARNESS ---
if __name__ == "__main__":
    print("Testing temporal chunk alignment...")

    # Mock audio transcript segments (from Task 9)
    mock_transcript = [
        {
            "start_time_seconds": 0.0,
            "end_time_seconds": 15.0,
            "text": "Hello students. Today we will discuss trigonometry and sum of sines in arithmetic progression.",
        },
        {
            "start_time_seconds": 15.0,
            "end_time_seconds": 45.0,
            "text": "Notice the identity on the slide. The sum of sine alpha plus sine alpha plus beta continues up to n terms.",
        },
        {
            "start_time_seconds": 45.0,
            "end_time_seconds": 80.0,
            "text": "The closed form solution evaluates directly to sine n beta by two divided by sine beta by two into sine of the average angle.",
        },
    ]

    # Mock visual OCR keyframes (from Task 10)
    mock_keyframes = [
        {
            "timestamp_seconds": 22.5,
            "storage_path": "users/user_1/lec_1/frame_22.jpg",
            "extracted_text": "$$\\sum_{k=0}^{n-1} \\sin(\\alpha + k\\beta) = \\frac{\\sin\\left(\\frac{n\\beta}{2}\\right)}{\\sin\\left(\\frac{\\beta}{2}\\right)} \\sin\\left(\\alpha + \\frac{n-1}{2}\\beta\\right)$$",
        }
    ]

    # Running with a small window size (e.g. 20 words, 5 word overlap) to demo chunking on small sample text
    result = align_multimodal_chunks(
        transcript_segments=mock_transcript,
        keyframes_data=mock_keyframes,
        lecture_id="lec_test_101",
        window_size=20,
        overlap_size=5,
        language="en",
    )

    print(f"Generated {len(result)} temporal chunks.\n")
    for chunk in result:
        print(
            f"--- Chunk #{chunk['chunk_index']} [{chunk['start_time_seconds']}s -> {chunk['end_time_seconds']}s] ---"
        )
        print(f"Visual contexts bound: {chunk['visual_context_count']}")
        print(f"Composite payload preview:\n{chunk['composite_content'][:200]}...\n")
