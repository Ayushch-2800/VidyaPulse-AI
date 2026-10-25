import pytest

import cache
import query_router
from fakes import fake_vector

LECTURE = "lec-router"


def seed_chunks(db, texts, lecture_id=LECTURE, seconds_per_chunk=60.0):
    rows = []
    for index, text in enumerate(texts):
        rows.append(
            {
                "lecture_id": lecture_id,
                "chunk_index": index,
                "start_time_seconds": index * seconds_per_chunk,
                "end_time_seconds": (index + 1) * seconds_per_chunk,
                "transcript_text": text,
                "composite_content": text,
                "embedding": fake_vector(text),
            }
        )
    return db.seed("multimodal_chunks", rows)


@pytest.mark.parametrize(
    "question, intent",
    [
        ("Give me a quick summary", "overview"),
        ("Summarise the lecture", "overview"),
        ("What are the key concepts?", "overview"),
        ("what is this lecture about", "overview"),
        ("TL;DR please", "overview"),
        ("How many times did he say integration?", "literal"),
        ("What exactly is written on the slide?", "literal"),
        ("Sir ne derivative kitni baar bola?", "literal"),
        ("Explain the chain rule", "semantic"),
        ("Write an essay on vectors", "semantic"),  # "essay" contains "say"
        (
            "How does the account balance change?",
            "semantic",
        ),  # "account" contains "count"
        ("chain rule kya hai?", "semantic"),
    ],
)
def test_classify_intent(question, intent):
    assert query_router.classify_intent(question) == intent


@pytest.mark.parametrize(
    "question, keyword",
    [
        ("How many times did he say integration?", "integration"),
        ("How many times is the word derivative mentioned?", "derivative"),
        ("Count the times he says 'chain rule'.", "chain rule"),
        ('Did the teacher say "eigen-value" exactly?', "eigen-value"),
        ("What's the teacher's exact words on vectors?", "vectors"),
        ("Sir ne derivative kitni baar bola?", "derivative"),
        ("कितनी बार अवकलज कहा गया", "गया"),
        ('Sir ne "अवकलज" kitni baar bola?', "अवकलज"),
        ("How many times did he say 'தொகையீடு'?", "தொகையீடு"),
        ("How many times did he say 50%_off?", "off"),
        ("say", "say"),
        ("???", ""),
    ],
)
def test_literal_keyword(question, keyword):
    assert query_router.literal_keyword(question) == keyword


def test_literal_search_builds_a_bounded_ordered_ilike_query(db):
    seed_chunks(
        db, ["we integrate x", "no match here", "integration by parts", "Integral"]
    )
    blocks = query_router.route_1_literal_search(
        "How many times did he say integration?", LECTURE
    )

    assert [b["composite_content"] for b in blocks] == ["integration by parts"]
    (query,) = db.queries_on("multimodal_chunks")
    assert query.columns == query_router.CHUNK_COLUMNS
    assert query.filters == [
        ("eq", "lecture_id", LECTURE),
        ("ilike", "transcript_text", "%integration%"),
    ]
    assert query.orders == [("chunk_index", False)]
    assert query.limit_ == query_router.LITERAL_MATCH_LIMIT
    assert set(blocks[0]) >= {
        "id",
        "chunk_index",
        "start_time_seconds",
        "end_time_seconds",
    }


def test_literal_search_with_no_term_skips_the_database(db):
    assert query_router.route_1_literal_search("???", LECTURE) == []
    assert db.queries == []


def test_literal_search_caps_matches_for_long_lectures(db):
    seed_chunks(db, [f"the word vector appears in part {i}" for i in range(60)])
    blocks = query_router.route_1_literal_search(
        "how many times is vector said", LECTURE
    )
    assert len(blocks) == query_router.LITERAL_MATCH_LIMIT
    assert [b["chunk_index"] for b in blocks] == list(
        range(query_router.LITERAL_MATCH_LIMIT)
    )


