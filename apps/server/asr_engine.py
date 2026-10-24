import os
from typing import Dict, Any
from faster_whisper import WhisperModel

# 1. Load the model globally so it initializes only once when the server starts.
# We use "base" on "cpu" with "int8" for extreme speed and low RAM usage.
print("[ASR SETUP] Loading local Whisper model...")
model = WhisperModel("base", device="cpu", compute_type="int8")
print("[ASR SETUP] Whisper model loaded successfully.")


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
        segments, info = model.transcribe(file_path, beam_size=5)

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
