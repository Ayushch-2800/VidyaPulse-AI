import re
import time
import unicodedata
from storage_utils import supabase
from typing import List, Dict, Any, Optional

import cache

# Import the existing embedding logic so dimensions (1536) match perfectly
from embedding_engine import embed_query

SEMANTIC_MATCH_THRESHOLD = 0.3
SEMANTIC_MATCH_COUNT = 8
OVERVIEW_CHUNK_COUNT = 10  # ~2k chars each, fits the synthesizer's 24k context budget
# The synthesizer keeps ~24k chars of context, about 12 chunks, so more matches are never read
LITERAL_MATCH_LIMIT = 20
# Every route returns these, so the synthesizer can cite them without another Supabase lookup
CHUNK_COLUMNS = (
    "id, chunk_index, start_time_seconds, end_time_seconds, composite_content"
)

# Broad questions about the whole lecture. They embed poorly against any single chunk,
# so vector search returns nothing above the threshold and the answer was "Not covered".
OVERVIEW_PATTERNS = (
    r"\b(summar(y|ies|ise|ize|ised|ized)|overview|recap|gist|tl;?dr|outline|"
    r"main (points?|ideas?|topics?|takeaways?)|key (points?|ideas?|topics?|takeaways?|concepts?)|"
    r"what (is|was) (this|the) (lecture|video|class|session) about|"
    r"what (does|did) (this|the) (lecture|video|class|session) cover|"
    r"what (topics|concepts) (are|were|does|did))\b"
)
# Word boundaries so "essay" or "account" don't trigger the literal route.
# "kitni/kitne baar" is Hinglish for "how many times".
LITERAL_PATTERNS = (
    r"\b(how many times|exactly|mention(s|ed)?|say|says|said|count|exact words?|"
    r"kitni (baar|bar)|kitne (baar|bar))\b"
)
# Words of the question itself, never the term being searched for
LITERAL_STOPWORDS = set("""
    a an and any are at baar bar bola boli by count did do does exact exactly for from has
    have he her his how in is it kaha kitne kitni lecture many mam madam me mention mentioned
    mentions ne number of on phrase professor say said says she sir teacher term that the they
    this time times to use used uses video was were what word words you
    """.split())
# A term in quotes, e.g. say 'derivative' or "chain rule". The quote must open after a space,
# so the apostrophes in "what's" or "teacher's" are not mistaken for one.
QUOTED_TERM_PATTERN = re.compile(r"(?:^|\s)[\"'“‘](.+?)[\"'”’](?=$|[\s?.!,;:])")
# SQL LIKE wildcards and escapes, treated as spaces so a term can never act as a pattern
LIKE_SPECIAL_PATTERN = re.compile(r"[%_*\\]")


def classify_intent(query: str) -> str:
    """Detects overview requests, literal counts/facts, or conceptual (semantic) questions."""
    q = query.lower()
    if re.search(OVERVIEW_PATTERNS, q):
        return "overview"
    if re.search(LITERAL_PATTERNS, q):
        return "literal"
    return "semantic"


def literal_keyword(query: str) -> str:
    """
    The term a literal question asks about: a quoted term if there is one, else the last word
    that is not part of the question ("How many times is the word derivative mentioned?" ->
    "derivative"). Only letters, digits, spaces and hyphens are kept, so the term can't act as
    an SQL LIKE wildcard.
    """
    quoted = QUOTED_TERM_PATTERN.search(query)
    if quoted:
        words = clean_words(quoted.group(1))
    else:
        words = clean_words(query.lower())
        terms = [w for w in words if w not in LITERAL_STOPWORDS]
        words = (terms or words)[-1:]
    return " ".join(words)


def clean_words(text: str) -> List[str]:
    """
    Splits on spaces and keeps letters, digits and hyphens in any script. Unicode categories
    rather than a word-character regex, which would split Hindi or Tamil words at vowel signs.
    """
    words = []
    for raw in LIKE_SPECIAL_PATTERN.sub(" ", text).split():
        raw = re.sub(r"['’]s$", "", raw)  # teacher's -> teacher
        word = "".join(
            c for c in raw if c == "-" or unicodedata.category(c)[0] in "LMN"
        ).strip("-")
        if word:
            words.append(word)
    return words


