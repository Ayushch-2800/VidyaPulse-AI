import fakeredis
import pytest

import cache


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(cache.time, "monotonic", fake)
    return fake


def test_normalize_and_hash_ignore_case_and_spacing():
    assert cache.normalize_text("  What IS   a\nVector? ") == "what is a vector?"
    assert cache.text_hash("What is a vector?") == cache.text_hash(
        " what is  a VECTOR? "
    )
    assert cache.text_hash("What is a vector?") != cache.text_hash("What is a matrix?")
    assert cache.normalize_text(None) == ""


def test_memory_cache_expires_entries(clock):
    memory = cache.MemoryCache()
    memory.set("a", "1", ttl=10)
    memory.set("forever", "2", ttl=None)
    assert memory.get("a") == "1"
    clock.now += 11
    assert memory.get("a") is None
    assert memory.get("forever") == "2"
    assert memory.get("missing") is None


def test_memory_cache_evicts_least_recently_used():
    memory = cache.MemoryCache(max_items=2)
    memory.set("a", "1", 60)
    memory.set("b", "2", 60)
    memory.get("a")  # "b" is now the oldest
    memory.set("c", "3", 60)
    assert memory.get("b") is None
    assert memory.get("a") == "1" and memory.get("c") == "3"


def test_memory_counters_survive_eviction_and_clear_resets():
    memory = cache.MemoryCache(max_items=1)
    assert memory.incr("version") == 1
    memory.set("x", "1", 60)
    memory.set("y", "2", 60)
    assert memory.get_counter("version") == 1
    memory.clear()
    assert memory.get_counter("version") == 0 and memory.get("y") is None


def test_json_round_trip_and_stats(fresh_cache):
    assert cache.get_json("k") is None
    cache.set_json("k", {"vector": [0.1, 0.2], "text": "धन्यवाद"}, ttl=60)
    assert cache.get_json("k") == {"vector": [0.1, 0.2], "text": "धन्यवाद"}
    stats = cache.stats()
    assert stats == {
        "backend": "memory",
        "enabled": True,
        "hits": 1,
        "misses": 1,
        "hit_rate": 0.5,
    }
    cache.reset_stats()
    assert cache.stats()["hit_rate"] is None


def test_zero_ttl_and_disabled_block_skip_the_cache():
    cache.set_json("never", 1, ttl=0)
    assert cache.get_json("never") is None
    cache.set_json("k", 1, ttl=60)
    with cache.disabled():
        assert cache.get_json("k") is None
        cache.set_json("other", 2, ttl=60)
    assert cache.get_json("k") == 1
    assert cache.get_json("other") is None


def test_corrupt_entry_reads_as_a_miss():
    cache.get_backend().set("bad", "{not json", 60)
    assert cache.get_json("bad") is None


def test_invalidating_a_lecture_changes_its_keys():
    first = cache.lecture_key("answer", "lec-1", "q")
    assert first == "answer:lec-1:v0:q"
    cache.invalidate_lecture("lec-1")
    assert cache.lecture_key("answer", "lec-1", "q") == "answer:lec-1:v1:q"
    assert cache.lecture_key("answer", "lec-2", "q") == "answer:lec-2:v0:q"


def test_redis_backend_round_trip_with_prefix():
    client = fakeredis.FakeRedis()
    redis_cache = cache.RedisCache("redis://unused", client=client)
    cache.configure(redis_cache)

    cache.set_json("embedding:abc", [1.0, 2.0], ttl=60)
    assert cache.get_json("embedding:abc") == [1.0, 2.0]
    assert client.ttl("vidyapulse:embedding:abc") > 0
    cache.invalidate_lecture("lec")
    cache.invalidate_lecture("lec")
    assert cache.lecture_version("lec") == 2
    assert cache.stats()["backend"] == "redis"

    redis_cache.clear()
    assert client.keys("vidyapulse:*") == []


class BrokenRedis:
    def __init__(self):
        self.calls = 0

    def _fail(self, *args, **kwargs):
        self.calls += 1
        raise ConnectionError("Connection refused")

    get = set = incr = scan_iter = delete = _fail


def test_redis_outage_falls_back_to_memory_then_retries(clock, capsys):
    broken = BrokenRedis()
    redis_cache = cache.RedisCache("redis://down", client=broken)
    cache.configure(redis_cache)

    cache.set_json("k", "v", ttl=60)  # Redis fails, the memory fallback keeps it
    assert cache.get_json("k") == "v"
    assert broken.calls == 1  # Redis isn't retried during the cool-down
    assert cache.lecture_version("lec") == 0
    cache.invalidate_lecture("lec")
    assert cache.lecture_version("lec") == 1
    redis_cache.clear()
    assert "Redis is unreachable" in capsys.readouterr().out

    clock.now += cache.REDIS_RETRY_SECONDS + 1
    assert (
        cache.get_json("k") is None
    )  # Redis tried again, fails again: a miss, no error
    assert broken.calls == 2


def test_get_backend_picks_redis_from_env(monkeypatch):
    import redis

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(
        redis.Redis,
        "from_url",
        classmethod(lambda cls, url, **kw: fakeredis.FakeRedis()),
    )
    cache.configure(None)
    assert isinstance(cache.get_backend(), cache.RedisCache)


def test_get_backend_without_redis_url_is_memory(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    cache.configure(None)
    assert isinstance(cache.get_backend(), cache.MemoryCache)


def test_get_backend_survives_a_bad_redis_setup(monkeypatch):
    import redis

    def explode(cls, url, **kwargs):
        raise ValueError("bad url")

    monkeypatch.setenv("REDIS_URL", "not-a-url")
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(explode))
    cache.configure(None)
    assert isinstance(cache.get_backend(), cache.MemoryCache)
