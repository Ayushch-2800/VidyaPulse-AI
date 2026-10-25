import sys

if __name__ == "__main__":
    # Check keys before the imports below open Supabase and Gemini connections
    from gemini_utils import check_environment, preload

    print("[STUDY SET] Starting...", flush=True)
    try:
        check_environment("STUDY SET")
    except EnvironmentError as e:
        print(f"\n[STUDY SET ERROR] {e}", file=sys.stderr, flush=True)
        sys.exit(1)
    # Imports Supabase and Gemini step by step, so a stall names the exact step
    preload("STUDY SET")

import threading
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, Field

from storage_utils import supabase
from gemini_utils import GeminiKeyError, generate_structured, log
from synthesizer import CHAT_MODEL, synthesize_answer
from cheat_sheet_engine import (
    fetch_lecture_chunks,
    build_batch_prompt,
    resolve_timestamp,
)

TAG = "STUDY SET"
SUMMARY_TAG = "SUMMARY"
FLASHCARD_COUNT = 10
QUIZ_QUESTION_COUNT = 5
OPTIONS_PER_QUESTION = 4
# Flashcards and quiz come from ONE Gemini call; longer lectures are sampled evenly to fit this budget
MAX_CONTEXT_CHARS = 60000
# Phrased so the query router takes its overview route, which samples the whole lecture in order
SUMMARY_QUERY = "Give me a summary of this lecture, covering its main topics in the order they are taught."

# Lectures whose summary is being written right now, so a second click (or the post-ingestion
# job) waits for that run instead of spending another Gemini call on the same summary
_summaries_running: set = set()
_summaries_lock = threading.Lock()


class Flashcard(BaseModel):
    question: str = Field(
        description="A recall question a student should be able to answer"
    )
    answer: str = Field(
        description="Concise answer, with math in LaTeX using $...$ delimiters"
    )
    timestamp: str = Field(
        description="MM:SS label of the chunk that proves the answer, copied from its header"
    )


class QuizQuestion(BaseModel):
    question: str
    options: List[str] = Field(description="Exactly 4 answer choices")
    correct_index: int = Field(description="0-based index of the correct option")
    option_explanations: List[str] = Field(
        description="One explanation per option, in the same order: why it is correct, or why it is wrong"
    )
    timestamp: str = Field(
        description="MM:SS label of the chunk the question is based on, copied from its header"
    )


class StudySet(BaseModel):
    flashcards: List[Flashcard]
    quiz: List[QuizQuestion]


STUDY_SET_PROMPT = f"""
You are creating active-recall study material from ONE lecture's transcript and slide OCR.

Produce:
- Exactly {FLASHCARD_COUNT} high-yield flashcards covering the most important ideas, spread across the whole lecture.
- Exactly {QUIZ_QUESTION_COUNT} multiple-choice questions, each with exactly {OPTIONS_PER_QUESTION} options and one correct answer.

Strictly follow these rules:
1. Use ONLY the lecture chunks provided. Never test facts the lecture does not state.
2. Every flashcard and question must set "timestamp" to the MM:SS label of the chunk that proves it. Never invent one.
3. Wrong options must be plausible misconceptions a student might hold, not obviously silly.
4. "option_explanations" must explain, for every option, why it is right or why it is wrong.
5. Write all math in LaTeX with $...$ delimiters, copying formulas from the slide context exactly.
6. The transcript may be code-mixed (Hinglish, Tamil-English, etc.). Write the study material in English.
""".strip()