def route_1_literal_search(query: str, lecture_id: str) -> List[Dict[str, Any]]:
    """Route 1: Bypasses vector search and uses raw SQL text matching."""
    print("[ROUTER] Executing Route 1: Exact Text Match Search...")
    keyword = literal_keyword(query)
    if not keyword:
        return []
    print(f"[ROUTER] Searching the transcript for '{keyword}'...")

    res = (
        supabase.table("multimodal_chunks")
        .select(CHUNK_COLUMNS)
        .eq("lecture_id", lecture_id)
        .ilike("transcript_text", f"%{keyword}%")
        .order("chunk_index")
        .limit(LITERAL_MATCH_LIMIT)
        .execute()
    )

    return res.data if res.data else []


def route_2_semantic_search(
    query: str, lecture_id: str, timings: Optional[Dict[str, float]] = None
) -> List[Dict[str, Any]]:
    """Route 2: Embeds the query and uses Cosine Similarity (<=>)."""
    print("[ROUTER] Executing Route 2: Semantic Vector Search...")
    timings = timings if timings is not None else {}

    # 1. Use your existing engine to generate the 1536-d vector (cached for repeat questions)
    started = time.perf_counter()
    query_vector = embed_query(query)
    timings["embedding_ms"] = elapsed_ms(started)

    if not query_vector:
        raise ValueError("Failed to generate embedding for the query.")

    # 2. Search Supabase
    def match(threshold: float) -> List[Dict[str, Any]]:
        res = supabase.rpc(
            "match_multimodal_chunks",
            {
                "query_embedding": query_vector,
                "match_threshold": threshold,
                "match_count": SEMANTIC_MATCH_COUNT,
                "p_lecture_id": lecture_id,
            },
        ).execute()
        return res.data if res.data else []

    started = time.perf_counter()
    blocks = match(SEMANTIC_MATCH_THRESHOLD)
    if not blocks:
        # Nothing cleared the threshold: hand the LLM the nearest chunks anyway and let the
        # grounding prompt decide whether they answer the question
        print(
            f"[ROUTER] No chunks above {SEMANTIC_MATCH_THRESHOLD} similarity; retrying with the nearest {SEMANTIC_MATCH_COUNT}."
        )
        blocks = match(0.0)
    timings["vector_search_ms"] = elapsed_ms(started)
    return blocks


def sample_evenly(chunks: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    """`count` chunks spread across the list in order, always including the first and last."""
    if len(chunks) <= count:
        return chunks
    step = (len(chunks) - 1) / (count - 1)
    return [chunks[round(i * step)] for i in range(count)]


def route_3_overview(lecture_id: str) -> List[Dict[str, Any]]:
    """Route 3: For summaries, samples chunks evenly across the whole lecture in order."""
    print("[ROUTER] Executing Route 3: Lecture Overview Sampling...")
    res = (
        supabase.table("multimodal_chunks")
        .select(CHUNK_COLUMNS)
        .eq("lecture_id", lecture_id)
        .order("chunk_index")
        .execute()
    )
    return sample_evenly(res.data or [], OVERVIEW_CHUNK_COUNT)


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def hybrid_intelligent_router(query: str, lecture_id: str) -> Dict[str, Any]:
    """
    Routes the query to the correct search method. Task 19: results are cached per lecture,
    so a repeat question costs no Gemini embedding call and no Supabase round trip.
    """
    started = time.perf_counter()
    print(f"\n[ROUTER] Analyzing Query: '{query}'")
    intent = classify_intent(query)
    print(f"[ROUTER] Intent Detected: {intent.upper()}")

    # An overview samples the same chunks whatever the wording, so it needs no query in its key
    key_parts = () if intent == "overview" else (cache.text_hash(query),)
    key = cache.lecture_key(f"search-{intent}", lecture_id, *key_parts)
    timings: Dict[str, float] = {}

    context_blocks = cache.get_json(key)
    search_cached = context_blocks is not None
    if search_cached:
        print("[ROUTER] Search results served from the cache.")
    else:
        if intent == "overview":
            context_blocks = route_3_overview(lecture_id)
        elif intent == "literal":
            context_blocks = route_1_literal_search(query, lecture_id)
        else:
            context_blocks = route_2_semantic_search(query, lecture_id, timings)
        cache.set_json(key, context_blocks, cache.SEARCH_TTL_SECONDS)

    timings["retrieval_ms"] = elapsed_ms(started)
    print(
        f"[ROUTER] Successfully retrieved {len(context_blocks)} context blocks in {timings['retrieval_ms']:.0f} ms."
    )
    return {
        "query": query,
        "intent": intent,
        "context_blocks": context_blocks,
        "cached": search_cached,
        "timings_ms": timings,
    }
