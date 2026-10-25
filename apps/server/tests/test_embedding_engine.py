import sys
import types

import cache
import embedding_engine


def make_chunks(count, lecture_id="lec-emb"):
    return [
        {
            "chunk_index": i,
            "lecture_id": lecture_id,
            "start_time_seconds": i * 60.0,
            "end_time_seconds": (i + 1) * 60.0,
            "duration_seconds": 60.0,
            "transcript_text": f"part {i}",
            "visual_context_count": 0,
            "composite_content": f"part {i} of the lecture",
            "language": "hi",
        }
        for i in range(count)
    ]


def test_generate_embeddings_asks_for_1536_dimensions(embedder):
    vectors = embedding_engine.generate_embeddings(["chain rule", "limits"])
    assert len(vectors) == 2 and all(len(v) == 1536 for v in vectors)
    call = embedder.calls[0]
    assert call["model"] == "models/gemini-embedding-001"
    assert call["output_dimensionality"] == 1536
    assert call["task_type"] == "semantic_similarity"
    assert call["request_options"]["timeout"] == embedding_engine.EMBED_TIMEOUT_SECONDS


def test_generate_embeddings_handles_empty_input_and_errors(embedder):
    assert embedding_engine.generate_embeddings([]) == []
    assert embedder.calls == []
    embedder.errors.append(RuntimeError("429 RESOURCE_EXHAUSTED"))
    assert embedding_engine.generate_embeddings(["x"]) == []


def test_embed_query_is_cached_across_case_and_spacing(embedder):
    first = embedding_engine.embed_query("What is the Chain Rule?")
    second = embedding_engine.embed_query("  what is the chain   rule? ")
    assert first == second and len(first) == 1536
    assert len(embedder.calls) == 1


def test_embed_query_never_caches_failures(embedder):
    embedder.errors.append(RuntimeError("503 UNAVAILABLE"))
    assert embedding_engine.embed_query("limits") is None
    assert embedding_engine.embed_query("limits") is not None
    assert len(embedder.calls) == 2


def test_embed_query_rejects_wrong_dimensions(embedder):
    embedder.dimensions = 768  # e.g. GEMINI_EMBEDDING_MODEL pointed at a 768-d model
    assert embedding_engine.embed_query("limits") is None
    assert cache.stats()["hits"] == 0


def test_index_inserts_in_batches_and_invalidates_the_lecture(db, embedder):
    version = cache.lecture_version("lec-emb")
    chunks = make_chunks(120)
    assert embedding_engine.index_multimodal_chunks(chunks, "lec-emb") is True

    inserts = db.queries_on("multimodal_chunks", "insert")
    assert [len(q.payload) for q in inserts] == [50, 50, 20]
    row = db.tables["multimodal_chunks"][0]
    assert row["language"] == "hi" and len(row["embedding"]) == 1536
    assert "word_count" not in row and "visual_contexts" not in row
    assert cache.lecture_version("lec-emb") == version + 1


def test_index_reports_failures(db, embedder):
    assert embedding_engine.index_multimodal_chunks([], "lec") is False

    embedder.errors.append(RuntimeError("API key not valid"))
    assert embedding_engine.index_multimodal_chunks(make_chunks(2), "lec") is False
    assert db.queries_on("multimodal_chunks", "insert") == []


def test_index_reports_a_partial_save(db, embedder, monkeypatch):
    real_execute = db._execute

    def drop_rows(query):
        result = real_execute(query)
        if query.action == "insert":
            result.data = result.data[:-1]
        return result

    monkeypatch.setattr(db, "_execute", drop_rows)
    assert embedding_engine.index_multimodal_chunks(make_chunks(3), "lec") is False


def test_get_genai_configures_rest_once(monkeypatch):
    configured = []
    fake = types.ModuleType("google.generativeai")
    fake.configure = lambda **kwargs: configured.append(kwargs)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)
    import google

    monkeypatch.setattr(google, "generativeai", fake, raising=False)
    monkeypatch.setattr(embedding_engine, "_genai", None)

    assert embedding_engine.get_genai() is fake
    assert embedding_engine.get_genai() is fake
    assert configured == [{"api_key": "test-gemini-key", "transport": "rest"}]
