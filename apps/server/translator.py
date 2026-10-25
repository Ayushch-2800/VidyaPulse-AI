"""
Task 18: Translates the workspace (answers, summary, cheat sheet, flashcards, quiz and notes)
into Indian languages with Gemini Flash.

Every result is cached in Supabase, so each text costs one free-tier call per language, ever.
Math, code and [MM:SS] citations are swapped for {{n}} placeholders before the call and put
back afterwards, so Gemini can never mangle LaTeX or move a timestamp.
"""

import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from gemini_utils import (
    CHAT_MODEL,
    FALLBACK_MODEL,
    INTERACTIVE_TIMEOUT_SECONDS,
    GeminiQuotaError,
    generate_structured,
    log,
)
from storage_utils import supabase

TAG = "TRANSLATE"

# Re-exported so main.py can answer 429 when today's quota is used up
TranslationQuotaError = GeminiQuotaError

# The codes the frontend's language switch sends. Generated content is written in English.
LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "bn": "Bengali",
}
SOURCE_LANGUAGE = "en"
MAX_TEXTS_PER_REQUEST = 300
# Translation is a simple task, so it runs on the fast Flash-Lite model by default, which also
# has its own free-tier quota, separate from (and larger than) the main chat model's. When its
# daily quota runs out, translation moves on to the main model.
TRANSLATE_MODEL = (
    os.getenv("GEMINI_TRANSLATE_MODEL", "").strip() or FALLBACK_MODEL or CHAT_MODEL
)
# The free tier counts requests per day, so each call carries a lot: a whole lecture's study
# set usually fits in two calls. Indic scripts take several times more output tokens than
# English, so a call is not made bigger than this.
MAX_BATCH_CHARS = 8000
# Gemini calls in flight at once for one request. Higher risks the free tier's per-minute quota.
PARALLEL_CALLS = 3
# A longer text (a summary) is split at paragraph breaks into parts of about this size, so its
# parts translate in parallel instead of in one slow call
MAX_PIECE_CHARS = 1200
# Hashes per PostgREST in() filter, so the request URL stays short
CACHE_LOOKUP_BATCH = 50

# Same math and code spans as the frontend's citations.ts, plus [MM:SS] citations
PROTECTED_PATTERN = re.compile(
    r"\$\$[\s\S]*?\$\$|\$[^$\n]+?\$|```[\s\S]*?```|`[^`\n]*`|\[\d{1,3}:[0-5]\d\]"
)
PLACEHOLDER_PATTERN = re.compile(r"\{\{(\d+)\}\}")
PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n\s*")
LETTER_PATTERN = re.compile(r"[^\W\d_]")


class TranslatedText(BaseModel):
    id: int
    text: str


class TranslationBatch(BaseModel):
    items: List[TranslatedText]


def translation_prompt(language: str) -> str:
    name = LANGUAGES[language]
    return f"""
You translate study material for Indian students into {name}.

Strictly follow these rules:
1. Translate every item's "text" into natural, student-friendly {name} in its native script. Return one item per input item, with the same "id".
2. Keep every placeholder such as {{{{0}}}} exactly as written, once each. They stand for formulas and timestamps.
3. Keep markdown formatting (**bold**, bullet points, headings, line breaks) where it is.
4. Technical terms that students usually say in English (e.g. "neural network", "derivative") may stay in English, in Latin script.
5. If a text is already in {name}, return it unchanged.
6. Translate only. Never add, drop, explain or summarize anything.
""".strip()


def protect(text: str) -> Tuple[str, List[str]]:
    """Replaces math, code and citations with {{0}}, {{1}}, ... and returns the replaced spans."""
    tokens: List[str] = []

    def swap(match: re.Match) -> str:
        tokens.append(match.group(0))
        return f"{{{{{len(tokens) - 1}}}}}"

    return PROTECTED_PATTERN.sub(swap, text), tokens


def restore(translated: str, tokens: List[str]) -> Optional[str]:
    """Puts the protected spans back. None if Gemini dropped, repeated or invented a placeholder."""
    found = sorted(int(n) for n in PLACEHOLDER_PATTERN.findall(translated))
    if found != list(range(len(tokens))):
        return None
    return PLACEHOLDER_PATTERN.sub(lambda m: tokens[int(m.group(1))], translated)


