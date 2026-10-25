import io
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import cache
import main
from fakes import gemini_response
from lecture_factory import seed_four_hour_lecture

LECTURE = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def jobs(monkeypatch):
    """Records the background jobs an endpoint queues instead of running them."""
    queued = []
    for name in ("generate_cheat_sheet", "generate_study_set", "generate_summary"):
        monkeypatch.setattr(
            main, name, lambda lecture_id, _n=name: queued.append((_n, lecture_id))
        )
    monkeypatch.setattr(
        main, "process_ingestion_pipeline", lambda **kw: queued.append(("pipeline", kw))
    )
    return queued


@pytest.fixture
def lecture(db):
    db.seed(
        "lectures",
        [
            {
                "id": LECTURE,
                "user_id": "user-1",
                "title": "Calculus",
                "source_type": "youtube",
                "source_url": "https://youtu.be/x",
            }
        ],
    )
    return LECTURE


def seed_chunks(db, count, lecture_id=LECTURE):
    db.seed(
        "multimodal_chunks",
        [
            {
                "lecture_id": lecture_id,
                "chunk_index": i,
                "start_time_seconds": i * 60.0,
                "end_time_seconds": (i + 1) * 60.0,
                "transcript_text": f"part {i} about integration",
                "composite_content": f"part {i} about integration",
            }
            for i in range(count)
        ],
    )


def test_health_endpoints(client):
    assert client.get("/").json() == {"message": "VidyaPulse AI Engine is running."}
    assert client.get("/db-check").json() == {"status": "ok"}
    assert client.get("/cache/stats").json()["backend"] == "memory"


def test_chat_ask_answers_and_then_serves_from_cache(client, db, lecture, gemini):
    seed_chunks(db, 3)
    gemini.replies.append(gemini_response("It is said at [01:00]."))
    body = {"query": "How many times did he say integration?", "lecture_id": LECTURE}

    first = client.post("/chat/ask", json=body).json()
    second = client.post("/chat/ask", json=body).json()
    assert first["grounded"] is True and first["cached"] is False
    assert second["cached"] is True and second["answer"] == first["answer"]
    assert len(gemini.calls) == 1


def test_chat_ask_uses_the_stored_summary_for_overview_questions(client, db, gemini):
    db.seed(
        "study_artifacts",
        [
            {
                "lecture_id": LECTURE,
                "kind": "summary",
                "status": "completed",
                "model": "m",
                "content": {"answer": "Stored [00:00].", "citations": []},
            }
        ],
    )
    result = client.post(
        "/chat/ask", json={"query": "Give me a summary", "lecture_id": LECTURE}
    ).json()
    assert result["answer"] == "Stored [00:00]." and result["cached"] is True
    assert gemini.calls == []


def test_chat_ask_reports_failures(client, db, embedder):
    embedder.errors.append(RuntimeError("503 UNAVAILABLE"))
    response = client.post(
        "/chat/ask", json={"query": "Explain limits", "lecture_id": LECTURE}
    )
    assert response.status_code == 500
    assert "Failed to generate embedding" in response.json()["detail"]


def test_router_test_endpoint(client, db):
    seed_chunks(db, 2)
    result = client.post(
        "/test/router", json={"query": "say integration", "lecture_id": LECTURE}
    ).json()
    assert result["intent"] == "literal" and len(result["context_blocks"]) == 2
    db.fail("multimodal_chunks", RuntimeError("down"))
    assert (
        client.post(
            "/test/router", json={"query": "say calculus", "lecture_id": LECTURE}
        ).status_code
        == 500
    )


def test_cheat_sheet_endpoints(client, db, jobs):
    assert client.get(f"/lectures/{LECTURE}/cheatsheet").status_code == 404
    db.seed(
        "cheat_sheets",
        [{"lecture_id": LECTURE, "status": "completed", "content": {"formulas": []}}],
    )
    assert client.get(f"/lectures/{LECTURE}/cheatsheet").json()["status"] == "completed"
    db.fail("cheat_sheets", RuntimeError("PGRST205 relation does not exist"))
    detail = client.get(f"/lectures/{LECTURE}/cheatsheet").json()["detail"]
    assert "Run apps/server/migrations/004_cheat_sheets.sql" in detail
    assert client.post(f"/lectures/{LECTURE}/cheatsheet").status_code == 202
    assert jobs == [("generate_cheat_sheet", LECTURE)]


