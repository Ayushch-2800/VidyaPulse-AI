import pytest

import cache
import synthesizer
from fakes import fake_vector, gemini_response

LECTURE = "lec-synth"


def seed_lecture(db, texts, seconds_per_chunk=60.0, lecture_id=LECTURE):
    return db.seed(
        "multimodal_chunks",
        [
            {
                "lecture_id": lecture_id,
                "chunk_index": i,
                "start_time_seconds": i * seconds_per_chunk,
                "end_time_seconds": (i + 1) * seconds_per_chunk,
                "transcript_text": text,
                "composite_content": text,
                "embedding": fake_vector(text),
            }
            for i, text in enumerate(texts)
        ],
    )


@pytest.mark.parametrize(
    "seconds, label",
    [
        (0, "00:00"),
        (59.9, "00:59"),
        (60, "01:00"),
        (3599, "59:59"),
        (14400, "240:00"),
        (-5, "00:00"),
    ],
)
def test_format_timestamp(seconds, label):
    assert synthesizer.format_timestamp(seconds) == label


def test_hydrate_uses_the_lecture_time_map_for_rpc_blocks(db):
    rows = seed_lecture(db, ["intro", "chain rule", "examples"])
    db.reset_log()
    blocks = [
        {"id": rows[2]["id"], "composite_content": "examples", "similarity": 0.9},
        {"id": rows[1]["id"], "composite_content": "chain rule", "similarity": 0.8},
    ]
    hydrated = synthesizer.hydrate_timestamps(blocks, LECTURE)
    assert [b["start_time_seconds"] for b in hydrated] == [60.0, 120.0]  # chronological
    assert hydrated[0]["chunk_index"] == 1 and hydrated[0]["similarity"] == 0.8
    assert len(db.queries) == 1

    synthesizer.hydrate_timestamps(blocks, LECTURE)
    assert len(db.queries) == 1  # The time map is cached for the lecture


def test_hydrate_skips_the_lookup_when_blocks_carry_times(db):
    blocks = [
        {
            "id": "a",
            "chunk_index": 4,
            "start_time_seconds": 240.0,
            "end_time_seconds": 300.0,
            "composite_content": "x",
        }
    ]
    hydrated = synthesizer.hydrate_timestamps(blocks, LECTURE)
    assert (
        hydrated[0]["start_time_seconds"] == 240.0 and hydrated[0]["chunk_index"] == 4
    )
    assert db.queries == []


def test_hydrate_without_lecture_id_queries_by_ids(db):
    rows = seed_lecture(db, ["intro", "chain rule"])
    db.reset_log()
    hydrated = synthesizer.hydrate_timestamps(
        [{"id": rows[1]["id"], "composite_content": "chain rule"}]
    )
    assert hydrated[0]["start_time_seconds"] == 60.0
    (query,) = db.queries
    assert query.filters == [("in", "id", [rows[1]["id"]])]


def test_hydrate_falls_back_to_the_composite_header(db):
    db.fail("multimodal_chunks", RuntimeError("PostgREST down"))
    blocks = [
        {
            "id": "x",
            "composite_content": "### Spoken Transcript (12.5s - 45.0s):\nhello",
        },
        {"id": "y", "composite_content": "no header at all"},
    ]
    hydrated = synthesizer.hydrate_timestamps(blocks, LECTURE)
    assert (hydrated[0]["start_time_seconds"], hydrated[0]["end_time_seconds"]) == (
        12.5,
        45.0,
    )
    assert hydrated[1]["start_time_seconds"] is None  # Untimed blocks go last


def test_remember_chunk_times_ignores_rows_without_ids(db):
    synthesizer.remember_chunk_times(LECTURE, [{"chunk_index": 0}])
    assert cache.get_json(cache.lecture_key("chunk-times", LECTURE)) is None
    synthesizer.remember_chunk_times(
        LECTURE,
        [
            {
                "id": 7,
                "chunk_index": 0,
                "start_time_seconds": 1.0,
                "end_time_seconds": 2.0,
            }
        ],
    )
    assert synthesizer.lecture_chunk_times(LECTURE) == {
        "7": {"chunk_index": 0, "start_time_seconds": 1.0, "end_time_seconds": 2.0}
    }
    assert db.queries == []


def test_shorten_and_trim_block():
    assert synthesizer.shorten("short", 10) == "short"
    assert synthesizer.shorten("one two three four", 9) == "one two …"
    body = "spoken " * 200 + synthesizer.VISUAL_HEADING + "\n" + "slide " * 200
    trimmed = synthesizer.trim_block(body, 300)
    transcript, _, visual = trimmed.partition(synthesizer.VISUAL_HEADING)
    assert len(transcript) <= 210 and len(visual) <= 110
    assert synthesizer.trim_block("tiny", 300) == "tiny"
    assert synthesizer.trim_block("word " * 100, 50).endswith("…")


