import static_ffmpeg

static_ffmpeg.add_paths()

import os
import uuid
import uvicorn
import mimetypes
from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status,
    File,
    UploadFile,
    BackgroundTasks,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from auth import get_current_user
from audio_extractor import download_youtube_audio
from asr_engine import transcribe_multilingual_audio, build_semantic_chunks_multilingual
from storage_utils import supabase
from media_validator import (
    validate_and_save_upload,
    convert_to_mp3_if_needed,
    get_media_duration_seconds,
)
from vision_extractor import process_video_keyframes

app = FastAPI(title="VidyaPulse AI Engine")

# CORS setup for Next.js frontend & Chrome Extension
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_origin_regex=r"chrome-extension://.*",  # Safely allows Chrome extension requests
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directory to temporarily hold captured audio chunks from Chrome Extension
UPLOAD_DIR = "temp_chunks"
os.makedirs(UPLOAD_DIR, exist_ok=True)


class IngestYouTubeRequest(BaseModel):
    youtube_url: str


class FinalizeStreamRequest(BaseModel):
    session_id: str


@app.get("/")
def root_check():
    return {"message": "VidyaPulse AI Engine is running."}


@app.get("/db-check")
def db_check():
    return {"status": "ok"}


def process_ingestion_pipeline(
    lecture_id: str,
    local_audio_path: str,
    original_file_path: str = None,
    user_id: str = None,
):
    """
    Executes frame extraction, Pan-India Multilingual ASR, semantic chunking, and database persistence
    asynchronously for background file processing.
    """
    try:
        # Keyframe Extraction for Video files
        if original_file_path and user_id:
            mime_type, _ = mimetypes.guess_type(original_file_path)
            if mime_type and mime_type.startswith("video"):
                print(f"🎬 Starting frame extraction for {lecture_id}")
                process_video_keyframes(
                    video_path=original_file_path,
                    lecture_id=lecture_id,
                    user_id=user_id,
                    ssim_threshold=0.85,
                )

        # 1. Pan-India Multilingual ASR with Auto Language Detection & Code-Mixing
        asr_result = transcribe_multilingual_audio(
            file_path=local_audio_path,
            language_code="unknown",  # Auto-detects hi-IN, ta-IN, te-IN, kn-IN, mr-IN, etc.
            mode="codemix",  # Ideal for Hinglish, Tanglish, and technical code-switching
        )

        detected_lang = asr_result["detected_language"]
        segments = asr_result["segments"]

        # 2. Build ~45-second Semantic Chunks
        chunks = build_semantic_chunks_multilingual(segments, target_duration=45.0)

        # 3. Insert into Supabase transcript_chunks table
        db_chunks = []
        for index, chunk in enumerate(chunks):
            db_chunks.append(
                {
                    "lecture_id": lecture_id,
                    "chunk_index": index,
                    "text_content": chunk["chunk_text"],
                    "start_time": chunk["start_time"],
                    "end_time": chunk["end_time"],
                    "language": detected_lang,
                }
            )

        if db_chunks:
            supabase.table("transcript_chunks").insert(db_chunks).execute()

        # 4. Mark lecture as completed with detected language
        supabase.table("lectures").update(
            {"status": "completed", "language": detected_lang}
        ).eq("id", lecture_id).execute()

    except Exception as e:
        supabase.table("lectures").update({"status": "failed"}).eq(
            "id", lecture_id
        ).execute()
        print(f"[ASR PIPELINE ERROR]: {str(e)}")

    finally:
        if local_audio_path and os.path.exists(local_audio_path):
            try:
                os.remove(local_audio_path)
            except OSError:
                pass
        if (
            original_file_path
            and os.path.exists(original_file_path)
            and original_file_path != local_audio_path
        ):
            try:
                os.remove(original_file_path)
            except OSError:
                pass


@app.post("/ingest/youtube")
def ingest_youtube_lecture(payload: IngestYouTubeRequest):
    user_id = "74a53efe-4184-4c33-bffa-ab99456c5ffb"

    lecture_id = None
    local_audio_path = None

    try:
        # 1. Download YouTube Audio
        audio_info = download_youtube_audio(payload.youtube_url, user_id)
        local_audio_path = audio_info.get("local_wav_path") or audio_info.get(
            "local_mp3_path"
        )

        # 2. Insert initial record into 'lectures' table
        lecture_data = {
            "user_id": user_id,
            "title": audio_info.get("title", "Untitled Lecture"),
            "source_type": "youtube",
            "source_url": payload.youtube_url,
            "media_bucket_path": audio_info.get("bucket_path"),
            "status": "processing",
        }
        res = supabase.table("lectures").insert(lecture_data).execute()

        if not res.data:
            raise RuntimeError(
                "Failed to insert lecture record into Supabase database."
            )

        lecture_record = res.data[0]
        lecture_id = lecture_record["id"]

        # 3. Transcribe Audio via Pan-India Multilingual ASR
        asr_result = transcribe_multilingual_audio(
            file_path=local_audio_path, language_code="unknown", mode="codemix"
        )

        detected_lang = asr_result["detected_language"]
        segments = asr_result["segments"]

        # 4. Build Semantic Chunks
        chunks = build_semantic_chunks_multilingual(segments, target_duration=45.0)

        # 5. Batch insert chunks into 'transcript_chunks' table
        db_chunks = []
        for index, chunk in enumerate(chunks):
            db_chunks.append(
                {
                    "lecture_id": lecture_id,
                    "chunk_index": index,
                    "text_content": chunk["chunk_text"],
                    "start_time": chunk["start_time"],
                    "end_time": chunk["end_time"],
                    "language": detected_lang,
                }
            )

        if db_chunks:
            supabase.table("transcript_chunks").insert(db_chunks).execute()

        # 6. Update lecture status to 'completed' with detected language
        supabase.table("lectures").update(
            {"status": "completed", "language": detected_lang}
        ).eq("id", lecture_id).execute()

        return {
            "status": "success",
            "lecture_id": lecture_id,
            "title": audio_info.get("title"),
            "detected_language": detected_lang,
            "chunks_processed": len(chunks),
        }

    except Exception as e:
        if lecture_id:
            try:
                supabase.table("lectures").update({"status": "failed"}).eq(
                    "id", lecture_id
                ).execute()
            except Exception:
                pass

        print(f"[INGESTION ERROR]: {str(e)}")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {str(e)}",
        )

    finally:
        if local_audio_path and os.path.exists(local_audio_path):
            try:
                os.remove(local_audio_path)
            except OSError:
                pass