def needs_translation(text: str) -> bool:
    """False for blank text and text that is only math, code or timestamps."""
    masked, _ = protect(text)
    return bool(LETTER_PATTERN.search(PLACEHOLDER_PATTERN.sub("", masked)))


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_cache(hashes: List[str], language: str) -> Dict[str, str]:
    found: Dict[str, str] = {}
    try:
        for start in range(0, len(hashes), CACHE_LOOKUP_BATCH):
            res = (
                supabase.table("translations")
                .select("source_hash, translated_text")
                .eq("language", language)
                .in_("source_hash", hashes[start : start + CACHE_LOOKUP_BATCH])
                .execute()
            )
            found.update(
                {row["source_hash"]: row["translated_text"] for row in res.data or []}
            )
    except Exception as e:
        log(
            TAG,
            f"WARNING: the translations cache could not be read ({e}). Translating without it; "
            "run migrations/006_workspace.sql so repeat translations cost no Gemini calls.",
        )
    return found


def write_cache(rows: List[Dict[str, str]]) -> None:
    if not rows:
        return
    try:
        supabase.table("translations").upsert(
            rows, on_conflict="source_hash,language"
        ).execute()
    except Exception as e:
        log(
            TAG, f"WARNING: could not save {len(rows)} translation(s) to the cache: {e}"
        )


def batch_texts(texts: List[str]) -> List[List[str]]:
    """Groups texts so each Gemini call stays under MAX_BATCH_CHARS."""
    batches, current, size = [], [], 0
    for text in texts:
        if current and size + len(text) > MAX_BATCH_CHARS:
            batches.append(current)
            current, size = [], 0
        current.append(text)
        size += len(text)
    if current:
        batches.append(current)
    return batches


def split_long_text(text: str) -> Tuple[List[str], List[str]]:
    """
    Splits text longer than MAX_PIECE_CHARS at paragraph breaks outside math and code, into
    pieces of about MAX_PIECE_CHARS. Returns (pieces, separators), so that the pieces joined
    with the separators between them give back the text.
    """
    if len(text) <= MAX_PIECE_CHARS:
        return [text], []
    protected = [m.span() for m in PROTECTED_PATTERN.finditer(text)]
    pieces: List[str] = []
    separators: List[str] = []
    start = 0
    for brk in PARAGRAPH_BREAK.finditer(text):
        if brk.start() - start < MAX_PIECE_CHARS:
            continue
        if any(a < brk.start() < b for a, b in protected):
            continue
        pieces.append(text[start : brk.start()])
        separators.append(brk.group(0))
        start = brk.end()
    pieces.append(text[start:])
    return pieces, separators


def join_pieces(pieces: List[str], separators: List[str]) -> str:
    out = pieces[0]
    for separator, piece in zip(separators, pieces[1:]):
        out += separator + piece
    return out


def translate_batch(texts: List[str], language: str) -> List[Optional[str]]:
    """One structured Gemini call for the batch. An item that comes back damaged is None."""
    masked = [protect(text) for text in texts]
    payload = json.dumps(
        [{"id": i, "text": m} for i, (m, _) in enumerate(masked)], ensure_ascii=False
    )
    result = generate_structured(
        f"ITEMS:\n{payload}",
        translation_prompt(language),
        TranslationBatch,
        # Google advises against lowering Gemini 3's temperature: it can loop until the deadline
        temperature=None if TRANSLATE_MODEL.startswith("gemini-3") else 0.2,
        tag=TAG,
        # A student is waiting on this: no free-tier pacing, the short deadline, then the faster model
        pace=False,
        max_retries=3,
        timeout_seconds=INTERACTIVE_TIMEOUT_SECONDS,
        model=TRANSLATE_MODEL,
        fallback_model=CHAT_MODEL,
    )
    by_id = {item.id: item.text for item in result.items}

    restored: List[Optional[str]] = []
    for i, (_, tokens) in enumerate(masked):
        text = by_id.get(i, "")
        out = restore(text, tokens) if text.strip() else None
        if out is None:
            log(
                TAG,
                f"Item {i} came back missing or with damaged placeholders; keeping the original.",
            )
        restored.append(out)
    return restored


