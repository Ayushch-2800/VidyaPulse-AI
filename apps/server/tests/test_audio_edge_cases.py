"""
Task 19 edge cases with real audio. Runs the local faster-whisper model on synthesized lecture
speech, degraded the way classroom recordings are (background noise, phone-quality bandwidth,
low bitrate, clipping, room echo), in Indian English and code-mixed Hindi and Tamil voices,
plus silence, a corrupt file and a 5-minute recording.

Opt-in, because Whisper takes a few minutes on CPU. From apps/server:

    pytest -m audio -s

Needs ffmpeg (static-ffmpeg provides it), a text-to-speech voice (macOS `say`, or `espeak-ng`
on Linux) and the Whisper base model, which is downloaded once if it isn't cached. Anything
missing makes the affected tests skip with the reason. -s prints each transcript.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from typing import List, Optional

import pytest

from temporal_chunker import align_multimodal_chunks

pytestmark = pytest.mark.audio

ENGLISH = (
    "Today we will study the derivative. The derivative of sine x is cosine x. "
    "The chain rule says we differentiate the outer function, "
    "then multiply by the derivative of the inner function."
)
KEY_TERMS = ("derivative", "sine", "cosine", "chain rule", "function")
HINGLISH = (
    "आज हम derivative पढ़ेंगे। sine x का derivative cosine x होता है। "
    "chain rule में पहले बाहर वाले function का derivative लेते हैं।"
)
TAMIL_ENGLISH = "இன்று நாம் derivative படிப்போம். sine x இன் derivative cosine x ஆகும்."

# ffmpeg audio filters for the ways a lecture recording goes wrong
DEGRADATIONS = {
    "clean": ["-af", "aresample=16000"],
    "background_noise": [
        "-filter_complex",
        "anoisesrc=color=pink:amplitude=0.08:sample_rate=16000[n];"
        "[0:a]aresample=16000[s];[s][n]amix=inputs=2:duration=first",
    ],
    "phone_quality": ["-af", "highpass=f=300,lowpass=f=3400,aresample=8000"],
    "low_bitrate": ["-af", "aresample=16000", "-c:a", "libmp3lame", "-b:a", "16k"],
    "clipped": ["-af", "volume=18dB,aresample=16000"],
    "room_echo": ["-af", "aecho=0.8:0.85:60|120:0.5|0.3,aresample=16000"],
}


@lru_cache(maxsize=1)
def ffmpeg() -> Optional[str]:
    try:
        import static_ffmpeg

        static_ffmpeg.add_paths()
    except Exception:
        pass
    return shutil.which("ffmpeg")


def run_ffmpeg(*args: str) -> None:
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", *args], check=True)


@lru_cache(maxsize=1)
def macos_voices() -> dict:
    """locale -> voice name, from `say -v ?` (e.g. en_IN -> Rishi, hi_IN -> Lekha)."""
    if not shutil.which("say"):
        return {}
    listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    voices = {}
    for line in listing.splitlines():
        match = re.match(r"^(.+?)\s{2,}([a-z]{2}_[A-Z]{2})\s", line)
        if match:
            voices.setdefault(match.group(2), match.group(1).strip())
    return voices


def speak(text: str, path: str, locale: str) -> str:
    """Synthesizes speech with a voice for `locale` (en_IN, hi_IN, ta_IN) and returns the voice used."""
    voices = macos_voices()
    if voices:
        voice = voices.get(locale) or (
            voices.get("en_US") if locale.startswith("en") else None
        )
        if not voice:
            pytest.skip(
                f"No macOS voice for {locale}; add one in System Settings > Accessibility > Spoken Content."
            )
        aiff = path + ".aiff"
        subprocess.run(["say", "-v", voice, "-o", aiff, text], check=True)
        run_ffmpeg("-i", aiff, "-ac", "1", "-ar", "16000", path)
        return voice
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if espeak:
        voice = {"en_IN": "en", "hi_IN": "hi", "ta_IN": "ta"}[locale]
        subprocess.run([espeak, "-v", voice, "-s", "140", "-w", path, text], check=True)
        return f"espeak {voice}"
    pytest.skip("No text-to-speech: needs macOS `say` or espeak-ng.")


def degrade(source: str, target: str, kind: str) -> None:
    run_ffmpeg("-i", source, *DEGRADATIONS[kind], "-ac", "1", target)


def duration_seconds(path: str) -> float:
    from media_validator import get_media_duration_seconds

    return get_media_duration_seconds(path)


@pytest.fixture(scope="module")
def whisper():
    if not ffmpeg():
        pytest.skip("ffmpeg is not available.")
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        pytest.skip("faster-whisper is not installed in this venv.")
    sys.modules.pop(
        "asr_engine", None
    )  # a unit test may have imported it against a fake
    import asr_engine

    try:
        asr_engine.get_whisper_model()
    except Exception as e:
        pytest.skip(f"The Whisper model could not be loaded or downloaded: {e}")
    return asr_engine


def transcribe(asr_engine, path: str) -> dict:
    started = time.perf_counter()
    result = asr_engine.transcribe_multilingual_audio(path)
    result["seconds"] = time.perf_counter() - started
    return result


def text_of(result: dict) -> str:
    return " ".join(s["text"] for s in result["segments"])


def term_recall(text: str) -> float:
    lowered = text.lower()
    return sum(term in lowered for term in KEY_TERMS) / len(KEY_TERMS)


def assert_valid_timing(segments: List[dict], duration: float) -> None:
    starts = [s["start_time_seconds"] for s in segments]
    assert starts == sorted(starts), "segments out of order"
    for s in segments:
        assert 0 <= s["start_time_seconds"] <= s["end_time_seconds"] <= duration + 2.0
    texts = [s["text"].lower() for s in segments]
    assert all(
        a != b for a, b in zip(texts, texts[1:])
    ), "a repeated hallucination survived cleanup"


@pytest.fixture(scope="module")
def english_clip(tmp_path_factory):
    folder = tmp_path_factory.mktemp("speech")
    path = str(folder / "english.wav")
    voice = speak(ENGLISH, path, "en_IN")
    return path, voice


@pytest.mark.parametrize("kind", list(DEGRADATIONS))
def test_degraded_lecture_audio_is_transcribed(whisper, english_clip, tmp_path, kind):
    source, voice = english_clip
    target = str(tmp_path / f"{kind}.{'mp3' if kind == 'low_bitrate' else 'wav'}")
    degrade(source, target, kind)
    result = transcribe(whisper, target)
    text = text_of(result)
    recall = term_recall(text)
    print(
        f"\n[{kind}] voice={voice} lang={result['detected_language']} recall={recall:.0%} {result['seconds']:.1f}s: {text}"
    )

    assert "error" not in result
    assert result["segments"], f"Whisper heard nothing in the {kind} recording"
    assert_valid_timing(result["segments"], duration_seconds(target))
    assert align_multimodal_chunks(
        result["segments"], [], "lec", 300, 50, result["detected_language"]
    )
    if kind == "clean":
        # Whisper base may write "sign" for "sine"; 2 of the 5 terms is a clear pass
        assert (
            recall >= 0.4
        ), f"Only {recall:.0%} of the key terms were heard in clean speech: {text}"


@pytest.mark.parametrize(
    "locale, text", [("hi_IN", HINGLISH), ("ta_IN", TAMIL_ENGLISH)]
)
def test_code_mixed_regional_speech(whisper, tmp_path, locale, text):
    path = str(tmp_path / f"{locale}.wav")
    voice = speak(text, path, locale)
    result = transcribe(whisper, path)
    transcript = text_of(result)
    print(
        f"\n[{locale}] voice={voice} lang={result['detected_language']} {result['seconds']:.1f}s: {transcript}"
    )

    assert "error" not in result and result["segments"]
    assert_valid_timing(result["segments"], duration_seconds(path))
    (chunk,) = align_multimodal_chunks(
        result["segments"], [], "lec", 300, 50, result["detected_language"]
    )
    assert chunk["language"] == result["detected_language"]


@pytest.mark.parametrize(
    "source",
    [
        "anullsrc=r=16000:cl=mono",
        "anoisesrc=color=white:amplitude=0.02:sample_rate=16000",
    ],
)
def test_silence_and_hiss_produce_no_junk(whisper, tmp_path, source):
    path = str(tmp_path / "quiet.wav")
    run_ffmpeg("-f", "lavfi", "-i", source, "-t", "20", "-ac", "1", path)
    result = transcribe(whisper, path)
    print(
        f"\n[{source.split('=')[0]}] segments={len(result['segments'])}: {text_of(result)!r}"
    )

    assert "error" not in result
    assert_valid_timing(result["segments"], 20.0)
    assert (
        len(result["segments"]) <= 3
    ), "Whisper hallucinated a transcript over silence or hiss"


def test_corrupt_file_is_an_error_not_a_transcript(whisper, tmp_path):
    path = tmp_path / "broken.mp3"
    path.write_bytes(os.urandom(4096))
    result = transcribe(whisper, str(path))
    assert result["segments"] == [] and result["error"]


def test_long_recording_keeps_its_timeline(whisper, english_clip, tmp_path):
    """A 5-minute recording: timestamps must run to the end, and the speed predicts a 4-hour lecture."""
    source, _ = english_clip
    path = str(tmp_path / "long.wav")
    run_ffmpeg(
        "-stream_loop",
        "-1",
        "-i",
        source,
        "-t",
        "300",
        "-ac",
        "1",
        "-ar",
        "16000",
        path,
    )
    result = transcribe(whisper, path)
    segments = result["segments"]
    four_hour_minutes = result["seconds"] * (4 * 3600 / 300) / 60
    print(
        f"\n[5 min] {len(segments)} segments in {result['seconds']:.0f}s; a 4-hour lecture would take ~{four_hour_minutes:.0f} min"
    )

    assert_valid_timing(segments, 300.0)
    assert (
        segments[-1]["end_time_seconds"] >= 270
    ), "the transcript stops well before the audio does"
    chunks = align_multimodal_chunks(segments, [], "lec", 300, 50, "en")
    assert chunks[-1]["end_time_seconds"] >= 270


def test_degradation_filters_produce_audio(tmp_path):
    """Checks the ffmpeg filters themselves on a tone, so a broken filter isn't blamed on Whisper."""
    if not ffmpeg():
        pytest.skip("ffmpeg is not available.")
    tone = str(tmp_path / "tone.wav")
    run_ffmpeg(
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "3", tone
    )
    for kind in DEGRADATIONS:
        target = str(tmp_path / f"{kind}.{'mp3' if kind == 'low_bitrate' else 'wav'}")
        degrade(tone, target, kind)
        assert duration_seconds(target) == pytest.approx(3.0, abs=0.3), kind
