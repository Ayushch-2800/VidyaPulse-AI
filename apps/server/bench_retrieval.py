"""
Task 19: Measures retrieval latency (everything /chat/ask does before Gemini writes the answer)
against your real Supabase and Gemini, cold and cached, and checks it against a budget.

Run from apps/server with the venv active:

    python bench_retrieval.py <lecture_id>
    python bench_retrieval.py <lecture_id> --runs 5 --budget 2.0 --question "Explain the chain rule"
    python bench_retrieval.py <lecture_id> --with-answer   # also times a cached full answer

A cold semantic run costs one Gemini embedding call; nothing else uses Gemini unless you pass
--with-answer, which writes one answer per question. Exits 1 if any cold p95 is over budget.
"""

import argparse
import contextlib
import io
import math
import sys
import time
from typing import Any, Dict, List, Sequence

DEFAULT_QUESTIONS = (
    "Explain the most important concept taught in this lecture",  # semantic: embedding + vector search
    "How many times is the word 'example' said?",  # literal: SQL text match
    "Give me a quick summary of the lecture",  # overview: sampled chunks
)
# The Task 19 targets: retrieval under 2s, and a repeat question answered under 1.5s
DEFAULT_BUDGET_SECONDS = 2.0
CACHED_ANSWER_BUDGET_SECONDS = 1.5


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile; p95 of 5 runs is the slowest one."""
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


@contextlib.contextmanager
def quiet():
    """Hides the pipeline's log lines while timing; shows them if something fails."""
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            yield
    except Exception:
        sys.stdout.write(buffer.getvalue())
        raise


def measure_retrieval(question: str, lecture_id: str) -> Dict[str, Any]:
    """Routes and hydrates exactly as /chat/ask does, without the Gemini answer."""
    from query_router import hybrid_intelligent_router
    from synthesizer import hydrate_timestamps

    started = time.perf_counter()
    with quiet():
        routed = hybrid_intelligent_router(question, lecture_id)
        blocks = hydrate_timestamps(routed["context_blocks"], lecture_id)
    return {
        "intent": routed["intent"],
        "blocks": len(blocks),
        "ms": (time.perf_counter() - started) * 1000,
    }


def measure_cached_answer(question: str, lecture_id: str, runs: int) -> List[float]:
    """Writes one answer with Gemini, then times the repeats, which the cache serves."""
    from synthesizer import synthesize_answer

    with quiet():
        first = synthesize_answer(question, lecture_id)
    if not first["grounded"]:
        return []  # "Not covered" answers are never cached
    times = []
    for _ in range(runs):
        started = time.perf_counter()
        with quiet():
            synthesize_answer(question, lecture_id)
        times.append((time.perf_counter() - started) * 1000)
    return times


def run_benchmark(
    lecture_id: str,
    questions: Sequence[str],
    runs: int,
    with_answer: bool = False,
) -> List[Dict[str, Any]]:
    import cache

    rows = []
    for question in questions:
        cold = []
        for _ in range(runs):
            with cache.disabled():
                sample = measure_retrieval(question, lecture_id)
            cold.append(sample["ms"])
        measure_retrieval(question, lecture_id)  # fills the cache
        warm = [measure_retrieval(question, lecture_id)["ms"] for _ in range(runs)]
        row = {
            "question": question,
            "intent": sample["intent"],
            "blocks": sample["blocks"],
            "cold_p50": percentile(cold, 50),
            "cold_p95": percentile(cold, 95),
            "warm_p50": percentile(warm, 50),
            "warm_p95": percentile(warm, 95),
            "answer_p95": None,
        }
        if with_answer:
            answers = measure_cached_answer(question, lecture_id, runs)
            row["answer_p95"] = percentile(answers, 95) if answers else None
        rows.append(row)
    return rows


def report(
    rows: List[Dict[str, Any]], budget_seconds: float, backend: str, runs: int
) -> bool:
    budget_ms = budget_seconds * 1000
    print(
        f"\nRetrieval latency ({runs} runs per question, cache: {backend}, budget {budget_seconds:.1f}s)\n"
    )
    header = f"{'Question':<46} {'Route':<9} {'Blocks':>6} {'Cold p50':>9} {'Cold p95':>9} {'Cached p95':>11}"
    with_answers = any(r["answer_p95"] is not None for r in rows)
    if with_answers:
        header += f" {'Cached answer':>14}"
    print(header)
    print("-" * len(header))
    for r in rows:
        question = (
            r["question"] if len(r["question"]) <= 45 else r["question"][:44] + "…"
        )
        line = (
            f"{question:<46} {r['intent']:<9} {r['blocks']:>6} {r['cold_p50']:>6.0f} ms"
            f" {r['cold_p95']:>6.0f} ms {r['warm_p95']:>8.1f} ms"
        )
        if with_answers:
            answer = "n/a" if r["answer_p95"] is None else f"{r['answer_p95']:.1f} ms"
            line += f" {answer:>14}"
        print(line)

    slow = [r for r in rows if r["cold_p95"] > budget_ms]
    slow_answers = [
        r
        for r in rows
        if r["answer_p95"] is not None
        and r["answer_p95"] > CACHED_ANSWER_BUDGET_SECONDS * 1000
    ]
    print()
    if slow or slow_answers:
        for r in slow:
            print(
                f"FAIL: '{r['question']}' took {r['cold_p95']:.0f} ms at p95 (budget {budget_ms:.0f} ms)."
            )
        for r in slow_answers:
            print(
                f"FAIL: the cached answer to '{r['question']}' took {r['answer_p95']:.0f} ms."
            )
        return False
    print(
        f"PASS: every cold retrieval p95 is under {budget_seconds:.1f}s, and repeats come from the cache."
    )
    return True


def main(argv: Sequence[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("lecture_id", help="A lecture that has finished ingesting")
    parser.add_argument(
        "--runs", type=int, default=5, help="Timed runs per question (default 5)"
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=DEFAULT_BUDGET_SECONDS,
        help="Seconds allowed at p95 (default 2.0)",
    )
    parser.add_argument(
        "--question",
        action="append",
        help="Ask this instead of the 3 defaults (repeatable)",
    )
    parser.add_argument(
        "--with-answer",
        action="store_true",
        help="Also time a cached full answer (1 Gemini call per question)",
    )
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    from gemini_utils import check_environment

    check_environment("BENCH")
    import cache

    rows = run_benchmark(
        args.lecture_id, args.question or DEFAULT_QUESTIONS, args.runs, args.with_answer
    )
    return 0 if report(rows, args.budget, cache.stats()["backend"], args.runs) else 1


if __name__ == "__main__":
    sys.exit(main())
