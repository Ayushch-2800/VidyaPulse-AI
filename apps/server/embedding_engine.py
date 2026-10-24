import os
from typing import List, Dict, Any
import google.generativeai as genai
from google.api_core import retry as api_retry
from storage_utils import supabase

# REST instead of gRPC: gRPC channel setup can stall silently on some networks and has no timeout
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"), transport="rest")

# Fixed model name, no catalog lookup: listing models was a network call at import time that
# could freeze every script importing this module. gemini-embedding-001 is the Gemini embedding
# model that supports output_dimensionality=1536. Override if your chunks used another model.
VALID_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
EMBED_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "60"))
print(f"[EMBEDDING SETUP]: Using embedding model {VALID_MODEL}", flush=True)


def generate_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Calls Google Gemini API to batch-generate semantic embeddings,
    specifically truncated to 1536 dimensions to match the Supabase schema.
    """
    if not texts:
        return []

    try:
        response = genai.embed_content(
            model=VALID_MODEL,
            content=texts,
            task_type="semantic_similarity",
            output_dimensionality=1536,  # <-- Forces Gemini to match your Supabase table size
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

    # 4. Execute Bulk Insert to Supabase PostgreSQL
    print(
        "[EMBEDDING PIPELINE]: Pushing vectors and metadata to Supabase 'multimodal_chunks' table..."
    )
    response = supabase.table("multimodal_chunks").insert(db_payload).execute()

    if hasattr(response, "data") and response.data:
        print(
            f"[EMBEDDING PIPELINE]: Successfully indexed {len(response.data)} vectorized chunks."
        )
        return True
    else:
        print("[EMBEDDING PIPELINE]: Warning - Insert executed but no data returned.")
        return False
