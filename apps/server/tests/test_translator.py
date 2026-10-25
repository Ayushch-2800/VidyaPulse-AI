import json

import pytest

import translator
from fakes import gemini_response
from translator import TranslatedText, TranslationBatch


def translate_reply(transform):
    """A Gemini stand-in that applies `transform` to every item it is sent."""

    def reply(call):
        payload = json.loads(call["contents"].split("ITEMS:\n", 1)[1])
        return gemini_response(
            parsed=TranslationBatch(
                items=[
                    TranslatedText(id=i["id"], text=transform(i["text"]))
                    for i in payload
                ]
            )
        )

    return reply


def test_protect_and_restore_round_trip():
    text = "Use $\\frac{a}{b}$ and ```x = 1``` and `y` at [125:30] or $$E=mc^2$$."
    masked, tokens = translator.protect(text)
    assert masked == "Use {{0}} and {{1}} and {{2}} at {{3}} or {{4}}."
    assert translator.restore(masked.replace("Use", "उपयोग"), tokens).startswith(
        "उपयोग $\\frac{a}{b}$"
    )


@pytest.mark.parametrize(
    "damaged", ["{{0}} {{0}} {{2}}", "{{0}} {{1}}", "{{0}} {{1}} {{2}} {{3}}"]
)
def test_restore_rejects_damaged_placeholders(damaged):
    _, tokens = translator.protect("$a$ $b$ $c$")
    assert translator.restore(damaged, tokens) is None


def test_needs_translation():
    assert translator.needs_translation("Explain $x$") is True
    assert translator.needs_translation("$x^2$ [01:00]") is False
    assert translator.needs_translation("   ") is False


def test_batch_texts_respects_the_budget(monkeypatch):
    monkeypatch.setattr(translator, "MAX_BATCH_CHARS", 10)
    assert translator.batch_texts(["aaaa", "bbbb", "cccc", "dddddddddddd"]) == [
        ["aaaa", "bbbb"],
        ["cccc"],
        ["dddddddddddd"],
    ]


def test_english_and_unsupported_languages(gemini):
    assert translator.translate_texts(["Hello"], "en") == ["Hello"]
    with pytest.raises(ValueError, match="Unsupported language 'fr'"):
        translator.translate_texts(["Hello"], "fr")
    assert translator.translate_texts(["$x$", ""], "hi") == ["$x$", ""]
    assert gemini.calls == []


def test_translation_is_cached_and_deduplicated(db, gemini):
    gemini.default = translate_reply(lambda t: f"[hi] {t}")
    texts = [
        "The chain rule $f'(x)$ [01:00]",
        "Limits",
        "The chain rule $f'(x)$ [01:00]",
    ]
    first = translator.translate_texts(texts, "hi")
    assert first == [
        "[hi] The chain rule $f'(x)$ [01:00]",
        "[hi] Limits",
        "[hi] The chain rule $f'(x)$ [01:00]",
    ]
    sent = json.loads(gemini.calls[0]["contents"].split("ITEMS:\n", 1)[1])
    assert [i["text"] for i in sent] == ["The chain rule {{0}} {{1}}", "Limits"]
    assert len(db.tables["translations"]) == 2

    assert translator.translate_texts(texts, "hi") == first
    assert len(gemini.calls) == 1  # The second time is served from the cache


def test_damaged_items_keep_the_original_and_are_not_cached(db, gemini):
    gemini.default = translate_reply(lambda t: t.replace("{{0}}", ""))
    assert translator.translate_texts(["Area is $\\pi r^2$"], "ta") == [
        "Area is $\\pi r^2$"
    ]
    assert db.tables["translations"] == []


def test_cache_read_and_write_errors_do_not_fail_translation(db, gemini, capsys):
    gemini.default = translate_reply(lambda t: "அனுமானம்")
    db.fail(
        "translations", RuntimeError("PGRST205 translations does not exist"), times=2
    )
    assert translator.translate_texts(["Hypothesis"], "ta") == ["அனுமானம்"]
    out = capsys.readouterr().out
    assert "could not be read" in out and "could not save" in out


def test_cache_lookup_is_split_into_short_queries(db):
    hashes = [f"h{i}" for i in range(120)]
    translator.read_cache(hashes, "hi")
    sizes = [
        len(q.filter_value("in", "source_hash")) for q in db.queries_on("translations")
    ]
    assert sizes == [50, 50, 20]
    translator.write_cache([])
    assert len(db.queries) == 3
