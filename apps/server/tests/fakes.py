"""
In-memory stand-ins for Supabase and Gemini, so the whole suite runs offline in seconds and
never spends free-tier quota.

FakeSupabase implements the slice of the supabase-py / postgrest query builder the app uses
(select, insert, update, upsert, delete, eq, ilike, in_, order, range, limit, rpc), records every
query it executes, and can simulate network latency and failures.
"""

import hashlib
import math
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

DIMENSIONS = 1536
# Simulated network latency must stay real even when a test replaces time.sleep
_real_sleep = time.sleep


class Result:
    def __init__(self, data):
        self.data = data


def _same(a: Any, b: Any) -> bool:
    return a == b or (a is not None and b is not None and str(a) == str(b))


def _like_to_regex(pattern: str) -> re.Pattern:
    parts = []
    for char in pattern:
        if char == "%":
            parts.append(".*")
        elif char == "_":
            parts.append(".")
        else:
            parts.append(re.escape(char))
    return re.compile("".join(parts), re.IGNORECASE | re.DOTALL)


class FakeQuery:
    def __init__(self, db: "FakeSupabase", table: str):
        self.db = db
        self.table = table
        self.action = "select"
        self.columns = "*"
        self.filters: List[tuple] = []
        self.orders: List[tuple] = []
        self.range_: Optional[tuple] = None
        self.limit_: Optional[int] = None
        self.payload: Any = None
        self.on_conflict: Optional[str] = None

    # Actions
    def select(self, columns: str = "*", **_):
        self.action, self.columns = "select", columns
        return self

    def insert(self, rows, **_):
        self.action, self.payload = "insert", rows
        return self

    def update(self, changes, **_):
        self.action, self.payload = "update", changes
        return self

    def upsert(self, rows, on_conflict: Optional[str] = None, **_):
        self.action, self.payload, self.on_conflict = "upsert", rows, on_conflict
        return self

    def delete(self, **_):
        self.action = "delete"
        return self

    # Filters and modifiers
    def eq(self, column: str, value: Any):
        self.filters.append(("eq", column, value))
        return self

    def ilike(self, column: str, pattern: str):
        self.filters.append(("ilike", column, pattern))
        return self

    def in_(self, column: str, values):
        self.filters.append(("in", column, list(values)))
        return self

    def order(self, column: str, desc: bool = False):
        self.orders.append((column, desc))
        return self

    def range(self, start: int, end: int):
        self.range_ = (start, end)
        return self

    def limit(self, count: int):
        self.limit_ = count
        return self

    def execute(self):
        return self.db._execute(self)

    def matches(self, row: Dict[str, Any]) -> bool:
        for op, column, value in self.filters:
            cell = row.get(column)
            if op == "eq" and not _same(cell, value):
                return False
            if op == "in" and not any(_same(cell, v) for v in value):
                return False
            if op == "ilike" and not (
                isinstance(cell, str) and _like_to_regex(value).fullmatch(cell)
            ):
                return False
        return True

    def filter_value(self, op: str, column: str) -> Any:
        for f_op, f_column, value in self.filters:
            if f_op == op and f_column == column:
                return value
        return None


class FakeStorageBucket:
    def __init__(self, storage: "FakeStorage", bucket: str):
        self.storage, self.bucket = storage, bucket

    def upload(self, path=None, file=None, file_options=None, **kwargs):
        if self.storage.error:
            raise self.storage.error
        body = file.read() if hasattr(file, "read") else file
        self.storage.uploads.append(
            {
                "bucket": self.bucket,
                "path": path,
                "bytes": body,
                "options": file_options,
            }
        )
        return {"Key": f"{self.bucket}/{path}"}

    def create_signed_url(self, path, expiration_seconds):
        if self.storage.error:
            raise self.storage.error
        return {
            "signedURL": f"https://storage.test/{self.bucket}/{path}?exp={expiration_seconds}"
        }


class FakeStorage:
    def __init__(self):
        self.uploads: List[Dict[str, Any]] = []
        self.error: Optional[Exception] = None

    def from_(self, bucket: str) -> FakeStorageBucket:
        return FakeStorageBucket(self, bucket)


