import os
from typing import List, Dict, Any
import google.generativeai as genai
from storage_utils import supabase

# Uses the same GEMINI_API_KEY you already set up for the Vision task
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))


def get_valid_embedding_model():
    """Queries Google's API to find the exact embedding model authorized for your key."""
    print("[EMBEDDING SETUP]: Resolving Gemini embedding model...", flush=True)
    try:
        # Timeout so a slow or rate-limited API fails over instead of hanging every import
        for m in genai.list_models(request_options={"timeout": 30}):
            # Check if the model supports the 'embedContent' method
            if "embedContent" in m.supported_generation_methods:
                return m.name
    except Exception as e:
        print(f"[EMBEDDING SETUP ERROR]: Could not fetch models list: {e}")

    # Fallback to the current standard if dynamic fetch fails
    print(
        "[EMBEDDING SETUP]: WARNING - falling back to models/text-embedding-004. "
        "If your chunks were embedded with a different model, similarity scores will be wrong.",
        flush=True,
    )
    return "models/text-embedding-004"


# Fetch and store the authorized model name automatically
VALID_MODEL = get_valid_embedding_model()


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
