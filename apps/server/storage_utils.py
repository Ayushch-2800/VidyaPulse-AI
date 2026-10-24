import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

_client = None


def get_supabase() -> Client:
    """Creates the Supabase client on first use, never at import time."""
    global _client
    if _client is None:
        _client = create_client(
            os.getenv("NEXT_PUBLIC_SUPABASE_URL", ""),
            # Use Service Role for backend bypass if needed, or Anon Key
            os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
        )
    return _client


class _LazySupabase:
    """Stands in for the client so `from storage_utils import supabase` opens no connection."""

    def __getattr__(self, name):
        return getattr(get_supabase(), name)


supabase: Client = _LazySupabase()  # type: ignore[assignment]


def generate_signed_url(
    bucket: str, file_path: str, expiration_seconds: int = 3600
) -> str:
    """
    Generates a secure, temporary Signed URL to access private bucket files.
    """
    try:
        response = supabase.storage.from_(bucket).create_signed_url(
            file_path, expiration_seconds
        )
        return response.get("signedURL", "")
    except Exception as e:
        print(f"Error generating signed URL: {str(e)}")
        return ""


def upload_file_backend(
    bucket: str, file_path: str, file_bytes: bytes, content_type: str = "audio/mpeg"
):
    """
    Uploads binary media from FastAPI directly to Supabase Storage.
    """
    try:
        res = supabase.storage.from_(bucket).upload(
            file_path, file_bytes, {"content-type": content_type}
        )
        return res
    except Exception as e:
        print(f"Upload failed: {str(e)}")
        return None
