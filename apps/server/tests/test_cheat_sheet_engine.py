import json

import pytest

import cheat_sheet_engine as engine
from cheat_sheet_engine import CheatSheetBatch, CheatSheetItem
from fakes import fake_vector, gemini_response
from gemini_utils import GeminiKeyError
from lecture_factory import seed_four_hour_lecture

LECTURE = "lec-cheat"


def chunk(index, text, seconds=60.0):
    return {
        "lecture_id": LECTURE,
        "chunk_index": index,
        "start_time_seconds": index * seconds,
        "end_time_seconds": (index + 1) * seconds,
        "composite_content": text,
    }


def item(kind, title, latex="", timestamp="00:30", explanation="Used often."):
    return CheatSheetItem(
        kind=kind,
        title=title,
        latex=latex,
        explanation=explanation,
        timestamp=timestamp,
    )


def test_batches_stay_under_the_character_budget():
    chunks = [chunk(i, "x" * 5000) for i in range(5)]
    assert [len(b) for b in engine.batch_chunks(chunks)] == [2, 2, 1]
    assert engine.batch_chunks([]) == []
    assert [len(b) for b in engine.batch_chunks([chunk(0, "y" * 20000)])] == [1]


def test_batch_prompt_labels_each_chunk():
    prompt = engine.build_batch_prompt([chunk(0, "intro"), chunk(125, " limits ")])
    assert prompt.startswith("LECTURE CHUNKS:")
    assert (
        "--- Chunk | timestamp 125:00 | covers 125:00 to 126:00 ---\nlimits" in prompt
    )


@pytest.mark.parametrize(
    "label, seconds",
    [
        ("01:30", 90.0),
        ("[01:30]", 90.0),
        ("02:04", 124.0),
        ("05:00", None),
        ("1:30:00", None),
        ("soon", None),
    ],
)
def test_resolve_timestamp_rejects_invented_labels(label, seconds):
    batch = [chunk(0, "a"), chunk(1, "b")]  # covers 00:00-02:00, plus 5s tolerance
    assert engine.resolve_timestamp(label, batch) == seconds


def test_normalize_key_ignores_latex_spacing():
    a = {"kind": "formula", "latex": "a^2 + b^2", "title": "Pythagoras"}
    b = {"kind": "formula", "latex": "a^2+b^2", "title": "Pythagorean theorem"}
    c = {"kind": "definition", "latex": "", "title": " Limit "}
    assert engine.normalize_key(a) == engine.normalize_key(b)
    assert engine.normalize_key(c) == "definition:limit"


def test_extract_items_dedupes_overlap_and_drops_bad_kinds(monkeypatch):
    replies = [
        [
            item("formula", "Chain rule", "$f(g(x))' = f'(g(x))g'(x)$"),
            item("example", "Skip me"),
            item("theorem", "  "),
        ],
        [item("Formula", "Chain rule again", "f(g(x))'=f'(g(x))g'(x)", "02:10")],
    ]
    monkeypatch.setattr(engine, "call_gemini_structured", lambda prompt: replies.pop(0))
    monkeypatch.setattr(engine, "MAX_BATCH_CHARS", 10)
    items = engine.extract_items(
        [chunk(0, "chain rule text"), chunk(2, "repeat of it")]
    )
    assert len(items) == 1
    assert (
        items[0]["latex"] == "f(g(x))' = f'(g(x))g'(x)"
        and items[0]["timestamp_seconds"] == 30.0
    )


def test_parse_vector_and_cosine():
    assert engine.parse_vector("[0.5, 1]") == [0.5, 1]
    assert engine.parse_vector([1, 2]) == [1, 2]
    assert engine.parse_vector(None) == []
    assert engine.cosine_similarity([1, 0], [1, 0]) == 1.0
    assert engine.cosine_similarity([0, 0], [1, 0]) == 0.0


