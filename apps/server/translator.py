"""
Task 18: Translates the workspace (answers, summary, cheat sheet, flashcards, quiz and notes)
into Indian languages with Gemini Flash.

Every result is cached in Supabase, so each text costs one free-tier call per language, ever.
Math, code and [MM:SS] citations are swapped for {{n}} placeholders before the call and put
back afterwards, so Gemini can never mangle LaTeX or move a timestamp.
"""

import hashlib
import json
import re
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from gemini_utils import CHAT_MODEL, generate_structured, log
from storage_utils import supabase

TAG = "TRANSLATE"

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
# Indic scripts take several times more output tokens than English, so keep each call small
MAX_BATCH_CHARS = 6000
# Hashes per PostgREST in() filter, so the request URL stays short
CACHE_LOOKUP_BATCH = 50

# Same math and code spans as the frontend's citations.ts, plus [MM:SS] citations
PROTECTED_PATTERN = re.compile(
    r"\$\$[\s\S]*?\$\$|\$[^$\n]+?\$|```[\s\S]*?```|`[^`\n]*`|\[\d{1,3}:[0-5]\d\]"
)
PLACEHOLDER_PATTERN = re.compile(r"\{\{(\d+)\}\}")
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
        temperature=0.2,
        tag=TAG,
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
    reused; the rest go to Gemini in as few calls as fit MAX_BATCH_CHARS. Texts with nothing to
    translate, and any text Gemini returns damaged, come back unchanged.
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
    missing = []
    for text, indexes in positions.items():
        hit = cached.get(hashes[text])
        if hit is None:
            missing.append(text)
            continue
        for i in indexes:
            results[i] = hit

    name = LANGUAGES[language]
    batches = batch_texts(missing)
    log(
        TAG,
        f"{len(positions)} unique text(s) for {name}: {len(positions) - len(missing)} cached, "
        f"{len(missing)} to translate in {len(batches)} Gemini call(s).",
    )

    for n, batch in enumerate(batches, start=1):
        log(TAG, f"Gemini call {n}/{len(batches)}: {len(batch)} text(s) into {name}...")
        new_rows = []
        for text, translated in zip(batch, translate_batch(batch, language)):
            if translated is None:
                continue
            for i in positions[text]:
                results[i] = translated
            new_rows.append(
                {
                    "source_hash": hashes[text],
                    "language": language,
                    "translated_text": translated,
                    "model": CHAT_MODEL,
                }
            )
        write_cache(new_rows)

    log(TAG, f"Translation into {name} done.")
    return results
