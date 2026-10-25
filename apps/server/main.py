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
from datetime import datetime, timezone
from typing import List, Optional

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
    Response,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from temporal_chunker import align_multimodal_chunks
from embedding_engine import index_multimodal_chunks

import cache
from auth import get_current_user
from storage_utils import supabase
from query_router import classify_intent, hybrid_intelligent_router
from synthesizer import remember_chunk_times, synthesize_answer
from cheat_sheet_engine import generate_cheat_sheet
from study_artifacts_engine import (
    cached_summary,
    generate_study_set,
    generate_summary,
    lecture_owner_id,
    summary_running,
)
from translator import LANGUAGES, MAX_TEXTS_PER_REQUEST, translate_texts
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
        print(
            f"[ASR SETUP ERROR] Could not load the Whisper model yet: {e}", flush=True
        )


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


class TranslateRequest(BaseModel):
    texts: List[str]
    language: str


NOTE_KINDS = ("note", "answer", "flashcard", "formula")
NOTE_COLUMNS = (
    "id, lecture_id, kind, title, body, timestamp_seconds, created_at, updated_at"
)


class NoteCreateRequest(BaseModel):
    kind: str = "note"
    title: str = ""
    body: str = ""
    timestamp_seconds: Optional[float] = None


class NoteUpdateRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None


@app.get("/")
def root_check():
    return {"message": "VidyaPulse AI Engine is running."}


@app.get("/db-check")
def db_check():
    return {"status": "ok"}


@app.get("/cache/stats")
def cache_stats():
    """Task 19: Which cache is in use (redis or memory) and its hit rate since startup."""
    return cache.stats()


# Rows per Supabase insert, so a 4-hour lecture's thousands of Whisper segments are not one huge request
SEGMENT_INSERT_BATCH_SIZE = 500


def insert_in_batches(table: str, rows: List[dict], batch_size: int) -> None:
    for start in range(0, len(rows), batch_size):
        supabase.table(table).insert(rows[start : start + batch_size]).execute()


def transcribe_or_raise(file_path: str) -> dict:
    """Local Whisper ASR. Raises when it failed, so the lecture is marked failed, not empty."""
    from asr_engine import transcribe_multilingual_audio

    asr_result = transcribe_multilingual_audio(
        file_path=file_path,
        language_code="unknown",  # Auto-detects hi-IN, ta-IN, te-IN, kn-IN, mr-IN, etc.
        mode="codemix",  # Ideal for Hinglish, Tanglish, and technical code-switching
    )
    if asr_result.get("error"):
        raise RuntimeError(f"Transcription failed: {asr_result['error']}")
    return asr_result


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
        asr_result = transcribe_or_raise(local_audio_path)

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

        insert_in_batches("transcript_chunks", db_chunks, SEGMENT_INSERT_BATCH_SIZE)

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


