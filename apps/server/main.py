import faulthandler
import os
import sys
import threading
import time

# Nothing below makes a network call or loads a heavy library at import time.
# yt-dlp, static-ffmpeg, faster-whisper and OpenCV are imported only where they are used.
print("[STARTUP] Importing modules...", flush=True)
_import_started = time.monotonic()
SLOW_IMPORT_SECONDS = float(os.getenv("STARTUP_SLOW_IMPORT_SECONDS", "60"))


def _report_slow_import() -> None:
    """Prints which line the import is on every 60s; the server keeps loading meanwhile."""
    global _slow_import_timer
    print(
        f"\n[STARTUP] Still importing after {time.monotonic() - _import_started:.0f}s. "
        "In the thread that ends in main.py '<module>', the top 'File' line is what is slow:",
        file=sys.stderr,
        flush=True,
    )
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    _slow_import_timer = threading.Timer(SLOW_IMPORT_SECONDS, _report_slow_import)
    _slow_import_timer.daemon = True
    _slow_import_timer.start()


_slow_import_timer = threading.Timer(SLOW_IMPORT_SECONDS, _report_slow_import)
_slow_import_timer.daemon = True
_slow_import_timer.start()

from contextlib import asynccontextmanager

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

from temporal_chunker import align_multimodal_chunks
from embedding_engine import index_multimodal_chunks

from auth import get_current_user
from storage_utils import supabase
from query_router import hybrid_intelligent_router
from synthesizer import synthesize_answer
from cheat_sheet_engine import generate_cheat_sheet
from study_artifacts_engine import generate_study_set
from media_validator import (
    validate_and_save_upload,
    convert_to_mp3_if_needed,
    get_media_duration_seconds,
)

_slow_import_timer.cancel()
print(
    f"[STARTUP] Modules imported in {time.monotonic() - _import_started:.1f}s.",
    flush=True,
)