def test_study_artifact_endpoints(client, db, jobs):
    assert client.get(f"/lectures/{LECTURE}/study-artifacts").status_code == 404
    db.seed(
        "study_artifacts",
        [{"lecture_id": LECTURE, "kind": "quiz", "status": "completed", "content": []}],
    )
    assert list(client.get(f"/lectures/{LECTURE}/study-artifacts").json()) == ["quiz"]
    db.fail("study_artifacts", RuntimeError("boom"))
    assert client.get(f"/lectures/{LECTURE}/study-artifacts").json()["detail"] == "boom"
    assert (
        client.post(f"/lectures/{LECTURE}/study-artifacts").json()["status"] == "queued"
    )
    assert jobs == [("generate_study_set", LECTURE)]


def test_summary_is_not_queued_twice(client, jobs, monkeypatch):
    assert client.post(f"/lectures/{LECTURE}/summary").json()["status"] == "queued"
    monkeypatch.setattr(main, "summary_running", lambda lecture_id: True)
    assert client.post(f"/lectures/{LECTURE}/summary").json()["status"] == "processing"
    assert jobs == [("generate_summary", LECTURE)]


def test_translate_validation_and_errors(client, monkeypatch):
    assert (
        client.post("/translate", json={"texts": ["hi"], "language": "fr"}).status_code
        == 400
    )
    too_many = ["x"] * (main.MAX_TEXTS_PER_REQUEST + 1)
    assert (
        client.post(
            "/translate", json={"texts": too_many, "language": "hi"}
        ).status_code
        == 400
    )
    assert client.post(
        "/translate", json={"texts": ["Hello"], "language": "en"}
    ).json() == {
        "language": "en",
        "translations": ["Hello"],
    }

    def explode(texts, language):
        raise RuntimeError("quota")

    monkeypatch.setattr(main, "translate_texts", explode)
    assert (
        client.post("/translate", json={"texts": ["Hello"], "language": "hi"}).json()[
            "detail"
        ]
        == "Translation failed: quota"
    )


def test_notes_crud(client, db, lecture):
    url = f"/lectures/{LECTURE}/notes"
    assert client.post(url, json={"kind": "poem", "body": "x"}).status_code == 400
    assert client.post(url, json={"title": " ", "body": ""}).status_code == 400
    assert client.post("/lectures/missing/notes", json={"body": "x"}).status_code == 404

    note = client.post(
        url,
        json={
            "kind": "formula",
            "title": " Chain rule ",
            "body": "$f(g(x))'$",
            "timestamp_seconds": 61,
        },
    ).json()
    assert note["title"] == "Chain rule" and note["user_id"] == "user-1"
    assert [n["id"] for n in client.get(url).json()["notes"]] == [note["id"]]

    assert client.patch(f"/notes/{note['id']}", json={}).status_code == 400
    assert (
        client.patch(f"/notes/{note['id']}", json={"body": " new "}).json()["body"]
        == "new"
    )
    assert client.patch("/notes/nope", json={"body": "x"}).status_code == 404
    assert client.delete(f"/notes/{note['id']}").status_code == 204
    assert client.delete(f"/notes/{note['id']}").status_code == 404


def test_notes_surface_database_errors(client, db, lecture):
    db.fail("notes", RuntimeError("PGRST205 notes does not exist"), times=5)
    assert (
        "006_workspace.sql" in client.get(f"/lectures/{LECTURE}/notes").json()["detail"]
    )
    assert (
        client.post(f"/lectures/{LECTURE}/notes", json={"body": "x"}).status_code == 500
    )
    assert client.patch("/notes/n1", json={"body": "x"}).status_code == 500
    assert client.delete("/notes/n1").status_code == 500
    db.fail("lectures", RuntimeError("bad uuid"))
    assert (
        client.post(f"/lectures/{LECTURE}/notes", json={"body": "x"}).status_code == 500
    )


def test_export_bundle_collects_everything_with_warnings(client, db, lecture):
    assert client.get("/lectures/nope/export").status_code == 404
    db.seed(
        "study_artifacts",
        [
            {
                "lecture_id": LECTURE,
                "kind": "summary",
                "status": "completed",
                "content": {"answer": "S"},
            }
        ],
    )
    db.seed(
        "notes", [{"lecture_id": LECTURE, "kind": "note", "title": "t", "body": "b"}]
    )
    db.fail("cheat_sheets", RuntimeError("PGRST205 cheat_sheets does not exist"))
    bundle = client.get(f"/lectures/{LECTURE}/export").json()
    assert bundle["lecture"]["title"] == "Calculus"
    assert bundle["summary"]["content"]["answer"] == "S"
    assert bundle["cheat_sheet"] is None and bundle["flashcards"] is None
    assert len(bundle["notes"]) == 1
    assert "004_cheat_sheets.sql" in bundle["warnings"][0]
    db.fail("lectures", RuntimeError("down"))
    assert client.get(f"/lectures/{LECTURE}/export").status_code == 500


