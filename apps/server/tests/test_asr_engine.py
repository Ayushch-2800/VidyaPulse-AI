import sys
from types import SimpleNamespace

import pytest


class FakeWhisperModel:
    """Records how it was built; transcribe() replays FakeWhisperModel.result."""

    instances = []
    fail_local_load = False
    result = ([], SimpleNamespace(language="en", language_probability=0.99))
    error = None

    def __init__(self, size, device, compute_type, local_files_only=False):
        if local_files_only and FakeWhisperModel.fail_local_load:
            raise OSError("model not cached")
        self.args = (size, device, compute_type, local_files_only)
        FakeWhisperModel.instances.append(self)

    def transcribe(self, path, beam_size=5):
        if FakeWhisperModel.error:
            raise FakeWhisperModel.error
        segments, info = FakeWhisperModel.result
        return iter(segments), info


def segment(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text)


@pytest.fixture
def asr(stub):
    """asr_engine imported against a fake faster_whisper, with a fresh model slot."""
    FakeWhisperModel.instances = []
    FakeWhisperModel.fail_local_load = False
    FakeWhisperModel.error = None
    stub("faster_whisper", WhisperModel=FakeWhisperModel)
    sys.modules.pop("asr_engine", None)
    import asr_engine

    yield asr_engine
    sys.modules.pop("asr_engine", None)  # The next import gets the real faster_whisper


@pytest.fixture
def audio_file(tmp_path):
    path = tmp_path / "lecture.mp3"
    path.write_bytes(b"ID3fake")
    return str(path)


def test_model_loads_once_from_the_local_cache(asr):
    first = asr.get_whisper_model()
    assert asr.get_whisper_model() is first
    assert first.args == ("base", "cpu", "int8", True)


def test_model_downloads_when_not_cached(asr):
    FakeWhisperModel.fail_local_load = True
    model = asr.get_whisper_model()
    assert model.args == ("base", "cpu", "int8", False)


def test_missing_file_raises(asr):
    with pytest.raises(FileNotFoundError):
        asr.transcribe_multilingual_audio("/no/such/file.mp3")


def test_transcription_formats_segments(asr, audio_file):
    FakeWhisperModel.result = (
        [
            segment(0.0, 2.5, " Namaste students, "),
            segment(2.5, 6.0, "aaj hum derivative padhenge."),
        ],
        SimpleNamespace(language="hi", language_probability=0.71),
    )
    result = asr.transcribe_multilingual_audio(audio_file)
    assert result == {
        "segments": [
            {
                "start_time_seconds": 0.0,
                "end_time_seconds": 2.5,
                "text": "Namaste students,",
            },
            {
                "start_time_seconds": 2.5,
                "end_time_seconds": 6.0,
                "text": "aaj hum derivative padhenge.",
            },
        ],
        "detected_language": "hi",
    }


def test_noisy_audio_hallucinations_are_cleaned(asr, audio_file):
    """Whisper over noise or silence repeats a phrase and emits music notes or dots."""
    FakeWhisperModel.result = (
        [
            segment(0.0, 4.0, "The derivative of sine is cosine."),
            segment(4.0, 6.0, "♪ ♪"),
            segment(6.0, 8.0, "..."),
            segment(8.0, 10.0, "Thank you."),
            segment(10.0, 12.0, "thank you."),
            segment(12.0, 14.0, "Thank  you."),
            segment(14.0, 16.0, "Next, the chain rule."),
        ],
        SimpleNamespace(language="en", language_probability=0.41),
    )
    result = asr.transcribe_multilingual_audio(audio_file)
    assert [
        (s["text"], s["start_time_seconds"], s["end_time_seconds"])
        for s in result["segments"]
    ] == [
        ("The derivative of sine is cosine.", 0.0, 4.0),
        ("Thank you.", 8.0, 14.0),
        ("Next, the chain rule.", 14.0, 16.0),
    ]


def test_a_crash_returns_an_error_instead_of_fake_text(asr, audio_file):
    FakeWhisperModel.error = RuntimeError("Invalid data found when processing input")
    result = asr.transcribe_multilingual_audio(audio_file)
    assert result["segments"] == []
    assert result["detected_language"] == "unknown"
    assert "Invalid data" in result["error"]


def test_clean_segments_keeps_indic_scripts_and_fixes_backwards_times(asr):
    cleaned = asr.clean_segments(
        [
            {"start_time_seconds": 0, "end_time_seconds": 3, "text": "अवकलज का नियम"},
            {"start_time_seconds": 3, "end_time_seconds": 2, "text": "தொகையீடு"},
            {"start_time_seconds": 4, "end_time_seconds": 5, "text": None},
        ]
    )
    assert [s["text"] for s in cleaned] == ["अवकलज का नियम", "தொகையீடு"]
    assert cleaned[1]["end_time_seconds"] == 3.0
