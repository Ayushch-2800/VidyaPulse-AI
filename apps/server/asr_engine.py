import os
import re
import threading
from typing import Dict, Any, List
from faster_whisper import WhisperModel

# A segment needs at least one letter or digit in any script; "...", "♪" or "" is not speech
SPEECH_PATTERN = re.compile(r"[^\W_]")

# 1. Load the model once per process, on first use rather than at import time.
# We use "base" on "cpu" with "int8" for extreme speed and low RAM usage.
_model = None
_model_lock = threading.Lock()


def get_whisper_model() -> WhisperModel:
    global _model
    with _model_lock:
        if _model is None:
            print("[ASR SETUP] Loading local Whisper model...", flush=True)
            try:
                # Use the cached copy without asking Hugging Face for updates (a network call)
                _model = WhisperModel(
                    "base", device="cpu", compute_type="int8", local_files_only=True
                )
            except Exception:
                print(
                    "[ASR SETUP] Whisper model not cached yet, downloading it once...",
                    flush=True,
                )
                _model = WhisperModel("base", device="cpu", compute_type="int8")
            print("[ASR SETUP] Whisper model loaded successfully.", flush=True)
    return _model


def clean_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Task 19: Tidies Whisper output from low-quality audio. Drops segments with no words
    (music notes, "...") and merges back-to-back repeats of the same text, which is how
    Whisper hallucinates over noise or silence ("Thank you. Thank you. Thank you.").
    Timing is kept: a merged segment ends where the last repeat ended.
    """
    cleaned: List[Dict[str, Any]] = []
    for segment in segments:
        text = " ".join((segment.get("text") or "").split())
        if not SPEECH_PATTERN.search(text):
            continue
        start = float(segment["start_time_seconds"])
        end = max(start, float(segment["end_time_seconds"]))
        previous = cleaned[-1] if cleaned else None
        if previous and previous["text"].lower() == text.lower():
            previous["end_time_seconds"] = max(previous["end_time_seconds"], end)
            continue
        cleaned.append(
            {"start_time_seconds": start, "end_time_seconds": end, "text": text}
        )
    return cleaned


def transcribe_multilingual_audio(
    file_path: str, language_code: str = "unknown", mode: str = "codemix"
) -> Dict[str, Any]:
    """
    Transcribes audio using a locally hosted Whisper model.
    100% Free, offline, and completely immune to API rate limits.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    print(f"[ASR PIPELINE] Transcribing {file_path} locally using faster-whisper...")

    try:
        # 2. Transcribe the audio
        segments, info = get_whisper_model().transcribe(file_path, beam_size=5)

        detected_lang = info.language
        print(
            f"[ASR PIPELINE] Detected language: {detected_lang} with probability {info.language_probability:.2f}"
        )

        formatted_segments = []

        # 3. Format segments exactly as Task 11 expects
        for segment in segments:
            formatted_segments.append(
                {
                    "start_time_seconds": segment.start,
                    "end_time_seconds": segment.end,
                    "text": segment.text.strip(),
                }
            )

        cleaned = clean_segments(formatted_segments)
        if len(cleaned) < len(formatted_segments):
            print(
                f"[ASR PIPELINE] Dropped or merged {len(formatted_segments) - len(cleaned)} "
                "empty or repeated segments (noise, music or silence)."
            )
        print(f"[ASR PIPELINE] Successfully extracted {len(cleaned)} audio chunks.")

        return {"segments": cleaned, "detected_language": detected_lang}

    except Exception as e:
        print(f"[ASR ERROR] Local transcription failed: {e}")
        # No placeholder text: indexing "[Audio transcription failed]" as if it were the
        # lecture made chat answer from it. The pipelines check "error" and mark it failed.
        return {"segments": [], "detected_language": "unknown", "error": str(e)}
