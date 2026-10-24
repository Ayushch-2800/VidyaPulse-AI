import re
from storage_utils import supabase
from typing import List, Dict, Any

# Import the existing embedding logic so dimensions (1536) match perfectly
from embedding_engine import generate_embeddings

SEMANTIC_MATCH_THRESHOLD = 0.3
SEMANTIC_MATCH_COUNT = 8
OVERVIEW_CHUNK_COUNT = 10  # ~2k chars each, fits the synthesizer's 24k context budget

# Broad questions about the whole lecture. They embed poorly against any single chunk,
# so vector search returns nothing above the threshold and the answer was "Not covered".
OVERVIEW_PATTERNS = (
    r"\b(summar(y|ies|ise|ize|ised|ized)|overview|recap|gist|tl;?dr|outline|"
    r"main (points?|ideas?|topics?|takeaways?)|key (points?|ideas?|topics?|takeaways?|concepts?)|"
    r"what (is|was) (this|the) (lecture|video|class|session) about|"
    r"what (does|did) (this|the) (lecture|video|class|session) cover|"
    r"what (topics|concepts) (are|were|does|did))\b"
)
# Word boundaries so "essay" or "account" don't trigger the literal route
LITERAL_PATTERNS = r"\b(how many times|exactly|mention(s|ed)?|say|says|said|count|exact words?)\b"


def classify_intent(query: str) -> str:
    """Detects overview requests, literal counts/facts, or conceptual (semantic) questions."""
    q = query.lower()
    if re.search(OVERVIEW_PATTERNS, q):
        return "overview"
    if re.search(LITERAL_PATTERNS, q):
        return "literal"
    return "semantic"

def route_1_literal_search(query: str, lecture_id: str) -> List[Dict[str, Any]]:
    """Route 1: Bypasses vector search and uses raw SQL text matching."""
    print("[ROUTER] Executing Route 1: Exact Text Match Search...")
    words = query.lower().replace("?", "").split()
    keyword = words[-1] if len(words) > 0 else query
    
    res = supabase.table("multimodal_chunks") \
        .select("id, composite_content") \
        .eq("lecture_id", lecture_id) \
        .ilike("transcript_text", f"%{keyword}%") \
        .execute()
        
    return res.data if res.data else []

def route_2_semantic_search(query: str, lecture_id: str) -> List[Dict[str, Any]]:
    """Route 2: Embeds the query and uses Cosine Similarity (<=>)."""
    print("[ROUTER] Executing Route 2: Semantic Vector Search...")
    
    # 1. Use your existing engine to generate the 1536-d vector
    embeddings = generate_embeddings([query])
    
    if not embeddings or len(embeddings) == 0:
        raise ValueError("Failed to generate embedding for the query.")
        
    query_vector = embeddings[0]
    
    # 2. Search Supabase
    def match(threshold: float) -> List[Dict[str, Any]]:
        res = supabase.rpc(
            "match_multimodal_chunks",
            {
                "query_embedding": query_vector,
                "match_threshold": threshold,
                "match_count": SEMANTIC_MATCH_COUNT,
                "p_lecture_id": lecture_id
            }
        ).execute()
        return res.data if res.data else []

    blocks = match(SEMANTIC_MATCH_THRESHOLD)
    if not blocks:
        # Nothing cleared the threshold: hand the LLM the nearest chunks anyway and let the
        # grounding prompt decide whether they answer the question
        print(f"[ROUTER] No chunks above {SEMANTIC_MATCH_THRESHOLD} similarity; retrying with the nearest {SEMANTIC_MATCH_COUNT}.")
        blocks = match(0.0)
    return blocks


def route_3_overview(lecture_id: str) -> List[Dict[str, Any]]:
    """Route 3: For summaries, samples chunks evenly across the whole lecture in order."""
    print("[ROUTER] Executing Route 3: Lecture Overview Sampling...")
    res = supabase.table("multimodal_chunks") \
        .select("id, chunk_index, composite_content") \
        .eq("lecture_id", lecture_id) \
        .order("chunk_index") \
        .execute()
    chunks = res.data or []

    if len(chunks) <= OVERVIEW_CHUNK_COUNT:
        return chunks
    # Always include the first and last chunk, spread the rest evenly in between
    step = (len(chunks) - 1) / (OVERVIEW_CHUNK_COUNT - 1)
    return [chunks[round(i * step)] for i in range(OVERVIEW_CHUNK_COUNT)]

def hybrid_intelligent_router(query: str, lecture_id: str) -> Dict[str, Any]:
    """Routes the query to the correct search method."""
    print(f"\n[ROUTER] Analyzing Query: '{query}'")
    intent = classify_intent(query)
    print(f"[ROUTER] Intent Detected: {intent.upper()}")
    
    if intent == "overview":
        context_blocks = route_3_overview(lecture_id)
    elif intent == "literal":
        context_blocks = route_1_literal_search(query, lecture_id)
    else:
        context_blocks = route_2_semantic_search(query, lecture_id)
        
    print(f"[ROUTER] Successfully retrieved {len(context_blocks)} context blocks.")
    return {
        "query": query,
        "intent": intent,
        "context_blocks": context_blocks
    }