def test_transcript_from_chunks_warms_the_citation_time_map(client, db):
    seed_chunks(db, 3)
    segments = client.get(f"/lectures/{LECTURE}/transcript").json()["segments"]
    assert [s["start"] for s in segments] == [0.0, 60.0, 120.0]
    db.reset_log()
    from synthesizer import lecture_chunk_times

    assert len(lecture_chunk_times(LECTURE)) == 3 and db.queries == []


def test_transcript_falls_back_to_whisper_segments_and_pages_long_lectures(client, db):
    db.seed(
        "transcript_chunks",
        [
            {
                "lecture_id": LECTURE,
                "chunk_index": i,
                "start_time": i * 6.0,
                "end_time": i * 6.0 + 6,
                "text_content": f"segment {i}",
            }
            for i in range(
                2401
            )  # a 4-hour upload: more rows than PostgREST returns at once
        ]
        + [
            {
                "lecture_id": LECTURE,
                "chunk_index": 9999,
                "start_time": None,
                "end_time": None,
                "text_content": "untimed",
            }
        ],
    )
    segments = client.get(f"/lectures/{LECTURE}/transcript").json()["segments"]
    assert len(segments) == 2401 and segments[-1]["start"] == 14400.0
    pages = [q.range_ for q in db.queries_on("transcript_chunks")]
    assert pages == [(0, 999), (1000, 1999), (2000, 2999)]
    assert client.get("/lectures/empty/transcript").status_code == 404


class FakeYoutubeDL:
    title = "Limits & Continuity"
    error = None

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download):
        if FakeYoutubeDL.error:
            raise FakeYoutubeDL.error
        with open(self.options["outtmpl"], "wb") as f:
            f.write(b"fake mp4")
        return {"title": FakeYoutubeDL.title}


@pytest.fixture
def youtube(stub, embedder):
    """Stubs yt-dlp, Whisper and the keyframe extractor; chunking and indexing run for real."""
    os.makedirs("temp_chunks", exist_ok=True)
    FakeYoutubeDL.error = None
    state = SimpleNamespace(
        asr={
            "segments": [
                {
                    "start_time_seconds": 0.0,
                    "end_time_seconds": 30.0,
                    "text": "limits " * 40,
                }
            ],
            "detected_language": "en",
        },
        keyframes=[
            {
                "timestamp_seconds": 5.0,
                "storage_path": "k.jpg",
                "extracted_text": "$\\lim_{x\\to0}$",
            }
        ],
    )
    stub("yt_dlp", YoutubeDL=FakeYoutubeDL)
    stub("asr_engine", transcribe_multilingual_audio=lambda **kw: state.asr)
    stub("vision_extractor", process_video_keyframes=lambda **kw: state.keyframes)
    return state


def lecture_status(db):
    return [row["status"] for row in db.tables["lectures"]]


def test_youtube_ingest_indexes_and_queues_the_study_jobs(client, db, youtube, jobs):
    result = client.post(
        "/ingest/youtube", json={"youtube_url": "https://youtu.be/abc"}
    ).json()
    assert result["status"] == "success" and result["title"] == "Limits & Continuity"
    assert result["total_chunks_generated"] == 1
    assert lecture_status(db) == ["completed"]
    assert len(db.tables["multimodal_chunks"]) == 1
    assert [name for name, _ in jobs] == [
        "generate_cheat_sheet",
        "generate_study_set",
        "generate_summary",
    ]
    assert os.listdir("temp_chunks") == []  # the downloaded video is removed


def test_youtube_ingest_marks_failed_when_transcription_fails(
    client, db, youtube, jobs
):
    youtube.asr = {
        "segments": [],
        "detected_language": "unknown",
        "error": "corrupt audio",
    }
    response = client.post(
        "/ingest/youtube", json={"youtube_url": "https://youtu.be/abc"}
    )
    assert (
        response.status_code == 500
        and "Transcription failed: corrupt audio" in response.json()["detail"]
    )
    assert lecture_status(db) == ["failed"] and jobs == []
    assert db.tables["multimodal_chunks"] == []


def test_youtube_ingest_of_a_silent_slide_video_indexes_the_slides(
    client, db, youtube, jobs
):
    youtube.asr = {"segments": [], "detected_language": "en"}
    assert (
        client.post("/ingest/youtube", json={"youtube_url": "u"}).json()[
            "total_chunks_generated"
        ]
        == 1
    )
    assert db.tables["multimodal_chunks"][0]["transcript_text"] == ""