class FakeAuth:
    def __init__(self):
        self.response: Any = None
        self.error: Optional[Exception] = None
        self.tokens: List[str] = []

    def get_user(self, token: str):
        self.tokens.append(token)
        if self.error:
            raise self.error
        return self.response


class FakeRpc:
    def __init__(self, db: "FakeSupabase", name: str, params: Dict[str, Any]):
        self.db, self.name, self.params = db, name, params

    def execute(self):
        self.db._delay()
        self.db.rpc_calls.append((self.name, self.params))
        error = self.db._take_error(f"rpc:{self.name}")
        if error:
            raise error
        handler = self.db.rpc_handlers.get(self.name)
        if handler is None:
            raise RuntimeError(
                f"PGRST202: Could not find the function public.{self.name}"
            )
        return Result(handler(self.params))


class FakeSupabase:
    def __init__(self):
        self.tables: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.queries: List[FakeQuery] = []
        self.rpc_calls: List[tuple] = []
        self.rpc_handlers: Dict[str, Callable] = {
            "match_multimodal_chunks": self._match_multimodal_chunks
        }
        self.storage = FakeStorage()
        self.auth = FakeAuth()
        self.latency_seconds = 0.0
        self._errors: Dict[str, List[Exception]] = defaultdict(list)

    # Test helpers
    def seed(self, table: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        stored = [self._with_defaults(dict(row)) for row in rows]
        self.tables[table].extend(stored)
        return stored

    def fail(self, target: str, error: Exception, times: int = 1) -> None:
        """Makes the next `times` queries on `target` raise. target: a table, 'table:action' or 'rpc:name'."""
        self._errors[target].extend([error] * times)

    def queries_on(self, table: str, action: Optional[str] = None) -> List[FakeQuery]:
        return [
            q
            for q in self.queries
            if q.table == table and (action is None or q.action == action)
        ]

    def reset_log(self) -> None:
        self.queries.clear()
        self.rpc_calls.clear()

    # Client surface
    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)

    def rpc(self, name: str, params: Dict[str, Any]) -> FakeRpc:
        return FakeRpc(self, name, params)

    # Internals
    def _delay(self) -> None:
        if self.latency_seconds:
            _real_sleep(self.latency_seconds)

    def _take_error(self, *targets: str) -> Optional[Exception]:
        for target in targets:
            if self._errors.get(target):
                return self._errors[target].pop(0)
        return None

    def _with_defaults(self, row: Dict[str, Any]) -> Dict[str, Any]:
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        return row

    def _project(self, row: Dict[str, Any], columns: str) -> Dict[str, Any]:
        if columns.strip() == "*":
            return dict(row)
        return {c.strip(): row.get(c.strip()) for c in columns.split(",") if c.strip()}

    def _execute(self, query: FakeQuery) -> Result:
        self._delay()
        self.queries.append(query)
        error = self._take_error(f"{query.table}:{query.action}", query.table)
        if error:
            raise error

        rows = self.tables[query.table]
        if query.action == "select":
            selected = [r for r in rows if query.matches(r)]
            for column, desc in reversed(query.orders):
                # None sorts last, like Postgres's default for ascending order
                selected.sort(
                    key=lambda r: (
                        r.get(column) is None,
                        r.get(column) if r.get(column) is not None else 0,
                    ),
                    reverse=desc,
                )
            if query.range_:
                start, end = query.range_
                selected = selected[start : end + 1]
            if query.limit_ is not None:
                selected = selected[: query.limit_]
            return Result([self._project(r, query.columns) for r in selected])

        if query.action == "insert":
            payload = (
                query.payload if isinstance(query.payload, list) else [query.payload]
            )
            inserted = [self._with_defaults(dict(row)) for row in payload]
            rows.extend(inserted)
            return Result([dict(r) for r in inserted])

        if query.action == "update":
            changed = []
            for row in rows:
                if query.matches(row):
                    row.update(query.payload)
                    changed.append(dict(row))
            return Result(changed)

        if query.action == "upsert":
            payload = (
                query.payload if isinstance(query.payload, list) else [query.payload]
            )
            keys = [k.strip() for k in (query.on_conflict or "id").split(",")]
            written = []
            for new in payload:
                existing = next(
                    (r for r in rows if all(_same(r.get(k), new.get(k)) for k in keys)),
                    None,
                )
                if existing is not None:
                    existing.update(new)
                    written.append(dict(existing))
                else:
                    row = self._with_defaults(dict(new))
                    rows.append(row)
                    written.append(dict(row))
            return Result(written)

        if query.action == "delete":
            removed = [r for r in rows if query.matches(r)]
            self.tables[query.table] = [r for r in rows if not query.matches(r)]
            return Result([dict(r) for r in removed])

        raise ValueError(f"Unsupported action {query.action}")

    def _match_multimodal_chunks(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Same contract as the live RPC: id, composite_content and similarity only."""
        query_vector = params["query_embedding"]
        scored = []
        for row in self.tables["multimodal_chunks"]:
            if not _same(row.get("lecture_id"), params["p_lecture_id"]):
                continue
            if not row.get("embedding"):
                continue
            similarity = cosine(query_vector, row["embedding"])
            if similarity > params["match_threshold"]:
                scored.append((similarity, row))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {
                "id": row["id"],
                "composite_content": row["composite_content"],
                "similarity": round(similarity, 4),
            }
            for similarity, row in scored[: params["match_count"]]
        ]


def cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def fake_vector(text: str, dimensions: int = DIMENSIONS) -> List[float]:
    """
    A deterministic bag-of-words embedding: texts sharing words point the same way, so cosine
    similarity behaves like a real embedding model for the purposes of the tests.
    """
    vector = [0.0] * dimensions
    for word in re.findall(r"[^\W_]+", text.lower()):
        digest = hashlib.sha256(word.encode("utf-8")).digest()
        vector[int.from_bytes(digest[:4], "big") % dimensions] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class FakeLegacyGenai:
    """Stands in for the google-generativeai module that embedding_engine.get_genai returns."""

    def __init__(self, latency_seconds: float = 0.0):
        self.calls: List[Dict[str, Any]] = []
        self.errors: List[Exception] = []
        self.latency_seconds = latency_seconds
        self.dimensions = DIMENSIONS

    def embed_content(self, model, content, **kwargs):
        if self.latency_seconds:
            _real_sleep(self.latency_seconds)
        self.calls.append({"model": model, "content": content, **kwargs})
        if self.errors:
            raise self.errors.pop(0)
        texts = content if isinstance(content, list) else [content]
        vectors = [fake_vector(t, self.dimensions) for t in texts]
        return {"embedding": vectors if isinstance(content, list) else vectors[0]}

    @property
    def embedded_texts(self) -> List[str]:
        texts: List[str] = []
        for call in self.calls:
            content = call["content"]
            texts.extend(content if isinstance(content, list) else [content])
        return texts


def gemini_response(text: str = "", finish: str = "STOP", parsed: Any = None):
    """A google-genai GenerateContentResponse look-alike."""
    return SimpleNamespace(
        text=text,
        parsed=parsed,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))],
    )


class FakeGenaiClient:
    """
    Stands in for google.genai.Client. `replies` is a list of responses or exceptions, used in
    order; when it runs out, `default` (a callable taking the call kwargs) answers.
    """

    def __init__(
        self, replies: Optional[list] = None, default: Optional[Callable] = None
    ):
        self.replies = list(replies or [])
        self.default = default
        self.calls: List[Dict[str, Any]] = []
        self.models = SimpleNamespace(generate_content=self._generate_content)

    def _generate_content(self, model, contents, config=None):
        call = {"model": model, "contents": contents, "config": config}
        self.calls.append(call)
        if self.replies:
            reply = self.replies.pop(0)
        elif self.default:
            reply = self.default(call)
        else:
            reply = gemini_response("")
        if isinstance(reply, Exception):
            raise reply
        return reply
