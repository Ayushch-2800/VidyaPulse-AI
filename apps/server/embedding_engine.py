import os
from typing import List, Dict, Any, Optional

import cache
from storage_utils import supabase

# Fixed model name, no catalog lookup: listing models was a network call at import time that
# could freeze every script importing this module. gemini-embedding-001 is the Gemini embedding
# model that supports output_dimensionality=1536. Override if your chunks used another model.
VALID_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
EMBED_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "60"))
EMBEDDING_DIMENSIONS = 1536
# Rows per Supabase insert: each row carries a 1536-d vector (~20 KB of JSON), so a 4-hour
# lecture's ~150 chunks go up in a few requests instead of one multi-megabyte body
INSERT_BATCH_SIZE = 50

_genai = None


def get_genai():
    """Imports and configures the Gemini embedding SDK on first use, never at import time."""
    global _genai
    if _genai is None:
        import google.generativeai as genai

        # REST instead of gRPC: gRPC channel setup can stall silently on some networks
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY"), transport="rest")
        print(f"[EMBEDDING SETUP]: Using embedding model {VALID_MODEL}", flush=True)
        _genai = genai
    return _genai


def generate_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Calls Google Gemini API to batch-generate semantic embeddings,
    specifically truncated to 1536 dimensions to match the Supabase schema.
    """
    if not texts:
        return []

    from google.api_core import retry as api_retry

    try:
        response = get_genai().embed_content(
            model=VALID_MODEL,
            content=texts,
            task_type="semantic_similarity",
            output_dimensionality=EMBEDDING_DIMENSIONS,  # <-- Forces Gemini to match your Supabase table size
            request_options={
                "timeout": EMBED_TIMEOUT_SECONDS,
                # Retry 429/503 briefly, but never wait more than 2 minutes in total
                "retry": api_retry.Retry(
                    predicate=api_retry.if_transient_error, timeout=120
                ),
            },
        )
        # Gemini returns a list of embeddings when provided a list of texts
        return response["embedding"]
    except Exception as e:
        print(f"[EMBEDDING ERROR]: {e}")
        return []


def embed_query(text: str) -> Optional[List[float]]:
    """
    Task 19: The 1536-d vector for a student's question. Repeat questions (any case or spacing)
    come from the cache instead of Gemini. None if Gemini failed; failures are never cached.
    """
    key = f"embedding:{VALID_MODEL}:{EMBEDDING_DIMENSIONS}:{cache.text_hash(text)}"
    vector = cache.get_json(key)
    if vector is not None:
        return vector
    embeddings = generate_embeddings([text])
    if not embeddings or len(embeddings[0]) != EMBEDDING_DIMENSIONS:
        return None
    cache.set_json(key, embeddings[0], cache.EMBEDDING_TTL_SECONDS)
    return embeddings[0]


def index_multimodal_chunks(chunks: List[Dict[str, Any]], lecture_id: str) -> bool:
    """
    Takes the unified temporal chunks, generates dense vectors for their
    composite content, and bulk-inserts them into the Supabase pgvector table.
    """
    if not chunks:
        print("[EMBEDDING PIPELINE]: No chunks provided to index.")
        return False

    # 1. Extract the rich Markdown composite text (Audio + Visual OCR) for embedding
    texts_to_embed = [chunk["composite_content"] for chunk in chunks]

    # Updated print statement to reflect the correct dimensions
    print(
        f"[EMBEDDING PIPELINE]: Generating 1536-d Gemini vectors using {VALID_MODEL} for {len(texts_to_embed)} chunks..."
    )

    # 2. Batch-generate vectors
    embeddings = generate_embeddings(texts_to_embed)

    if not embeddings or len(embeddings) != len(chunks):
        print("[EMBEDDING PIPELINE]: Failed to generate embeddings for all chunks.")
        return False

    # 3. Construct the payload for bulk database insertion
    db_payload = []
    for i, chunk in enumerate(chunks):
        db_payload.append(
            {
                "lecture_id": lecture_id,
                "chunk_index": chunk["chunk_index"],
                "start_time_seconds": chunk["start_time_seconds"],
                "end_time_seconds": chunk["end_time_seconds"],
                "duration_seconds": chunk["duration_seconds"],
                "transcript_text": chunk["transcript_text"],
                "visual_context_count": chunk["visual_context_count"],
                "composite_content": chunk["composite_content"],
                "language": chunk.get("language", "unknown"),
                "embedding": embeddings[i],  # The 1536-dimensional array
            }
        )

    # 4. Execute Bulk Insert to Supabase PostgreSQL, a batch at a time
    print(
        "[EMBEDDING PIPELINE]: Pushing vectors and metadata to Supabase 'multimodal_chunks' table..."
    )
    saved = 0
    for start in range(0, len(db_payload), INSERT_BATCH_SIZE):
        response = (
            supabase.table("multimodal_chunks")
            .insert(db_payload[start : start + INSERT_BATCH_SIZE])
            .execute()
        )
        saved += len(getattr(response, "data", None) or [])

    # New chunks make any cached search or answer for this lecture stale
    cache.invalidate_lecture(lecture_id)

    if saved == len(db_payload):
        print(f"[EMBEDDING PIPELINE]: Successfully indexed {saved} vectorized chunks.")
        return True
    print(
        f"[EMBEDDING PIPELINE]: Warning - only {saved} of {len(db_payload)} chunks were saved."
    )
    return False