def warm_whisper_model() -> None:
    try:
        from asr_engine import get_whisper_model

        get_whisper_model()
    except Exception as e:
        # Not fatal: the first transcription tries to load it again
        print(f"[ASR SETUP ERROR] Could not load the Whisper model yet: {e}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Puts the bundled ffmpeg on PATH; it downloads only on the very first run
    print("[STARTUP] Adding ffmpeg to PATH...", flush=True)
    import static_ffmpeg

    static_ffmpeg.add_paths()
    # Warm the local Whisper model in the background so startup completes immediately;
    # the first transcription waits for it if it is still loading
    threading.Thread(target=warm_whisper_model, daemon=True).start()
    print("[STARTUP] Ready. Whisper keeps loading in the background.", flush=True)
    yield


app = FastAPI(title="VidyaPulse AI Engine", lifespan=lifespan)

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

class RouterTestRequest(BaseModel):
    query: str
    lecture_id: str
    
class ChatAskRequest(BaseModel):
    query: str
    lecture_id: str


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
    # Heavy libraries (faster-whisper, OpenCV) load on the first ingestion, not at server boot
    from asr_engine import transcribe_multilingual_audio
    from vision_extractor import process_video_keyframes

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

        # 2 & 3. Insert Whisper segments directly into Supabase transcript_chunks table
        db_chunks = []
        for index, segment in enumerate(segments):
            db_chunks.append(
                {
                    "lecture_id": lecture_id,
                    "chunk_index": index,
                    "text_content": segment["text"],
                    "start_time": segment["start_time_seconds"],
                    "end_time": segment["end_time_seconds"],
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
async def ingest_video_pipeline(
    payload: IngestYouTubeRequest, background_tasks: BackgroundTasks
):
    import yt_dlp
    from asr_engine import transcribe_multilingual_audio
    from vision_extractor import process_video_keyframes

    youtube_url = payload.youtube_url
    user_id = "74a53efe-4184-4c33-bffa-ab99456c5ffb"

    # Generate a temporary path for downloading the media
    temp_id = str(uuid.uuid4())
    video_path = f"temp_chunks/{temp_id}.mp4"
    video_title = "YouTube Lecture"
    lecture_id = None

    print(f"--- DOWNLOADING YOUTUBE VIDEO: {youtube_url} ---")
    try:
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "outtmpl": video_path,
            "quiet": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # extract_info grabs the video title and downloads it simultaneously
            info = ydl.extract_info(youtube_url, download=True)
            video_title = info.get("title", video_title)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to download YouTube video: {e}"
        )

    try:
        # 0. Create the parent record in 'lectures' table so Foreign Keys (like keyframes) are satisfied
        lecture_data = {
            "user_id": user_id,
            "title": video_title,
            "source_type": "youtube",
            "source_url": youtube_url,
            "status": "processing",
        }
        res = supabase.table("lectures").insert(lecture_data).execute()
        if not res.data:
            raise RuntimeError("Failed to create lecture record in Supabase.")

        # Grab the real database-generated ID
        lecture_id = res.data[0]["id"]
        print(f"--- STARTING UNIFIED INGESTION FOR LECTURE {lecture_id} ---")

        # ==========================================
        # TASK 9: Audio Transcription (Local Whisper)
        # ==========================================
        print("[1/4] Running Audio Transcription...")
        asr_result = transcribe_multilingual_audio(
            file_path=video_path, language_code="unknown", mode="codemix"
        )
        transcript_segments = asr_result["segments"]
        detected_lang = asr_result["detected_language"]

        # ==========================================
        # TASK 10: Vision & OCR Extraction
        # ==========================================
        print("[2/4] Running Vision & OCR Extraction...")
        keyframes_metadata = process_video_keyframes(
            video_path=video_path,
            lecture_id=lecture_id,
            user_id=user_id,
            ssim_threshold=0.70,  # Stricter threshold to avoid Gemini 429 Quota Error
        )

        # ==========================================
        # TASK 11: Temporal Sync & Chunking
        # ==========================================
        print("[3/4] Synchronizing Multimodal Chunks...")
        multimodal_chunks = align_multimodal_chunks(
            transcript_segments=transcript_segments,
            keyframes_data=keyframes_metadata,
            lecture_id=lecture_id,
            window_size=300,
            overlap_size=50,
            language=detected_lang,
        )

        # ==========================================
        # TASK 12: Multilingual Vector Embedding
        # ==========================================
        print("[4/4] Generating Embeddings and Storing in Database...")
        index_multimodal_chunks(chunks=multimodal_chunks, lecture_id=lecture_id)

        # Mark the lecture as successfully completed
        supabase.table("lectures").update(
            {"status": "completed", "language": detected_lang}
        ).eq("id", lecture_id).execute()

        print("--- INGESTION COMPLETE ---")

        # TASK 15: Build the cheat sheet after the response is sent
        background_tasks.add_task(generate_cheat_sheet, lecture_id)
        # TASK 16: Flashcards + quiz, queued after the cheat sheet so the two Gemini jobs run one at a time
        background_tasks.add_task(generate_study_set, lecture_id)

        return {
            "status": "success",
            "lecture_id": lecture_id,
            "title": video_title,
            "detected_language": detected_lang,
            "total_chunks_generated": len(multimodal_chunks),
            "data": multimodal_chunks,
        }

    except Exception as e:
        # If any step fails, safely update the database status to failed
        if lecture_id:
            try:
                supabase.table("lectures").update({"status": "failed"}).eq(
                    "id", lecture_id
                ).execute()
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Always clean up the temporary video file to prevent server disk overflow
        if os.path.exists(video_path):
            os.remove(video_path)


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

@app.post("/test/router")
async def test_query_router(payload: RouterTestRequest):
    """
    Test endpoint for Task 13: Hybrid Intelligent Query Router.
    """
    try:
        result = hybrid_intelligent_router(payload.query, payload.lecture_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/ask")
def chat_ask(payload: ChatAskRequest):
    """
    Task 14: Grounded LLM Synthesizer. Returns a cited answer with [MM:SS] deep-links.
    Declared as a sync route so FastAPI runs the blocking Gemini call in its threadpool.
    """
    try:
        return synthesize_answer(payload.query, payload.lecture_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/lectures/{lecture_id}/cheatsheet")
def get_cheat_sheet(lecture_id: str):
    """
    Task 15: Returns the stored cheat sheet and its generation status.
    """
    res = (
        supabase.table("cheat_sheets")
        .select("lecture_id, status, content, topic_tags, model, error, updated_at")
        .eq("lecture_id", lecture_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="No cheat sheet for this lecture yet.")
    return res.data[0]


@app.post("/lectures/{lecture_id}/cheatsheet", status_code=status.HTTP_202_ACCEPTED)
def regenerate_cheat_sheet(lecture_id: str, background_tasks: BackgroundTasks):
    """
    Task 15: Queues (re)generation of a lecture's cheat sheet in the background.
    """
    background_tasks.add_task(generate_cheat_sheet, lecture_id)
    return {"status": "queued", "lecture_id": lecture_id}


@app.get("/lectures/{lecture_id}/study-artifacts")
def get_study_artifacts(lecture_id: str):
    """
    Task 16: Returns the lecture's flashcards and quiz, keyed by kind, with their status.
    """
    res = (
        supabase.table("study_artifacts")
        .select("kind, status, content, model, error, updated_at")
        .eq("lecture_id", lecture_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=404, detail="No study artifacts for this lecture yet."
        )
    return {row["kind"]: row for row in res.data}


@app.post(
    "/lectures/{lecture_id}/study-artifacts", status_code=status.HTTP_202_ACCEPTED
)
def regenerate_study_artifacts(lecture_id: str, background_tasks: BackgroundTasks):
    """
    Task 16: Queues (re)generation of the lecture's flashcards and quiz in the background.
    """
    background_tasks.add_task(generate_study_set, lecture_id)
    return {"status": "queued", "lecture_id": lecture_id}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
