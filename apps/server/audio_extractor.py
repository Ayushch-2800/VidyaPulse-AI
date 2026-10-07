import os
import tempfile
import yt_dlp
from storage_utils import supabase


def download_youtube_audio(youtube_url: str, user_id: str) -> dict:
    temp_dir = tempfile.gettempdir()

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "64",
            }
        ],
        "outtmpl": os.path.join(temp_dir, "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        # Emulates valid YouTube clients to bypass 403 Forbidden blocks
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        video_id = info.get("id")
        title = info.get("title", "Untitled Lecture")

    local_mp3_path = os.path.join(temp_dir, f"{video_id}.mp3")

    if not os.path.exists(local_mp3_path):
        raise FileNotFoundError(
            f"Audio extraction failed. File not found: {local_mp3_path}"
        )

    bucket_filename = f"{user_id}/{video_id}.mp3"

    with open(local_mp3_path, "rb") as f:
        supabase.storage.from_("lectures").upload(
            path=bucket_filename,
            file=f,
            file_options={"content-type": "audio/mpeg", "upsert": "true"},
        )

    return {
        "title": title,
        "bucket_path": bucket_filename,
        "local_wav_path": local_mp3_path,
    }
