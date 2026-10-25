import threading

import pytest

import cache
import study_artifacts_engine as engine
from fakes import gemini_response
from gemini_utils import GeminiKeyError
from lecture_factory import seed_four_hour_lecture
from study_artifacts_engine import Flashcard, QuizQuestion, StudySet

LECTURE = "lec-study"


@pytest.fixture
def lecture(db):
    db.seed("lectures", [{"id": LECTURE, "user_id": "user-9"}])
    db.seed(
        "multimodal_chunks",
        [
            {
                "lecture_id": LECTURE,
                "chunk_index": i,
                "start_time_seconds": i * 60.0,
                "end_time_seconds": (i + 1) * 60.0,
                "composite_content": f"idea {i}",
            }
            for i in range(3)
        ],
    )
    return LECTURE


def quiz(
    question="Q?",
    options=("a", "b", "c", "d"),
    correct=1,
    explanations=("1", "2", "3", "4"),
    timestamp="00:30",
):
    return QuizQuestion(
        question=question,
        options=list(options),
        correct_index=correct,
        option_explanations=list(explanations),
        timestamp=timestamp,
    )


def test_sample_chunks_keeps_short_lectures_whole(monkeypatch):
    chunks = [{"composite_content": "x" * 100} for _ in range(10)]
    assert engine.sample_chunks(chunks) == chunks
    monkeypatch.setattr(engine, "MAX_CONTEXT_CHARS", 300)
    sampled = engine.sample_chunks(chunks)
    assert len(sampled) == 3 and sampled[0] is chunks[0]


def test_four_hour_lecture_is_sampled_to_one_call(db):
    seed_four_hour_lecture(db, LECTURE)
    chunks = engine.fetch_lecture_chunks(LECTURE)
    sampled = engine.sample_chunks(chunks)
    assert sum(len(c["composite_content"]) for c in sampled) <= engine.MAX_CONTEXT_CHARS
    assert (
        sampled[0]["chunk_index"] == 0
        and sampled[-1]["chunk_index"] > len(chunks) * 0.9
    )


def test_clean_flashcards_drops_blanks_and_caps_the_count():
    chunks = [{"start_time_seconds": 0.0, "end_time_seconds": 60.0}]
    cards = [
        Flashcard(question=f"Q{i}", answer="A", timestamp="00:10") for i in range(12)
    ]
    cards.insert(0, Flashcard(question=" ", answer="A", timestamp="00:10"))
    cleaned = engine.clean_flashcards(cards, chunks)
    assert len(cleaned) == engine.FLASHCARD_COUNT
    assert cleaned[0] == {"question": "Q0", "answer": "A", "timestamp_seconds": 10.0}


def test_clean_quiz_drops_malformed_questions():
    chunks = [{"start_time_seconds": 0.0, "end_time_seconds": 60.0}]
    questions = [
        quiz(),
        quiz(options=("a", "b", "c")),
        quiz(correct=4),
        quiz(options=("a", "a", "c", "d")),
        quiz(explanations=("1", "2")),
        quiz(question=" "),
        quiz(timestamp="99:00"),
    ]
    cleaned = engine.clean_quiz(questions, chunks)
    assert len(cleaned) == 2
    assert (
        cleaned[0]["timestamp_seconds"] == 30.0
        and cleaned[1]["timestamp_seconds"] is None
    )


def test_lecture_owner_id(db, lecture):
    assert engine.lecture_owner_id(LECTURE) == "user-9"
    with pytest.raises(ValueError, match="not found"):
        engine.lecture_owner_id("missing")
    db.fail("lectures", RuntimeError("invalid input syntax for type uuid"))
    with pytest.raises(RuntimeError, match="valid uuid"):
        engine.lecture_owner_id("not-a-uuid")