# A plain def, not async: FastAPI runs it in its threadpool, so a long lecture being
# transcribed doesn't freeze /chat/ask and every other request until it finishes
@app.post("/ingest/youtube")
def ingest_video_pipeline(
    payload: IngestYouTubeRequest, background_tasks: BackgroundTasks
):
    import yt_dlp
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
        asr_result = transcribe_or_raise(video_path)
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
        if not multimodal_chunks:
            raise RuntimeError(
                "No speech or slide text was found in this video, so there is nothing to index."
            )

        print("[4/4] Generating Embeddings and Storing in Database...")
        if not index_multimodal_chunks(chunks=multimodal_chunks, lecture_id=lecture_id):
            raise RuntimeError(
                "Embedding or saving the lecture's chunks failed; see the [EMBEDDING] lines above."
            )

        # Mark the lecture as successfully completed
        supabase.table("lectures").update(
            {"status": "completed", "language": detected_lang}
        ).eq("id", lecture_id).execute()

        print("--- INGESTION COMPLETE ---")

        # TASK 15: Build the cheat sheet after the response is sent
        background_tasks.add_task(generate_cheat_sheet, lecture_id)
        # TASK 16: Flashcards + quiz, queued after the cheat sheet so the two Gemini jobs run one at a time
        background_tasks.add_task(generate_study_set, lecture_id)
        # TASK 18: The workspace summary, one more Gemini call after the study set
        background_tasks.add_task(generate_summary, lecture_id)

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
def ingest_uploaded_lecture(
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
def test_query_router(payload: RouterTestRequest):
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
    A summary question is answered from the stored summary when there is one, with no Gemini call.
    """
    try:
        if classify_intent(payload.query) == "overview":
            stored = cached_summary(payload.lecture_id)
            if stored:
                print(
                    "[SUMMARY] Answering a summary question with the stored summary (no Gemini call).",
                    flush=True,
                )
                return {
                    "query": payload.query,
                    "intent": "overview",
                    "grounded": True,
                    "sources": [],
                    "cached": True,
                    **stored,
                }
        return synthesize_answer(payload.query, payload.lecture_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def migration_hint(error: Exception, migration: str) -> str:
    """The Supabase error, plus which migration to run when it is a missing table or kind."""
    text = str(error)
    if any(s in text for s in ("PGRST205", "does not exist", "_check")):
        return (
            f"{text} Run apps/server/migrations/{migration} in the Supabase SQL editor."
        )
    return text


@app.get("/lectures/{lecture_id}/cheatsheet")
def get_cheat_sheet(lecture_id: str):
    """
    Task 15: Returns the stored cheat sheet and its generation status.
    """
    try:
        res = (
            supabase.table("cheat_sheets")
            .select("lecture_id, status, content, topic_tags, model, error, updated_at")
            .eq("lecture_id", lecture_id)
            .execute()
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=migration_hint(e, "004_cheat_sheets.sql")
        )
    if not res.data:
        raise HTTPException(
            status_code=404, detail="No cheat sheet for this lecture yet."
        )
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
    Task 16: Returns the lecture's flashcards and quiz (and, since Task 18, its summary),
    keyed by kind, with their status.
    """
    try:
        res = (
            supabase.table("study_artifacts")
            .select("kind, status, content, model, error, updated_at")
            .eq("lecture_id", lecture_id)
            .execute()
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=migration_hint(e, "005_study_artifacts.sql")
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


@app.post("/lectures/{lecture_id}/summary", status_code=status.HTTP_202_ACCEPTED)
def regenerate_summary(lecture_id: str, background_tasks: BackgroundTasks):
    """
    Task 18: Queues (re)writing the lecture summary in the background, like the cheat sheet and
    study set; the workspace polls GET /study-artifacts for it. On a slow free tier this can take
    a few minutes, which is too long to hold a request open. A summary already being written is
    not started twice.
    """
    if summary_running(lecture_id):
        return {"status": "processing", "lecture_id": lecture_id}
    background_tasks.add_task(generate_summary, lecture_id)
    return {"status": "queued", "lecture_id": lecture_id}


@app.post("/translate")
def translate(payload: TranslateRequest):
    """
    Task 18: Translates workspace text (answers, summary, cheat sheet, flashcards, quiz and
    notes) for the language switch. Results are cached, so a repeat costs no Gemini call.
    """
    if payload.language not in LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language {payload.language!r}. Choose one of: {', '.join(LANGUAGES)}.",
        )
    if len(payload.texts) > MAX_TEXTS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"Send at most {MAX_TEXTS_PER_REQUEST} texts per request.",
        )
    try:
        translations = translate_texts(payload.texts, payload.language)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Translation failed: {e}")
    return {"language": payload.language, "translations": translations}


@app.get("/lectures/{lecture_id}/notes")
def list_notes(lecture_id: str):
    """
    Task 18: The student's notes for a lecture, oldest first.
    """
    try:
        res = (
            supabase.table("notes")
            .select(NOTE_COLUMNS)
            .eq("lecture_id", lecture_id)
            .order("created_at")
            .execute()
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=migration_hint(e, "006_workspace.sql")
        )
    return {"notes": res.data or []}


@app.post("/lectures/{lecture_id}/notes", status_code=status.HTTP_201_CREATED)
def create_note(lecture_id: str, payload: NoteCreateRequest):
    """
    Task 18: Saves a note: an AI answer, a flashcard, a formula, or the student's own text.
    Owned by the lecture's user, like the cheat sheet and study sets.
    """
    if payload.kind not in NOTE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of: {', '.join(NOTE_KINDS)}.",
        )
    if not payload.title.strip() and not payload.body.strip():
        raise HTTPException(
            status_code=400, detail="A note needs a title or some text."
        )
    try:
        user_id = lecture_owner_id(lecture_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        res = (
            supabase.table("notes")
            .insert(
                {
                    "lecture_id": lecture_id,
                    "user_id": user_id,
                    "kind": payload.kind,
                    "title": payload.title.strip(),
                    "body": payload.body.strip(),
                    "timestamp_seconds": payload.timestamp_seconds,
                }
            )
            .execute()
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=migration_hint(e, "006_workspace.sql")
        )
    return res.data[0]


@app.patch("/notes/{note_id}")
def update_note(note_id: str, payload: NoteUpdateRequest):
    """
    Task 18: Edits a note's title or text.
    """
    changes = {k: v.strip() for k, v in payload.model_dump(exclude_none=True).items()}
    if not changes:
        raise HTTPException(status_code=400, detail="Send a title or body to change.")
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        res = supabase.table("notes").update(changes).eq("id", note_id).execute()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=migration_hint(e, "006_workspace.sql")
        )
    if not res.data:
        raise HTTPException(status_code=404, detail="Note not found.")
    return res.data[0]


