import io
import os
import subprocess
import wave

import pytest
from fastapi import HTTPException, UploadFile

import media_validator


def upload(name: str, body: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(body), filename=name)


@pytest.mark.parametrize(
    "name, header",
    [
        ("a.mp3", b"ID3\x03\x00"),
        ("b.mp3", b"\xff\xfb\x90\x00"),
        ("c.mp4", b"\x00\x00\x00\x18ftypmp42"),
        ("d.mkv", b"\x1a\x45\xdf\xa3"),
        ("e.wav", b"RIFF\x00\x00\x00\x00WAVE"),
    ],
)
def test_valid_media_is_saved_with_its_extension(name, header):
    path = media_validator.validate_and_save_upload(
        upload(name, header + b"payload" * 100)
    )
    try:
        assert path.endswith(os.path.splitext(name)[1])
        with open(path, "rb") as f:
            assert f.read().startswith(header)
    finally:
        os.remove(path)


def test_unknown_formats_are_rejected():
    with pytest.raises(HTTPException) as error:
        media_validator.validate_and_save_upload(upload("notes.pdf", b"%PDF-1.7"))
    assert error.value.status_code == 400


def test_oversized_files_are_rejected(monkeypatch):
    monkeypatch.setattr(media_validator, "MAX_FILE_SIZE_BYTES", 10)
    with pytest.raises(HTTPException, match="exceeds 2GB"):
        media_validator.validate_and_save_upload(upload("a.mp3", b"ID3" + b"x" * 20))


def test_files_without_extension_default_to_mp3():
    path = media_validator.validate_and_save_upload(upload("recording", b"ID3abc"))
    os.remove(path)
    assert path.endswith(".mp3")


def test_mp3_is_not_converted_and_video_goes_through_ffmpeg(monkeypatch):
    assert media_validator.convert_to_mp3_if_needed("/x/talk.mp3") == "/x/talk.mp3"
    commands = []
    monkeypatch.setattr(
        subprocess, "run", lambda command, **kw: commands.append(command)
    )
    assert (
        media_validator.convert_to_mp3_if_needed("/x/talk.mp4")
        == "/x/talk_extracted.mp3"
    )
    assert (
        commands[0][:4] == ["ffmpeg", "-y", "-i", "/x/talk.mp4"]
        and "libmp3lame" in commands[0]
    )


def test_ffmpeg_failures_raise(monkeypatch):
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="FFmpeg audio extraction failed"):
        media_validator.convert_to_mp3_if_needed("/x/talk.mkv")


def test_duration_of_a_real_wav(tmp_path):
    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)  # telephone-quality sample rate
        w.writeframes(b"\x00\x00" * 8000 * 3)
    assert media_validator.get_media_duration_seconds(str(path)) == pytest.approx(3.0)


def test_duration_of_unreadable_files_is_zero(tmp_path, monkeypatch):
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"not audio")
    assert media_validator.get_media_duration_seconds(str(junk)) == 0.0

    def explode(path):
        raise OSError("unreadable")

    monkeypatch.setattr(media_validator, "MutagenFile", explode)
    assert media_validator.get_media_duration_seconds(str(junk)) == 0.0