def test_generate_study_set_saves_flashcards_and_quiz(db, lecture, gemini):
    gemini.replies.append(
        gemini_response(
            parsed=StudySet(
                flashcards=[
                    Flashcard(
                        question="What is idea 1?", answer="$x^2$", timestamp="01:10"
                    )
                ],
                quiz=[quiz()],
            )
        )
    )
    result = engine.generate_study_set(LECTURE)
    assert result["status"] == "completed"
    rows = {r["kind"]: r for r in db.tables["study_artifacts"]}
    assert rows["flashcards"]["content"][0]["timestamp_seconds"] == 70.0
    assert rows["quiz"]["status"] == "completed" and rows["quiz"]["user_id"] == "user-9"
    assert "LECTURE CHUNKS" in gemini.calls[0]["contents"]


def test_generate_study_set_failures(db, lecture, gemini, monkeypatch, capsys):
    gemini.replies.append(
        gemini_response(parsed=StudySet(flashcards=[], quiz=[quiz(correct=7)]))
    )
    assert engine.generate_study_set(LECTURE)["status"] == "failed"
    assert {r["status"] for r in db.tables["study_artifacts"]} == {"failed"}

    assert engine.generate_study_set("missing")["error"].startswith(
        "Lecture missing not found"
    )

    def reject(prompt):
        raise GeminiKeyError("bad key")

    monkeypatch.setattr(engine, "call_gemini_study_set", reject)
    db.fail("study_artifacts:upsert", RuntimeError("down"), times=3)
    assert engine.generate_study_set(LECTURE)["status"] == "failed"
    err = capsys.readouterr().err
    assert "Could not record the failure" in err


def test_study_set_needs_indexed_chunks(db, gemini):
    db.seed("lectures", [{"id": "empty", "user_id": "u"}])
    assert "No indexed chunks" in engine.generate_study_set("empty")["error"]


def test_cached_summary(db):
    assert engine.cached_summary(LECTURE) is None
    db.seed(
        "study_artifacts",
        [
            {
                "lecture_id": LECTURE,
                "kind": "summary",
                "status": "processing",
                "content": {},
            }
        ],
    )
    assert engine.cached_summary(LECTURE) is None
    db.tables["study_artifacts"][0].update(
        status="completed", content={"answer": "A", "citations": None}, model="m"
    )
    assert engine.cached_summary(LECTURE) == {
        "answer": "A",
        "citations": [],
        "model": "m",
    }
    db.fail("study_artifacts", RuntimeError("down"))
    assert engine.cached_summary(LECTURE) is None


def test_generate_summary_ignores_cached_answers(db, lecture, gemini):
    stale = cache.lecture_key(
        "answer", LECTURE, "gemini-3.8-flash", cache.text_hash(engine.SUMMARY_QUERY)
    )
    cache.set_json(stale, {"answer": "stale", "grounded": True, "citations": []}, 60)
    gemini.replies.append(gemini_response("Fresh summary [00:00]."))
    result = engine.generate_summary(LECTURE)
    assert result["answer"] == "Fresh summary [00:00]."
    (row,) = db.tables["study_artifacts"]
    assert row["kind"] == "summary" and row["status"] == "completed"
    assert row["model"] == "gemini-3.8-flash"


def test_generate_summary_failures(db, lecture, gemini):
    gemini.replies.append(gemini_response("Not covered in this lecture."))
    assert "could not summarize" in engine.generate_summary(LECTURE)["error"]
    db.fail("study_artifacts:upsert", RuntimeError("kind check"), times=2)
    assert "006_workspace.sql" in engine.generate_summary(LECTURE)["error"]


def test_a_summary_is_never_written_twice_at_once(db, lecture, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow_write(lecture_id):
        started.set()
        release.wait(5)
        return {"status": "completed"}

    monkeypatch.setattr(engine, "_write_summary", slow_write)
    first = threading.Thread(target=engine.generate_summary, args=(LECTURE,))
    first.start()
    started.wait(5)
    assert engine.summary_running(LECTURE) is True
    assert engine.generate_summary(LECTURE) == {"status": "processing"}
    release.set()
    first.join(5)
    assert engine.summary_running(LECTURE) is False
