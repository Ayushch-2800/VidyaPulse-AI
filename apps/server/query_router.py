import re
from storage_utils import supabase
from typing import List, Dict, Any

# Import the existing embedding logic so dimensions (1536) match perfectly
from embedding_engine import generate_embeddings

def classify_intent(query: str) -> str:
    """Detects if the user wants exact counts/literal facts vs. conceptual understanding."""
    literal_patterns = r"(how many times|exactly|mention|say|count|exact word)"
    if re.search(literal_patterns, query.lower()):
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
    res = supabase.rpc(
        "match_multimodal_chunks",
        {
            "query_embedding": query_vector,
            "match_threshold": 0.3, 
            "match_count": 8,
            "p_lecture_id": lecture_id
        }
    ).execute()
    
    return res.data if res.data else []

def hybrid_intelligent_router(query: str, lecture_id: str) -> Dict[str, Any]:
    """Routes the query to the correct search method."""
    print(f"\n[ROUTER] Analyzing Query: '{query}'")
    intent = classify_intent(query)
    print(f"[ROUTER] Intent Detected: {intent.upper()}")
    
    if intent == "literal":
        context_blocks = route_1_literal_search(query, lecture_id)
    else:
        context_blocks = route_2_semantic_search(query, lecture_id)
        
    print(f"[ROUTER] Successfully retrieved {len(context_blocks)} context blocks.")
    return {
        "query": query,
        "intent": intent,
        "context_blocks": context_blocks
    }