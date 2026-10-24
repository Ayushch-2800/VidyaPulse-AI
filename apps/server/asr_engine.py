import os
import threading
from typing import Dict, Any
from faster_whisper import WhisperModel

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

        print(
            f"[ASR PIPELINE] Successfully extracted {len(formatted_segments)} audio chunks."
        )

        return {"segments": formatted_segments, "detected_language": detected_lang}

    except Exception as e:
        print(f"[ASR ERROR] Local transcription failed: {e}")
        # Return fallback empty data so the pipeline handles failures gracefully
        return {
            "segments": [
                {
                    "start_time_seconds": 0.0,
                    "end_time_seconds": 1.0,
                    "text": "[Audio transcription failed]",
                }
            ],
            "detected_language": "unknown",
        }