def test_youtube_ingest_with_nothing_to_index_fails_clearly(client, db, youtube, jobs):
    youtube.asr = {"segments": [], "detected_language": "en"}
    youtube.keyframes = []
    response = client.post("/ingest/youtube", json={"youtube_url": "u"})
    assert "No speech or slide text" in response.json()["detail"]
    assert lecture_status(db) == ["failed"]


def test_youtube_ingest_fails_when_embedding_fails(client, db, youtube, jobs, embedder):
    embedder.errors.append(RuntimeError("429 RESOURCE_EXHAUSTED"))
    response = client.post("/ingest/youtube", json={"youtube_url": "u"})
    assert "Embedding or saving" in response.json()["detail"]
    assert lecture_status(db) == ["failed"] and jobs == []


def test_youtube_download_errors_and_db_errors(client, db, youtube, jobs):
    FakeYoutubeDL.error = RuntimeError("Video unavailable")
    response = client.post("/ingest/youtube", json={"youtube_url": "u"})
    assert (
        "Failed to download YouTube video: Video unavailable"
        in response.json()["detail"]
    )

    FakeYoutubeDL.error = None
    db.fail("lectures:insert", RuntimeError("insert refused"))
    assert (
        client.post("/ingest/youtube", json={"youtube_url": "u"}).json()["detail"]
        == "insert refused"
    )


def test_upload_ingest_queues_the_pipeline(client, db, jobs, monkeypatch, tmp_path):
    original = tmp_path / "talk.mp4"
    original.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    mp3 = tmp_path / "talk_extracted.mp3"
    mp3.write_bytes(b"ID3audio")
    monkeypatch.setattr(main, "validate_and_save_upload", lambda f: str(original))
    monkeypatch.setattr(main, "convert_to_mp3_if_needed", lambda p: str(mp3))
    monkeypatch.setattr(main, "get_media_duration_seconds", lambda p: 3725.456)

    result = client.post(
        "/ingest/upload", files={"file": ("talk.mp4", io.BytesIO(b"x"), "video/mp4")}
    ).json()
    assert result["status"] == "queued" and result["duration_seconds"] == 3725.46
    assert (
        db.storage.uploads[0]["bucket"] == "lectures"
        and db.storage.uploads[0]["bytes"] == b"ID3audio"
    )
    _, kwargs = jobs[0]
    assert kwargs["local_audio_path"] == str(mp3) and kwargs[
        "original_file_path"
    ] == str(original)


def test_upload_ingest_cleans_up_on_failure(client, db, jobs, monkeypatch, tmp_path):
    original = tmp_path / "talk.mkv"
    original.write_bytes(b"x")
    mp3 = tmp_path / "talk_extracted.mp3"
    mp3.write_bytes(b"y")
    monkeypatch.setattr(main, "validate_and_save_upload", lambda f: str(original))
    monkeypatch.setattr(main, "convert_to_mp3_if_needed", lambda p: str(mp3))
    monkeypatch.setattr(main, "get_media_duration_seconds", lambda p: 1.0)
    db.storage.error = RuntimeError("bucket missing")

    response = client.post(
        "/ingest/upload",
        files={"file": ("talk.mkv", io.BytesIO(b"x"), "video/x-matroska")},
    )
    assert response.status_code == 500 and "bucket missing" in response.json()["detail"]
    assert not original.exists() and not mp3.exists() and jobs == []


def test_extension_chunks_and_finalize(client):
    os.makedirs(main.UPLOAD_DIR, exist_ok=True)
    for name in (
        "chunk-session-1-1.webm",
        "chunk-session-1-2.webm",
        "chunk-session-2-1.webm",
    ):
        assert (
            client.post(
                "/ingest/upload-chunk",
                files={"file": (name, io.BytesIO(b"abc"), "audio/webm")},
            ).json()["bytes_received"]
            == 3
        )
    assert (
        client.post("/ingest/finalize-stream", json={"session_id": "session-1"}).json()[
            "chunks_found"
        ]
        == 2
    )
    bad = client.post(
        "/ingest/upload-chunk",
        files={"file": ("../../no/such/dir/x.webm", io.BytesIO(b"a"), "audio/webm")},
    )
    assert bad.status_code in (400, 422, 500)