def translate_texts(texts: List[str], language: str) -> List[str]:
    """
    Returns `texts` translated into `language`, in the same order. Cached translations are
    reused. The rest go to Gemini in calls of up to MAX_BATCH_CHARS, PARALLEL_CALLS at a time,
    with long texts split into paragraphs first. Texts with nothing to translate, and any text
    Gemini returns damaged, come back unchanged.
    """
    if language not in LANGUAGES:
        raise ValueError(
            f"Unsupported language {language!r}. Choose one of: {', '.join(LANGUAGES)}."
        )
    results = list(texts)
    if language == SOURCE_LANGUAGE:
        return results

    # Each unique text is looked up and translated once, wherever it appears
    positions: Dict[str, List[int]] = {}
    for i, text in enumerate(texts):
        if needs_translation(text):
            positions.setdefault(text, []).append(i)
    if not positions:
        return results

    hashes = {text: source_hash(text) for text in positions}
    cached = read_cache(list(hashes.values()), language)
    hits: Dict[str, str] = {}
    missing = []
    for text, indexes in positions.items():
        hit = cached.get(hashes[text])
        if hit is None:
            missing.append(text)
            continue
        hits[text] = hit
        for i in indexes:
            results[i] = hit
    if not missing:
        return results

    # Long texts go in as their parts, which are cached on their own as well
    splits = {text: split_long_text(text) for text in missing}
    units = list(
        dict.fromkeys(
            piece
            for text in missing
            for piece in splits[text][0]
            if needs_translation(piece)
        )
    )
    unit_hashes = {u: hashes.get(u) or source_hash(u) for u in units}
    done: Dict[str, str] = {u: hits[u] for u in units if u in hits}
    parts = [u for u in units if u not in positions]
    if parts:
        part_cache = read_cache([unit_hashes[u] for u in parts], language)
        done.update(
            {
                u: part_cache[unit_hashes[u]]
                for u in parts
                if unit_hashes[u] in part_cache
            }
        )
    todo = [u for u in units if u not in done]

    name = LANGUAGES[language]
    batches = batch_texts(todo)
    log(
        TAG,
        f"{len(positions)} unique text(s) for {name}: {len(positions) - len(missing)} cached, "
        f"{len(missing)} to translate as {len(todo)} part(s) in {len(batches)} Gemini call(s), "
        f"up to {PARALLEL_CALLS} at a time.",
    )

    def run(
        batch: List[str],
    ) -> Tuple[List[Tuple[str, Optional[str]]], Optional[Exception]]:
        # Errors are returned, not raised, so the batches that did finish are still cached
        try:
            return list(zip(batch, translate_batch(batch, language))), None
        except Exception as e:
            return [], e

    failure: Optional[Exception] = None
    with ThreadPoolExecutor(
        max_workers=max(1, min(PARALLEL_CALLS, len(batches)))
    ) as pool:
        for batch_result, error in pool.map(run, batches):
            if error is not None:
                # A used-up daily quota is the one to report: it says what to do next
                if failure is None or isinstance(error, GeminiQuotaError):
                    failure = error
                continue
            new_rows = []
            for unit, out in batch_result:
                if out is None:
                    continue
                done[unit] = out
                new_rows.append(
                    {
                        "source_hash": unit_hashes[unit],
                        "language": language,
                        "translated_text": out,
                        "model": TRANSLATE_MODEL,
                    }
                )
            write_cache(new_rows)
    if failure is not None:
        raise failure

    whole_rows = []
    for text in missing:
        pieces, separators = splits[text]
        if len(pieces) == 1:
            out = done.get(text)
            if out is None:
                continue
        else:
            out = join_pieces([done.get(p, p) for p in pieces], separators)
            # A part that came back damaged stays in English; retry the whole text next time
            if all(p in done or not needs_translation(p) for p in pieces):
                whole_rows.append(
                    {
                        "source_hash": hashes[text],
                        "language": language,
                        "translated_text": out,
                        "model": TRANSLATE_MODEL,
                    }
                )
        for i in positions[text]:
            results[i] = out
    write_cache(whole_rows)

    log(TAG, f"Translation into {name} done.")
    return results