def test_build_context_prompt_labels_and_budget():
    blocks = [
        {
            "start_time_seconds": 125.0,
            "end_time_seconds": 190.0,
            "composite_content": "a" * 50,
        },
        {"start_time_seconds": None, "composite_content": "b" * 50},
        {
            "start_time_seconds": 300.0,
            "end_time_seconds": None,
            "composite_content": "c" * 500,
        },
    ]
    prompt = synthesizer.build_context_prompt(blocks, max_chars=250)
    assert "cite as [02:05] | covers 02:05 to 03:10" in prompt
    assert "Context Block 2 | no timestamp available" in prompt
    assert "c" * 10 not in prompt  # Over budget, left out


def test_validate_citations_drops_invented_timestamps():
    blocks = [
        {"id": "a", "start_time_seconds": 60.0, "end_time_seconds": 120.0},
        {"id": "b", "start_time_seconds": 7500.0, "end_time_seconds": 7560.0},
        {"id": "c", "start_time_seconds": None, "end_time_seconds": None},
    ]
    answer = (
        "Limits come first [01:30]. Again [01:30]. Edge [00:56]. "
        "Late in a long lecture [125:30]. Made up [45:00] ."
    )
    cleaned, citations = synthesizer.validate_citations(answer, blocks)
    assert "[45:00]" not in cleaned and cleaned.endswith("Made up.")
    assert [c["label"] for c in citations] == ["01:30", "00:56", "125:30"]
    assert citations[2] == {"label": "125:30", "seconds": 7530, "chunk_id": "b"}


def test_no_context_answers_not_covered_without_gemini(db, gemini):
    result = synthesizer.synthesize_answer(
        "how many times did he say quaternion", LECTURE
    )
    assert result["answer"] == synthesizer.NOT_COVERED
    assert result["grounded"] is False and gemini.calls == []


def test_grounded_answer_is_cited_and_cached(db, embedder, gemini):
    seed_lecture(
        db,
        ["intro to calculus", "the chain rule says differentiate outside then inside"],
    )
    gemini.replies.append(
        gemini_response("Differentiate outside, then inside [01:00]. Wrong [30:00].")
    )

    first = synthesizer.synthesize_answer("Explain the chain rule", LECTURE)
    assert first["grounded"] is True and first["cached"] is False
    assert first["answer"] == "Differentiate outside, then inside [01:00]. Wrong."
    assert first["citations"][0]["seconds"] == 60
    assert first["model"] == "gemini-3.8-flash"
    assert {"retrieval_ms", "timestamps_ms", "generation_ms", "total_ms"} <= set(
        first["timings_ms"]
    )
    prompt = gemini.calls[0]["contents"]
    assert (
        "STUDENT QUESTION:\nExplain the chain rule" in prompt
        and "cite as [01:00]" in prompt
    )

    db.reset_log()
    again = synthesizer.synthesize_answer("explain the  CHAIN rule", LECTURE)
    assert again["cached"] is True and again["answer"] == first["answer"]
    assert len(gemini.calls) == 1 and db.queries == [] and db.rpc_calls == []


def test_not_covered_answers_are_not_cached(db, embedder, gemini):
    seed_lecture(db, ["kinematics of a particle"])
    gemini.replies.extend(
        [
            gemini_response("Not covered in this lecture."),
            gemini_response("Velocity [00:00]."),
        ]
    )
    first = synthesizer.synthesize_answer("What is velocity in kinematics", LECTURE)
    second = synthesizer.synthesize_answer("What is velocity in kinematics", LECTURE)
    assert first["grounded"] is False and first["answer"] == synthesizer.NOT_COVERED
    assert second["grounded"] is True and len(gemini.calls) == 2


def test_use_cache_false_always_asks_gemini(db, embedder, gemini):
    seed_lecture(db, ["the chain rule"])
    gemini.replies.extend(
        [gemini_response("One [00:10]."), gemini_response("Two [00:20].")]
    )
    synthesizer.synthesize_answer("Explain the chain rule", LECTURE)
    fresh = synthesizer.synthesize_answer(
        "Explain the chain rule", LECTURE, use_cache=False
    )
    assert fresh["answer"] == "Two [00:20]." and fresh["cached"] is False


def test_overview_prompt_samples_and_trims(db, gemini):
    seed_lecture(db, [f"topic {i} " + "detail " * 400 for i in range(25)])
    gemini.replies.append(gemini_response("It covers topics [00:00] to [24:00]."))
    result = synthesizer.synthesize_answer("Give me a quick summary", LECTURE)
    prompt = gemini.calls[0]["contents"]
    assert result["intent"] == "overview" and result["grounded"] is True
    assert "The student wants an overview" in prompt
    assert len(prompt) < synthesizer.OVERVIEW_CONTEXT_CHARS + 2000
    assert gemini.calls[0]["config"].max_output_tokens == synthesizer.MAX_ANSWER_TOKENS
