import os
import subprocess
import tempfile
from fastapi import UploadFile, HTTPException, status
from mutagen import File as MutagenFile

# Allowed magic byte signatures
ALLOWED_SIGNATURES = {
    "mp3": [b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"],
    "mp4": [b"ftyp"],
    "mkv": [b"\x1a\x45\xdf\xa3"],
    "wav": [b"RIFF"],
}

MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


def validate_and_save_upload(file: UploadFile) -> str:
    """
    Validates file size, signature, and saves it to a temporary local file.
    """
    # 1. Size Check
    file.file.seek(0, os.SEEK_END)
    file_size = file.file.tell()
    file.file.seek(0)

    if file_size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds 2GB limit ({file_size / (1024**3):.2f} GB uploaded).",
        )

    # 2. File Signature Check
    header = file.file.read(12)
    file.file.seek(0)

    is_valid = any(
        header.startswith(sig) or sig in header
        for sigs in ALLOWED_SIGNATURES.values()
        for sig in sigs
    )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid media file format. Only MP3, MP4, MKV, and WAV are supported.",
        )

    # 3. Save to Temp Directory
    ext = os.path.splitext(file.filename)[1].lower() or ".mp3"
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)

    chunk_size = 1024 * 1024 * 10  # 10 MB chunks
    while chunk := file.file.read(chunk_size):
        temp_file.write(chunk)
    temp_file.close()

    return temp_file.name


def convert_to_mp3_if_needed(
    input_path: str, bitrate: str = "128k", mono: bool = False
) -> str:
    """
    Converts video files (.mp4, .mkv) or uncompressed audio to compressed 128kbps MP3.
    Returns path to the extracted audio file. mono halves the size for speech-only recordings.
    """
    ext = os.path.splitext(input_path)[1].lower()

    if ext == ".mp3":
        return input_path

    output_mp3_path = os.path.splitext(input_path)[0] + "_extracted.mp3"

    # Run FFmpeg to extract/re-encode audio to MP3
    command = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vn",
        "-acodec",
        "libmp3lame",
        "-ab",
        bitrate,
        "-ar",
        "44100",
        *(["-ac", "1"] if mono else []),
        output_mp3_path,
    ]

    try:
        subprocess.run(
            command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return output_mp3_path
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg audio extraction failed for local file: {str(e)}")


def get_media_duration_seconds(file_path: str) -> float:
    """
    Extracts total media duration in seconds using mutagen.
    """
    try:
        audio = MutagenFile(file_path)
        if audio is not None and audio.info is not None:
            return float(audio.info.length)
        return 0.0
    except Exception:
        return 0.0