@app.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: str):
    """
    Task 18: Deletes a note.
    """
    try:
        res = supabase.table("notes").delete().eq("id", note_id).execute()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=migration_hint(e, "006_workspace.sql")
        )
    if not res.data:
        raise HTTPException(status_code=404, detail="Note not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/lectures/{lecture_id}/export")
def get_export_bundle(lecture_id: str):
    """
    Task 18: Everything the PDF export page prints, in one request: the lecture, its summary,
    cheat sheet, flashcards, quiz and notes. A part that is missing or fails to load is null,
    with the reason in "warnings".
    """
    try:
        lecture = (
            supabase.table("lectures")
            .select("id, title, source_type, source_url")
            .eq("id", lecture_id)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not lecture.data:
        raise HTTPException(status_code=404, detail="Lecture not found.")

    warnings: List[str] = []

    def load(label: str, migration: str, query):
        try:
            return query().data or []
        except Exception as e:
            warnings.append(f"Could not load {label}: {migration_hint(e, migration)}")
            return []

    sheets = load(
        "the cheat sheet",
        "004_cheat_sheets.sql",
        lambda: supabase.table("cheat_sheets")
        .select("status, content, topic_tags, updated_at")
        .eq("lecture_id", lecture_id)
        .execute(),
    )
    artifacts = load(
        "the summary and study sets",
        "005_study_artifacts.sql",
        lambda: supabase.table("study_artifacts")
        .select("kind, status, content, updated_at")
        .eq("lecture_id", lecture_id)
        .execute(),
    )
    notes = load(
        "notes",
        "006_workspace.sql",
        lambda: supabase.table("notes")
        .select(NOTE_COLUMNS)
        .eq("lecture_id", lecture_id)
        .order("created_at")
        .execute(),
    )
    by_kind = {row["kind"]: row for row in artifacts}

    return {
        "lecture": lecture.data[0],
        "summary": by_kind.get("summary"),
        "cheat_sheet": sheets[0] if sheets else None,
        "flashcards": by_kind.get("flashcards"),
        "quiz": by_kind.get("quiz"),
        "notes": notes,
        "warnings": warnings,
    }


# PostgREST caps each response at 1000 rows, so long lectures are read page by page
TRANSCRIPT_PAGE_SIZE = 1000


def fetch_all_rows(table: str, columns: str, lecture_id: str, order: str):
    rows, offset = [], 0
    while True:
        res = (
            supabase.table(table)
            .select(columns)
            .eq("lecture_id", lecture_id)
            .order(order)
            .range(offset, offset + TRANSCRIPT_PAGE_SIZE - 1)
            .execute()
        )
        page = res.data or []
        rows.extend(page)
        if len(page) < TRANSCRIPT_PAGE_SIZE:
            return rows
        offset += TRANSCRIPT_PAGE_SIZE


@app.get("/lectures/{lecture_id}/transcript")
def get_transcript(lecture_id: str):
    """
    Task 17: Returns the lecture's timed transcript for the synced sidebar.
    YouTube ingestion writes multimodal_chunks; uploads only write Whisper segments
    to transcript_chunks, so fall back to those when there are no multimodal chunks.
    """
    chunks = fetch_all_rows(
        "multimodal_chunks",
        "id, chunk_index, start_time_seconds, end_time_seconds, transcript_text",
        lecture_id,
        "chunk_index",
    )
    if chunks:
        # Opening the lecture warms the chunk time map, so the first answer cites without a lookup
        remember_chunk_times(lecture_id, chunks)
        segments = [
            {
                "start": c["start_time_seconds"],
                "end": c["end_time_seconds"],
                "text": c["transcript_text"],
            }
            for c in chunks
        ]
    else:
        segments = [
            {"start": c["start_time"], "end": c["end_time"], "text": c["text_content"]}
            for c in fetch_all_rows(
                "transcript_chunks",
                "chunk_index, start_time, end_time, text_content",
                lecture_id,
                "chunk_index",
            )
        ]

    segments = [
        s for s in segments if s["start"] is not None and (s["text"] or "").strip()
    ]
    if not segments:
        raise HTTPException(
            status_code=404, detail="No transcript for this lecture yet."
        )
    return {"lecture_id": lecture_id, "segments": segments}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