def test_finalize_stream_reports_errors(client, monkeypatch):
    monkeypatch.setattr(
        main.os, "listdir", lambda path: (_ for _ in ()).throw(OSError("gone"))
    )
    assert (
        client.post("/ingest/finalize-stream", json={"session_id": "s"}).status_code
        == 500
    )


@pytest.fixture
def pipeline_stubs(stub):
    state = SimpleNamespace(
        asr={
            "segments": [
                {
                    "start_time_seconds": i * 6.0,
                    "end_time_seconds": i * 6.0 + 6,
                    "text": f"s{i}",
                }
                for i in range(1201)
            ],
            "detected_language": "ta",
        },
        keyframe_calls=[],
    )
    stub("asr_engine", transcribe_multilingual_audio=lambda **kw: state.asr)
    stub(
        "vision_extractor",
        process_video_keyframes=lambda **kw: state.keyframe_calls.append(kw),
    )
    return state


def test_upload_pipeline_saves_long_transcripts_in_batches(
    db, lecture, pipeline_stubs, tmp_path
):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3")
    video = tmp_path / "a.mp4"
    video.write_bytes(b"ftyp")
    main.process_ingestion_pipeline(LECTURE, str(audio), str(video), "user-1")

    inserts = db.queries_on("transcript_chunks", "insert")
    assert [len(q.payload) for q in inserts] == [500, 500, 201]
    assert db.tables["lectures"][0]["status"] == "completed"
    assert db.tables["lectures"][0]["language"] == "ta"
    assert pipeline_stubs.keyframe_calls[0]["ssim_threshold"] == 0.85
    assert not audio.exists() and not video.exists()


def test_upload_pipeline_marks_failed_transcriptions(
    db, lecture, pipeline_stubs, tmp_path
):
    pipeline_stubs.asr = {
        "segments": [],
        "detected_language": "unknown",
        "error": "decoder crashed",
    }
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3")
    main.process_ingestion_pipeline(LECTURE, str(audio))
    assert db.tables["lectures"][0]["status"] == "failed"
    assert db.tables["transcript_chunks"] == []
    assert pipeline_stubs.keyframe_calls == []  # audio only: no frame extraction


def test_lifespan_adds_ffmpeg_and_warms_whisper(stub):
    calls = []
    stub("static_ffmpeg", add_paths=lambda: calls.append("ffmpeg"))
    stub("asr_engine", get_whisper_model=lambda: calls.append("whisper"))
    with TestClient(main.app) as client:
        assert client.get("/").status_code == 200
    assert calls[0] == "ffmpeg"


def test_whisper_warmup_failure_is_not_fatal(stub, capsys):
    def explode():
        raise OSError("no disk")

    stub("asr_engine", get_whisper_model=explode)
    main.warm_whisper_model()
    assert "Could not load the Whisper model yet: no disk" in capsys.readouterr().out


def test_four_hour_lecture_end_to_end(client, db, gemini, embedder):
    """Overview, literal and semantic questions on a 4-hour lecture, cited past the 99-minute mark."""
    chunks = seed_four_hour_lecture(db, LECTURE)
    last = chunks[-1]["start_time_seconds"]
    label = f"{int(last) // 60:02d}:{int(last) % 60:02d}"
    gemini.default = lambda call: gemini_response(
        f"Covered at [00:00] and at the end [{label}]."
    )

    overview = client.post(
        "/chat/ask", json={"query": "Give me a summary", "lecture_id": LECTURE}
    ).json()
    assert overview["sources"][0]["start_time_seconds"] == 0.0
    assert overview["sources"][-1]["start_time_seconds"] == last
    assert [c["label"] for c in overview["citations"]] == ["00:00", label]
    assert int(label.split(":")[0]) > 99

    literal = client.post(
        "/chat/ask",
        json={"query": "How many times did he say 'taylor'?", "lecture_id": LECTURE},
    ).json()
    assert literal["intent"] == "literal" and literal["sources"]
    # Taylor series is taught from 3:00:00 to 3:30:00; a chunk may start a little before
    assert all(
        3 * 3600 - 300 <= s["start_time_seconds"] <= 3.5 * 3600
        for s in literal["sources"]
    )

    semantic = client.post(
        "/chat/ask",
        json={"query": "Explain integration by parts", "lecture_id": LECTURE},
    ).json()
    assert semantic["intent"] == "semantic" and len(semantic["sources"]) == 8
    calls = len(gemini.calls)
    again = client.post(
        "/chat/ask",
        json={"query": "explain integration by parts", "lecture_id": LECTURE},
    ).json()
    assert again["cached"] is True and len(gemini.calls) == calls
    assert cache.stats()["hits"] > 0
