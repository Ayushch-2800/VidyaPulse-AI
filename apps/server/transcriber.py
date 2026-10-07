import os
import json
import tempfile
from pathlib import Path
from typing import List, Dict
from sarvamai import SarvamAI


def transcribe_audio_sarvam(file_path: str, language_code: str = "hi-IN") -> List[Dict]:
    """
    Transcribes audio using Sarvam AI Batch STT API (saaras:v4).
    Handles files of any length asynchronously without payload/30s restrictions.
    Returns standardized timestamped segments:
    [{"text": "...", "transcript": "...", "start_time": 0.0, "end_time": 4.5}]
    """
    api_key = os.getenv("SARVAM_API_KEY", "")
    if not api_key:
        raise ValueError("SARVAM_API_KEY environment variable is not set in .env")

    # Initialize official Sarvam AI SDK client
    client = SarvamAI(api_subscription_key=api_key)

    # 1. Create Sarvam Batch STT Job
    job = client.speech_to_text_job.create_job(
        model="saaras:v4", mode="transcribe", language_code=language_code
    )

    # 2. Upload Audio File (MP3/WAV) and Start Processing
    job.upload_files(file_paths=[file_path])
    job.start()

    # 3. Wait for Async Job Completion (poll every 3 seconds, max timeout 10 mins)
    job.wait_until_complete(poll_interval=3, timeout=600)

    # 4. Check for Execution Failures
    file_results = job.get_file_results()
    if not file_results.get("successful"):
        failed_info = file_results.get("failed", [{}])[0]
        error_msg = failed_info.get(
            "error_message", "Unknown error in Sarvam batch job"
        )
        raise RuntimeError(f"Sarvam batch transcription failed: {error_msg}")

    # 5. Extract JSON Outputs and Standardize Segment Keys
    segments = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        job.download_outputs(output_dir=tmp_dir)

        for json_path in Path(tmp_dir).glob("*.json"):
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

                # Segment-level transcription with timestamps
                if "segments" in data and isinstance(data["segments"], list):
                    for item in data["segments"]:
                        txt = item.get("transcript") or item.get("text") or ""
                        segments.append(
                            {
                                "text": txt,  # Primary key for downstream compatibility
                                "transcript": txt,  # Sarvam standard key
                                "start_time": float(
                                    item.get(
                                        "start_time_seconds",
                                        item.get("start_time", 0.0),
                                    )
                                ),
                                "end_time": float(
                                    item.get(
                                        "end_time_seconds", item.get("end_time", 0.0)
                                    )
                                ),
                            }
                        )

                # Fallback if Sarvam returns single transcript string
                elif "transcript" in data and isinstance(data["transcript"], str):
                    txt = data["transcript"]
                    segments.append(
                        {
                            "text": txt,
                            "transcript": txt,
                            "start_time": 0.0,
                            "end_time": 0.0,
                        }
                    )

    if not segments:
        raise ValueError(
            "Sarvam batch job completed successfully but returned no text content."
        )

    return segments


def build_semantic_chunks(
    segments: List[Dict], target_duration_seconds: float = 45.0
) -> List[Dict]:
    """
    Groups sentence-level segments into ~45-second knowledge chunks for vector embeddings.
    Safely handles both 'text' and 'transcript' key variations to prevent KeyError exceptions.
    """
    chunks = []
    current_chunk_text = []
    chunk_start = None
    chunk_end = 0.0

    for seg in segments:
        # Safe extraction of text content regardless of API response dictionary schema
        text_content = seg.get("text") or seg.get("transcript") or ""
        text_content = text_content.strip()

        if not text_content:
            continue

        start_time = float(seg.get("start_time", 0.0))
        end_time = float(seg.get("end_time", 0.0))

        if chunk_start is None:
            chunk_start = start_time

        current_chunk_text.append(text_content)
        chunk_end = end_time

        # When current chunk reaches or exceeds target duration, flush to chunks list
        if (chunk_end - chunk_start) >= target_duration_seconds:
            chunks.append(
                {
                    "chunk_text": " ".join(current_chunk_text),
                    "start_time": chunk_start,
                    "end_time": chunk_end,
                }
            )
            current_chunk_text = []
            chunk_start = None

    # Append remaining leftover segments
    if current_chunk_text and chunk_start is not None:
        chunks.append(
            {
                "chunk_text": " ".join(current_chunk_text),
                "start_time": chunk_start,
                "end_time": chunk_end,
            }
        )

    return chunks
