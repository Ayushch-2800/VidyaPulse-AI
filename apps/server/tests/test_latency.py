"""
Task 19 latency checks. Retrieval latency is set by network round trips, so these tests count
the round trips each path makes and price them at free-tier speeds measured from India, plus
one test that times real (simulated) waits end to end. bench_retrieval.py measures the same
thing against your live Supabase and Gemini.
"""

import time

import pytest

import bench_retrieval
import synthesizer
from fakes import gemini_response
from lecture_factory import seed_four_hour_lecture

LECTURE = "lec-latency"
# Conservative free-tier costs: a Supabase round trip from India to a Singapore/Mumbai project,
# and a Gemini embedding call. Typical numbers are about half of these.
SUPABASE_ROUND_TRIP_SECONDS = 0.35
EMBEDDING_CALL_SECONDS = 0.9
RETRIEVAL_BUDGET_SECONDS = 2.0
CACHED_ANSWER_BUDGET_SECONDS = 1.5


@pytest.fixture
def four_hour_lecture(db):
    seed_four_hour_lecture(db, LECTURE)
    db.reset_log()
    return LECTURE


def round_trips(db, embedder):
    return len(db.queries) + len(db.rpc_calls), len(embedder.calls)


def retrieve(question):
    routed = synthesizer.hybrid_intelligent_router(question, LECTURE)
    return synthesizer.hydrate_timestamps(routed["context_blocks"], LECTURE)


@pytest.mark.parametrize(
    "question, max_supabase, max_embeddings",
    [
        (
            "Explain integration by parts",
            3,
            1,
        ),  # embed, vector search, chunk time map (first use)
        (
            "How many times did he say 'taylor'?",
            1,
            0,
        ),  # one SQL query, times come with it
        ("Give me a summary", 1, 0),  # one query, sampled in Python
    ],
)
def test_cold_retrieval_fits_the_budget(
    four_hour_lecture, db, embedder, question, max_supabase, max_embeddings
):
    blocks = retrieve(question)
    supabase_calls, embedding_calls = round_trips(db, embedder)
    assert blocks and all(b["start_time_seconds"] is not None for b in blocks)
    assert supabase_calls <= max_supabase and embedding_calls == max_embeddings
    worst_case = (
        supabase_calls * SUPABASE_ROUND_TRIP_SECONDS
        + embedding_calls * EMBEDDING_CALL_SECONDS
    )
    assert worst_case < RETRIEVAL_BUDGET_SECONDS


def test_a_new_question_on_an_open_lecture_needs_two_round_trips(
    four_hour_lecture, db, embedder
):
    retrieve("Explain integration by parts")
    db.reset_log()
    embedder.calls.clear()
    retrieve("What is a taylor series expansion")
    assert round_trips(db, embedder) == (
        1,
        1,
    )  # vector search + embedding; chunk times are cached


def test_repeat_questions_make_no_round_trips(four_hour_lecture, db, embedder):
    for question in (
        "Explain integration by parts",
        "How many times did he say 'taylor'?",
        "Give me a summary",
    ):
        retrieve(question)
    db.reset_log()
    embedder.calls.clear()
    started = time.perf_counter()
    for question in (
        "explain integration BY parts",
        "How many times did he say 'taylor'?",
        "give me a summary",
    ):
        retrieve(question)
    assert round_trips(db, embedder) == (0, 0)
    assert time.perf_counter() - started < 0.15


def test_cached_answers_return_well_under_the_budget(
    four_hour_lecture, db, embedder, gemini
):
    gemini.default = lambda call: gemini_response("Integration by parts [180:00].")
    synthesizer.synthesize_answer("Explain integration by parts", LECTURE)
    db.latency_seconds = (
        SUPABASE_ROUND_TRIP_SECONDS  # a cached answer must not touch the network
    )
    started = time.perf_counter()
    answer = synthesizer.synthesize_answer("Explain integration by parts", LECTURE)
    assert answer["cached"] is True
    assert time.perf_counter() - started < CACHED_ANSWER_BUDGET_SECONDS / 10


def test_four_hour_lecture_processing_overhead_is_small(four_hour_lecture, embedder):
    """CPU time spent on our side (sampling, hydration, prompt building), excluding the network."""
    started = time.perf_counter()
    for question in (
        "Explain integration by parts",
        "How many times did he say 'taylor'?",
        "Give me a summary",
    ):
        blocks = retrieve(question)
        synthesizer.build_context_prompt(blocks)
    assert time.perf_counter() - started < 0.5


def test_simulated_network_end_to_end(four_hour_lecture, db, embedder):
    """Real waits: 120 ms per Supabase call and 300 ms per embedding, as on a good connection."""
    db.latency_seconds = 0.12
    embedder.latency_seconds = 0.3
    rows = bench_retrieval.run_benchmark(
        LECTURE, ["Explain integration by parts", "Give me a summary"], runs=2
    )
    semantic, overview = rows
    assert semantic["intent"] == "semantic" and overview["intent"] == "overview"
    # embedding 300 + vector search 120 + chunk times 120 ms
    assert 530 <= semantic["cold_p95"] < RETRIEVAL_BUDGET_SECONDS * 1000
    assert 100 <= overview["cold_p95"] < 500
    assert semantic["warm_p95"] < 50 and overview["warm_p95"] < 50


def test_benchmark_report_and_cli(
    four_hour_lecture, db, embedder, gemini, monkeypatch, tmp_path, capsys
):
    import gemini_utils

    monkeypatch.setattr(gemini_utils, "SERVER_DIR", tmp_path)
    gemini.default = lambda call: gemini_response("Answer [00:00].")
    assert bench_retrieval.main([LECTURE, "--runs", "2", "--with-answer"]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "Cached answer" in out and "semantic" in out

    rows = [
        {
            "question": "q" * 60,
            "intent": "semantic",
            "blocks": 8,
            "cold_p50": 2500,
            "cold_p95": 2600,
            "warm_p50": 1,
            "warm_p95": 1,
            "answer_p95": 1600,
        },
    ]
    assert bench_retrieval.report(rows, 2.0, "memory", 3) is False
    out = capsys.readouterr().out
    assert "FAIL" in out and "cached answer" in out
    with pytest.raises(SystemExit):
        bench_retrieval.main([LECTURE, "--runs", "0"])


def test_percentile_and_ungrounded_answers(db, gemini):
    assert bench_retrieval.percentile([5, 1, 3, 2, 4], 50) == 3
    assert bench_retrieval.percentile([5, 1, 3, 2, 4], 95) == 5
    assert (
        bench_retrieval.measure_cached_answer(
            "how many times did he say quark", LECTURE, 2
        )
        == []
    )


def test_benchmark_shows_logs_when_something_fails(db, embedder, capsys):
    embedder.errors.append(RuntimeError("503 UNAVAILABLE"))
    with pytest.raises(ValueError):
        bench_retrieval.measure_retrieval("Explain limits", LECTURE)
    assert "[ROUTER] Executing Route 2" in capsys.readouterr().out