def sample_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keeps every chunk if they fit MAX_CONTEXT_CHARS, otherwise an evenly spaced subset in lecture order."""
    total = sum(len(c.get("composite_content") or "") for c in chunks)
    if total <= MAX_CONTEXT_CHARS:
        return chunks
    keep = max(1, int(len(chunks) * MAX_CONTEXT_CHARS / total))
    step = len(chunks) / keep
    return [chunks[int(i * step)] for i in range(keep)]


def call_gemini_study_set(prompt: str) -> StudySet:
    """Calls Gemini Flash in JSON mode with the StudySet schema (timeout, pacing, logged retries)."""
    return generate_structured(
        prompt, STUDY_SET_PROMPT, StudySet, temperature=0.4, tag=TAG
    )


def clean_flashcards(
    cards: List[Flashcard], chunks: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    cleaned = []
    for card in cards:
        if not card.question.strip() or not card.answer.strip():
            continue
        cleaned.append(
            {
                "question": card.question.strip(),
                "answer": card.answer.strip(),
                "timestamp_seconds": resolve_timestamp(card.timestamp, chunks),
            }
        )
    return cleaned[:FLASHCARD_COUNT]


def clean_quiz(
    questions: List[QuizQuestion], chunks: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Drops any question whose options, answer index or explanations don't line up."""
    cleaned = []
    for q in questions:
        options = [o.strip() for o in q.options]
        explanations = [e.strip() for e in q.option_explanations]
        if (
            not q.question.strip()
            or len(options) != OPTIONS_PER_QUESTION
            or len(explanations) != OPTIONS_PER_QUESTION
            or not 0 <= q.correct_index < OPTIONS_PER_QUESTION
            or len(set(options)) != OPTIONS_PER_QUESTION
        ):
            log(TAG, f"Dropping malformed quiz question: {q.question[:60]}")
            continue
        cleaned.append(
            {
                "question": q.question.strip(),
                "options": options,
                "correct_index": q.correct_index,
                "option_explanations": explanations,
                "timestamp_seconds": resolve_timestamp(q.timestamp, chunks),
            }
        )
    return cleaned[:QUIZ_QUESTION_COUNT]


def lecture_owner_id(lecture_id: str) -> str:
    """The lecture's user_id. Raises ValueError if there is no such lecture."""
    try:
        lecture = (
            supabase.table("lectures").select("user_id").eq("id", lecture_id).execute()
        )
    except Exception as e:
        raise RuntimeError(
            f"Supabase query on lectures failed ({e}). Check NEXT_PUBLIC_SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY, and that lecture_id is a valid uuid."
        ) from e
    if not lecture.data:
        raise ValueError(f"Lecture {lecture_id} not found in the lectures table.")
    return lecture.data[0]["user_id"]


def save_study_artifact(
    lecture_id: str, user_id: str, kind: str, **fields: Any
) -> None:
    supabase.table("study_artifacts").upsert(
        {
            "lecture_id": lecture_id,
            "user_id": user_id,
            "kind": kind,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        },
        on_conflict="lecture_id,kind",
    ).execute()


def generate_study_set(lecture_id: str) -> Dict[str, Any]:
    """
    Task 16 background worker: generates 10 flashcards and a 5-question quiz for one lecture
    in a single Gemini call and saves them to study_artifacts.
    """
    log(TAG, f"--- GENERATING STUDY SET FOR LECTURE {lecture_id} ---")
    user_id = None

    try:
        log(TAG, "Looking up the lecture in Supabase...")
        user_id = lecture_owner_id(lecture_id)

        for kind in ("flashcards", "quiz"):
            save_study_artifact(
                lecture_id,
                user_id,
                kind,
                status="processing",
                error=None,
                model=CHAT_MODEL,
            )

        log(TAG, "Fetching lecture chunks from Supabase...")
        chunks = fetch_lecture_chunks(lecture_id)
        if not chunks:
            raise ValueError(
                "No indexed chunks found for this lecture. Check that ingestion completed."
            )

        sampled = sample_chunks(chunks)
        log(
            TAG,
            f"Found {len(chunks)} chunks; sending {len(sampled)} to Gemini in 1 call.",
        )
        study_set = call_gemini_study_set(build_batch_prompt(sampled))
        log(
            TAG,
            f"Gemini returned {len(study_set.flashcards)} flashcards and {len(study_set.quiz)} quiz questions.",
        )

        flashcards = clean_flashcards(study_set.flashcards, chunks)
        quiz = clean_quiz(study_set.quiz, chunks)
        if not flashcards and not quiz:
            raise ValueError("Gemini returned no usable flashcards or quiz questions.")

        log(TAG, "Saving flashcards and quiz to Supabase...")
        save_study_artifact(
            lecture_id, user_id, "flashcards", status="completed", content=flashcards
        )
        save_study_artifact(
            lecture_id, user_id, "quiz", status="completed", content=quiz
        )
        log(
            TAG,
            f"--- STUDY SET COMPLETE: {len(flashcards)} flashcards, {len(quiz)} quiz questions ---",
        )
        return {"status": "completed", "flashcards": flashcards, "quiz": quiz}

    except Exception as e:
        kind_label = "INVALID GEMINI KEY" if isinstance(e, GeminiKeyError) else "ERROR"
        print(f"\n[STUDY SET {kind_label}] {e}", file=sys.stderr, flush=True)
        if user_id:
            try:
                for kind in ("flashcards", "quiz"):
                    save_study_artifact(
                        lecture_id, user_id, kind, status="failed", error=str(e)
                    )
            except Exception as save_error:
                print(
                    f"[STUDY SET ERROR] Could not record the failure in Supabase: {save_error}",
                    file=sys.stderr,
                    flush=True,
                )
        return {"status": "failed", "error": str(e)}