def test_tagging_without_seeded_topics_skips_gemini(db, embedder):
    items = [{"title": "Limit", "explanation": "", "latex": ""}]
    assert engine.tag_exam_topics(items) == []
    assert items[0]["exam_topics"] == [] and embedder.calls == []


def test_tagging_matches_items_to_exam_topics(db, embedder, no_sleep):
    topics = [
        ("JEE", "Mathematics", "Chain rule of differentiation"),
        ("NEET", "Biology", "Photosynthesis in plants"),
    ]
    db.seed(
        "exam_topics",
        [
            {
                "id": i,
                "exam": e,
                "subject": s,
                "topic": t,
                "embedding": json.dumps(fake_vector(f"{t}")),
            }
            for i, (e, s, t) in enumerate(topics)
        ]
        + [
            {
                "id": 9,
                "exam": "GATE",
                "subject": "CS",
                "topic": "Unembedded",
                "embedding": None,
            }
        ],
    )
    items = [
        {
            "title": "Chain rule",
            "explanation": "differentiation of composite functions",
            "latex": "",
        },
        {"title": "Chain rule of differentiation", "explanation": "", "latex": ""},
    ]
    lecture_tags = engine.tag_exam_topics(items)
    assert items[1]["exam_topics"][0]["topic"] == "Chain rule of differentiation"
    threshold = engine.TOPIC_MATCH_THRESHOLD
    assert all(m["similarity"] >= threshold for i in items for m in i["exam_topics"])
    assert lecture_tags[0]["exam"] == "JEE" and lecture_tags[0]["item_count"] >= 1
    assert "Photosynthesis in plants" not in [t["topic"] for t in lecture_tags]


def test_generate_cheat_sheet_end_to_end(db, embedder, gemini):
    db.seed(
        "multimodal_chunks",
        [chunk(0, "the derivative of sin is cos"), chunk(1, "chain rule")],
    )
    gemini.replies.append(
        gemini_response(
            parsed=CheatSheetBatch(
                items=[
                    item("formula", "Chain rule", "f(g(x))'", "01:10"),
                    item("definition", "Derivative", "", "00:05"),
                    item("theorem", "Invented", "", "45:00"),
                ]
            )
        )
    )
    result = engine.generate_cheat_sheet(LECTURE)
    assert result["status"] == "completed"
    content = result["content"]
    assert [i["title"] for i in content["definitions"]] == ["Derivative"]
    assert content["theorems"][0]["timestamp_seconds"] is None
    (row,) = db.tables["cheat_sheets"]
    assert row["status"] == "completed" and row["model"] == "gemini-3.8-flash"
    assert [q.payload["status"] for q in db.queries_on("cheat_sheets", "upsert")] == [
        "processing",
        "completed",
    ]


def test_generate_cheat_sheet_failures_are_recorded(db, gemini):
    assert engine.generate_cheat_sheet(LECTURE)["status"] == "failed"
    assert "No indexed chunks" in db.tables["cheat_sheets"][0]["error"]

    db.fail("cheat_sheets:upsert", RuntimeError("relation does not exist"), times=2)
    result = engine.generate_cheat_sheet("other")
    assert "004_cheat_sheets.sql" in result["error"]


def test_invalid_gemini_key_is_reported(db, monkeypatch, capsys):
    db.seed("multimodal_chunks", [chunk(0, "x")])

    def reject(prompt):
        raise GeminiKeyError("Gemini rejected GEMINI_API_KEY")

    monkeypatch.setattr(engine, "call_gemini_structured", reject)
    assert engine.generate_cheat_sheet(LECTURE)["status"] == "failed"
    assert "[CHEATSHEET INVALID GEMINI KEY]" in capsys.readouterr().err


def test_four_hour_lecture_needs_about_two_dozen_calls(db):
    seed_four_hour_lecture(db, LECTURE)
    chunks = engine.fetch_lecture_chunks(LECTURE)
    batches = engine.batch_chunks(chunks)
    assert len(chunks) > 100
    assert 15 <= len(batches) <= 40
    assert sum(len(b) for b in batches) == len(chunks)
