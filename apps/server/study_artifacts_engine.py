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

from datetime import datetime, timezone
from typing import List, Dict, Any

from pydantic import BaseModel, Field

from storage_utils import supabase
from gemini_utils import GeminiKeyError, generate_structured, log
from synthesizer import CHAT_MODEL
from cheat_sheet_engine import (
    fetch_lecture_chunks,
    build_batch_prompt,
    resolve_timestamp,
)

TAG = "STUDY SET"
FLASHCARD_COUNT = 10
QUIZ_QUESTION_COUNT = 5
OPTIONS_PER_QUESTION = 4
# Flashcards and quiz come from ONE Gemini call; longer lectures are sampled evenly to fit this budget
MAX_CONTEXT_CHARS = 60000


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
        try:
            lecture = (
                supabase.table("lectures")
                .select("user_id")
                .eq("id", lecture_id)
                .execute()
            )
        except Exception as e:
            raise RuntimeError(
                f"Supabase query on lectures failed ({e}). Check NEXT_PUBLIC_SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY, and that lecture_id is a valid uuid."
            ) from e
        if not lecture.data:
            raise ValueError(f"Lecture {lecture_id} not found in the lectures table.")
        user_id = lecture.data[0]["user_id"]

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


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python study_artifacts_engine.py <lecture_id>")
        sys.exit(1)
    result = generate_study_set(sys.argv[1])
    sys.exit(0 if result["status"] == "completed" else 1)