def summary_running(lecture_id: str) -> bool:
    with _summaries_lock:
        return lecture_id in _summaries_running


def cached_summary(lecture_id: str) -> Optional[Dict[str, Any]]:
    """The stored summary as a /chat/ask answer, or None if there is no finished one."""
    try:
        res = (
            supabase.table("study_artifacts")
            .select("status, content, model")
            .eq("lecture_id", lecture_id)
            .eq("kind", "summary")
            .execute()
        )
    except Exception as e:
        log(
            SUMMARY_TAG,
            f"Could not read the stored summary ({e}); asking Gemini instead.",
        )
        return None
    row = (res.data or [None])[0]
    content = (row or {}).get("content") or {}
    if not row or row.get("status") != "completed" or not content.get("answer"):
        return None
    return {
        "answer": content["answer"],
        "citations": content.get("citations") or [],
        "model": row.get("model"),
    }


def generate_summary(lecture_id: str) -> Dict[str, Any]:
    """
    Task 18: Writes the lecture summary with the same grounded, [MM:SS]-cited synthesizer as
    /chat/ask and saves it to study_artifacts, so the workspace, the PDF export and summary
    questions in /chat/ask show it without another Gemini call. If this lecture's summary is
    already being written, returns right away instead of starting a second run.
    """
    with _summaries_lock:
        if lecture_id in _summaries_running:
            log(
                SUMMARY_TAG,
                f"Summary for {lecture_id} is already being written; not starting another.",
            )
            return {"status": "processing"}
        _summaries_running.add(lecture_id)
    try:
        return _write_summary(lecture_id)
    finally:
        with _summaries_lock:
            _summaries_running.discard(lecture_id)


def _write_summary(lecture_id: str) -> Dict[str, Any]:
    log(SUMMARY_TAG, f"--- GENERATING SUMMARY FOR LECTURE {lecture_id} ---")
    user_id = None

    try:
        log(SUMMARY_TAG, "Looking up the lecture in Supabase...")
        user_id = lecture_owner_id(lecture_id)
        try:
            save_study_artifact(
                lecture_id,
                user_id,
                "summary",
                status="processing",
                error=None,
                model=CHAT_MODEL,
            )
        except Exception as e:
            raise RuntimeError(
                f"Supabase write to study_artifacts failed ({e}). Run "
                "migrations/006_workspace.sql, which allows the 'summary' kind."
            ) from e

        # Regenerate must write a new summary, never return a cached answer
        result = synthesize_answer(SUMMARY_QUERY, lecture_id, use_cache=False)
        if not result["grounded"]:
            raise ValueError(
                "Gemini could not summarize this lecture. Check that ingestion completed "
                "and the lecture's chunks are indexed."
            )

        content = {"answer": result["answer"], "citations": result["citations"]}
        log(SUMMARY_TAG, "Saving the summary to Supabase...")
        # model records which one wrote it, which is the fallback if the main model timed out
        save_study_artifact(
            lecture_id,
            user_id,
            "summary",
            status="completed",
            content=content,
            model=result["model"],
        )
        log(
            SUMMARY_TAG,
            f"--- SUMMARY COMPLETE with {result['model']}: {len(content['answer']):,} chars, "
            f"{len(content['citations'])} timestamp citations ---",
        )
        return {"status": "completed", **content}

    except Exception as e:
        kind_label = "INVALID GEMINI KEY" if isinstance(e, GeminiKeyError) else "ERROR"
        print(f"\n[SUMMARY {kind_label}] {e}", file=sys.stderr, flush=True)
        if user_id:
            try:
                save_study_artifact(
                    lecture_id, user_id, "summary", status="failed", error=str(e)
                )
            except Exception as save_error:
                print(
                    f"[SUMMARY ERROR] Could not record the failure in Supabase: {save_error}",
                    file=sys.stderr,
                    flush=True,
                )
        return {"status": "failed", "error": str(e)}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python study_artifacts_engine.py <lecture_id>")
        sys.exit(1)
    result = generate_study_set(sys.argv[1])
    sys.exit(0 if result["status"] == "completed" else 1)
