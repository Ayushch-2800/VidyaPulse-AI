import os
import json
import tempfile
import requests
from typing import Dict, List, Any
from pydub import AudioSegment

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"


def parse_asr_response(res_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parses raw Sarvam ASR JSON output into standardized segments and metadata.
    """
    detected_language = res_json.get("language_code", "unknown")
    language_probability = res_json.get("language_probability", 0.0)
    full_transcript = res_json.get("transcript", "")

    timestamps_data = res_json.get("timestamps")
    segments: List[Dict[str, Any]] = []

    if timestamps_data and isinstance(timestamps_data, dict):
        words_or_phrases = timestamps_data.get("words", [])
        start_times = timestamps_data.get("start_time_seconds", [])
        end_times = timestamps_data.get("end_time_seconds", [])

        for text, start, end in zip(words_or_phrases, start_times, end_times):
            if text and text.strip():
                segments.append(
                    {
                        "text": text.strip(),
                        "start_time": round(float(start), 2),
                        "end_time": round(float(end), 2),
                    }
                )

    # Fallback if timestamps array is missing/empty but full_transcript exists
    if not segments and full_transcript:
        segments.append(
            {"text": full_transcript.strip(), "start_time": 0.0, "end_time": 0.0}
        )

    return {
        "detected_language": detected_language,
        "language_probability": language_probability,
        "full_transcript": full_transcript,
        "segments": segments,
    }


def _send_sarvam_asr_request(
    file_path: str, language_code: str, model: str, mode: str
) -> Dict[str, Any]:
    """
    Executes a single HTTP POST request to the Sarvam ASR endpoint.
    """
    headers = {"api-subscription-key": SARVAM_API_KEY}
    data = {
        "model": model,
        "language_code": language_code,  # 'unknown' triggers auto-detection across 22+ languages
        "mode": mode,  # 'codemix' handles regional dialects + English tech terms
        "with_timestamps": "true",  # Returns start/end timestamp arrays
    }

    with open(file_path, "rb") as audio_file:
        files = {"file": (os.path.basename(file_path), audio_file, "audio/wav")}
        response = requests.post(
            SARVAM_STT_URL, headers=headers, data=data, files=files, timeout=120
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"Sarvam ASR Error [{response.status_code}]: {response.text}"
        )

    res_json = response.json()

    # Terminal log for active inspection during testing
    print("\n================ SARVAM ASR RAW RESPONSE ================")
    print(json.dumps(res_json, indent=2, ensure_ascii=False))
    print("=========================================================\n")

    return parse_asr_response(res_json)


def transcribe_multilingual_audio(
    file_path: str,
    language_code: str = "unknown",
    model: str = "saaras:v3",
    mode: str = "codemix",
    chunk_duration_sec: int = 25,
) -> Dict[str, Any]:
    """
    Transcribes audio of arbitrary duration by slicing into 25-second sub-clips
    to bypass Sarvam AI's 30-second API limit, while offset-adjusting timestamps.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found at path: {file_path}")

    # Load audio media file via pydub
    audio = AudioSegment.from_file(file_path)
    total_duration_sec = len(audio) / 1000.0

    # Short audio fast-path (<= 28s)
    if total_duration_sec <= 28.0:
        return _send_sarvam_asr_request(file_path, language_code, model, mode)

    # Long audio chunking logic
    chunk_ms = chunk_duration_sec * 1000
    combined_segments: List[Dict[str, Any]] = []
    transcript_parts: List[str] = []
    detected_language = "unknown"
    language_probability = 0.0

    print(
        f"[ASR PIPELINE]: Audio duration is {total_duration_sec:.2f}s. Chunking into {chunk_duration_sec}s slices..."
    )

    for i in range(0, len(audio), chunk_ms):
        chunk_audio = audio[i : i + chunk_ms]
        time_offset_sec = i / 1000.0

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
            temp_path = temp_wav.name
            chunk_audio.export(temp_path, format="wav")

        try:
            chunk_res = _send_sarvam_asr_request(temp_path, language_code, model, mode)

            if (
                detected_language == "unknown"
                and chunk_res.get("detected_language") != "unknown"
            ):
                detected_language = chunk_res["detected_language"]
                language_probability = chunk_res.get("language_probability", 0.0)

            if chunk_res.get("full_transcript"):
                transcript_parts.append(chunk_res["full_transcript"].strip())

            # Adjust timestamps using current window time offset
            for seg in chunk_res.get("segments", []):
                combined_segments.append(
                    {
                        "text": seg["text"],
                        "start_time": round(seg["start_time"] + time_offset_sec, 2),
                        "end_time": round(seg["end_time"] + time_offset_sec, 2),
                    }
                )

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    return {
        "detected_language": detected_language,
        "language_probability": language_probability,
        "full_transcript": " ".join(transcript_parts),
        "segments": combined_segments,
    }


def build_semantic_chunks_multilingual(
    segments: List[Dict[str, Any]], target_duration: float = 45.0
) -> List[Dict[str, Any]]:
    """
    Aggregates timestamped segments into ~45-second semantic chunks for indexing,
    vector embedding, and Supabase 'transcript_chunks' storage.
    """
    if not segments:
        return []

    chunks = []
    current_chunk_text = []
    chunk_start_time = segments[0]["start_time"]
    current_duration = 0.0

    for seg in segments:
        text = seg["text"]
        start = seg["start_time"]
        end = seg["end_time"]
        seg_duration = max(end - start, 0.1)

        if current_chunk_text and (current_duration + seg_duration > target_duration):
            last_end_time = segments[segments.index(seg) - 1]["end_time"]
            chunks.append(
                {
                    "chunk_text": " ".join(current_chunk_text),
                    "start_time": chunk_start_time,
                    "end_time": last_end_time,
                }
            )
            current_chunk_text = [text]
            chunk_start_time = start
            current_duration = seg_duration
        else:
            current_chunk_text.append(text)
            current_duration += seg_duration

    if current_chunk_text:
        chunks.append(
            {
                "chunk_text": " ".join(current_chunk_text),
                "start_time": chunk_start_time,
                "end_time": segments[-1]["end_time"],
            }
        )

    return chunks