@app.post("/ingest/upload")
async def ingest_uploaded_lecture(
    background_tasks: BackgroundTasks, file: UploadFile = File(...)
):
    """
    Handles direct file uploads (.mp3, .mp4, .mkv, .wav),
    validates file integrity, uploads audio to Supabase storage, and
    triggers non-blocking background ingestion.
    """
    # Active Supabase User UUID for local dev testing
    user_id = "74a53efe-4184-4c33-bffa-ab99456c5ffb"

    temp_original_path = None
    extracted_mp3_path = None

    try:
        # 1. Validate size and save stream locally
        temp_original_path = validate_and_save_upload(file)

        # 2. Convert to compressed MP3
        extracted_mp3_path = convert_to_mp3_if_needed(temp_original_path)

        # 3. Calculate Media Duration
        duration_sec = get_media_duration_seconds(extracted_mp3_path)

        # 4. Upload MP3 to Supabase Bucket ('lectures')
        unique_file_id = str(uuid.uuid4())
        bucket_path = f"{user_id}/{unique_file_id}.mp3"

        with open(extracted_mp3_path, "rb") as f:
            supabase.storage.from_("lectures").upload(
                path=bucket_path,
                file=f,
                file_options={"content-type": "audio/mpeg", "upsert": "true"},
            )

        # 5. Insert Initial Lecture Record into Supabase
        lecture_data = {
            "user_id": user_id,
            "title": file.filename or "Uploaded Lecture",
            "source_type": "file_upload",
            "source_url": bucket_path,
            "media_bucket_path": bucket_path,
            "status": "processing",
        }
        res = supabase.table("lectures").insert(lecture_data).execute()

        if not res.data:
            raise RuntimeError("Failed to insert lecture record into Supabase.")

        lecture_id = res.data[0]["id"]

        # 6. Dispatch Background Task
        background_tasks.add_task(
            process_ingestion_pipeline,
            lecture_id=lecture_id,
            local_audio_path=extracted_mp3_path,
            original_file_path=temp_original_path,
            user_id=user_id,
        )

        return {
            "status": "queued",
            "lecture_id": lecture_id,
            "title": file.filename,
            "duration_seconds": round(duration_sec, 2),
            "message": "File uploaded successfully. Processing started in background.",
        }

    except Exception as e:
        if extracted_mp3_path and os.path.exists(extracted_mp3_path):
            try:
                os.remove(extracted_mp3_path)
            except OSError:
                pass
        if (
            temp_original_path
            and os.path.exists(temp_original_path)
            and temp_original_path != extracted_mp3_path
        ):
            try:
                os.remove(temp_original_path)
            except OSError:
                pass

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File upload ingestion failed: {str(e)}",
        )


@app.post("/ingest/upload-chunk")
async def upload_audio_chunk(file: UploadFile = File(...)):
    """
    Receives audio chunks from the Chrome Extension.
    """
    try:
        file_path = os.path.join(UPLOAD_DIR, file.filename)

        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        print(
            f"✅ Successfully received audio chunk: {file.filename} ({len(content)} bytes)"
        )

        return {
            "status": "success",
            "filename": file.filename,
            "bytes_received": len(content),
        }
    except Exception as e:
        print(f"❌ Error saving audio chunk: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest/finalize-stream")
async def finalize_stream(payload: FinalizeStreamRequest):
    """
    Finalizes a stream recording session triggered by the Chrome Extension.
    Matches uploaded chunks in `temp_chunks` for the session_id.
    """
    try:
        session_id = payload.session_id
        matching_chunks = [
            f for f in os.listdir(UPLOAD_DIR) if session_id in f and f.endswith(".webm")
        ]

        print(
            f"🏁 Finalizing stream session '{session_id}'. Chunks received: {len(matching_chunks)}"
        )

        return {
            "status": "completed",
            "session_id": session_id,
            "chunks_found": len(matching_chunks),
            "message": "Stream finalized successfully.",
        }
    except Exception as e:
        print(f"❌ Error finalizing stream session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