def test_semantic_search_calls_the_rpc_with_the_query_vector(db, embedder):
    seed_chunks(db, ["the chain rule of differentiation", "kinematics and velocity"])
    timings = {}
    blocks = query_router.route_2_semantic_search(
        "Explain the chain rule", LECTURE, timings
    )

    name, params = db.rpc_calls[0]
    assert name == "match_multimodal_chunks"
    assert params["match_threshold"] == query_router.SEMANTIC_MATCH_THRESHOLD
    assert params["match_count"] == query_router.SEMANTIC_MATCH_COUNT
    assert params["p_lecture_id"] == LECTURE
    assert len(params["query_embedding"]) == 1536
    assert blocks[0]["composite_content"] == "the chain rule of differentiation"
    assert set(blocks[0]) == {"id", "composite_content", "similarity"}
    assert {"embedding_ms", "vector_search_ms"} <= set(timings)


def test_semantic_search_falls_back_to_nearest_chunks(db, embedder):
    seed_chunks(db, ["kinematics and velocity"])
    blocks = query_router.route_2_semantic_search("photosynthesis in plants", LECTURE)
    assert [p["match_threshold"] for _, p in db.rpc_calls] == [0.3, 0.0]
    assert (
        blocks == []
    )  # cosine 0 is not above 0.0 either: nothing at all shares a word


def test_semantic_search_raises_when_embedding_fails(db, embedder):
    embedder.errors.append(RuntimeError("503 UNAVAILABLE"))
    with pytest.raises(ValueError, match="Failed to generate embedding"):
        query_router.route_2_semantic_search("Explain the chain rule", LECTURE)
    assert db.rpc_calls == []


def test_overview_samples_first_last_and_evenly_between(db):
    seed_chunks(db, [f"part {i}" for i in range(31)])
    blocks = query_router.route_3_overview(LECTURE)
    indexes = [b["chunk_index"] for b in blocks]
    assert len(indexes) == query_router.OVERVIEW_CHUNK_COUNT
    assert indexes[0] == 0 and indexes[-1] == 30
    assert indexes == sorted(indexes) and len(set(indexes)) == len(indexes)


def test_overview_of_a_short_lecture_returns_every_chunk(db):
    seed_chunks(db, ["intro", "body", "outro"])
    assert [b["chunk_index"] for b in query_router.route_3_overview(LECTURE)] == [
        0,
        1,
        2,
    ]


def test_sample_evenly_edge_cases():
    assert query_router.sample_evenly([], 10) == []
    assert query_router.sample_evenly([1, 2], 10) == [1, 2]
    assert query_router.sample_evenly(list(range(100)), 2) == [0, 99]


def test_router_caches_semantic_results_per_lecture(db, embedder):
    seed_chunks(db, ["the chain rule of differentiation", "kinematics and velocity"])
    first = query_router.hybrid_intelligent_router("Explain the chain rule", LECTURE)
    queries, rpcs, embeds = len(db.queries), len(db.rpc_calls), len(embedder.calls)

    again = query_router.hybrid_intelligent_router("  explain THE chain rule ", LECTURE)
    assert again["cached"] is True and first["cached"] is False
    assert again["context_blocks"] == first["context_blocks"]
    assert (len(db.queries), len(db.rpc_calls), len(embedder.calls)) == (
        queries,
        rpcs,
        embeds,
    )
    assert "retrieval_ms" in again["timings_ms"]


def test_new_question_reuses_the_cached_query_embedding(db, embedder):
    seed_chunks(db, ["the chain rule of differentiation"])
    query_router.hybrid_intelligent_router("Explain the chain rule", LECTURE)
    query_router.hybrid_intelligent_router("Explain the chain rule", "another-lecture")
    assert (
        len(embedder.calls) == 1
    )  # Same question, other lecture: no second Gemini call
    assert {p["p_lecture_id"] for _, p in db.rpc_calls} == {LECTURE, "another-lecture"}


def test_overview_cache_ignores_wording(db):
    seed_chunks(db, [f"part {i}" for i in range(12)])
    query_router.hybrid_intelligent_router("Give me a summary", LECTURE)
    result = query_router.hybrid_intelligent_router(
        "Summarize the main points", LECTURE
    )
    assert result["cached"] is True
    assert len(db.queries_on("multimodal_chunks")) == 1


def test_reindexing_a_lecture_retires_cached_searches(db):
    seed_chunks(db, ["integration by parts"])
    query_router.hybrid_intelligent_router(
        "how many times did he say integration", LECTURE
    )
    cache.invalidate_lecture(LECTURE)
    result = query_router.hybrid_intelligent_router(
        "how many times did he say integration", LECTURE
    )
    assert result["cached"] is False
    assert len(db.queries_on("multimodal_chunks")) == 2
