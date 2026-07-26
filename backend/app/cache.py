import json
import os
import uuid
import redis

_client: redis.Redis | None = None

COLLAGE_TTL = 3600  # 1 hour
JOB_TTL = 7200      # 2 hours

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _client


def set_job(job_id: str, data: dict) -> None:
    get_client().setex(f"job:{job_id}", JOB_TTL, json.dumps(data))


def get_job(job_id: str) -> dict | None:
    raw = get_client().get(f"job:{job_id}")
    return json.loads(raw) if raw else None


def set_collage(job_id: str, data: dict) -> None:
    get_client().setex(f"collage:{job_id}", COLLAGE_TTL, json.dumps(data))


def get_collage(job_id: str) -> dict | None:
    raw = get_client().get(f"collage:{job_id}")
    return json.loads(raw) if raw else None


def _topic_key(topic: str, density: str | None, layout_seed: int | None = None) -> str:
    seed_part = "auto" if layout_seed is None else str(layout_seed)
    return f"topic:{topic}:{density or 'auto'}:{seed_part}"


def get_cached_collage_id(topic: str, density: str | None = None, layout_seed: int | None = None) -> str | None:
    return get_client().get(_topic_key(topic, density, layout_seed))


def set_topic_cache(topic: str, job_id: str, density: str | None = None, layout_seed: int | None = None) -> None:
    get_client().setex(_topic_key(topic, density, layout_seed), COLLAGE_TTL, job_id)


# ── ledger: durable (NO TTL) private memory for the walker ─────────────────────
# Stored as a hash (id -> json record) plus a list preserving insertion order.
# Unlike the collage/job caches above, these keys never expire.
_LEDGER_RECORDS = "ledger:records"
_LEDGER_ORDER = "ledger:order"


def ledger_append(record: dict) -> dict:
    rid = record.get("id") or str(uuid.uuid4())
    record["id"] = rid
    c = get_client()
    c.hset(_LEDGER_RECORDS, rid, json.dumps(record))
    c.rpush(_LEDGER_ORDER, rid)
    return record


def ledger_recent(n: int = 50) -> list[dict]:
    c = get_client()
    ids = c.lrange(_LEDGER_ORDER, -n, -1)
    if not ids:
        return []
    return [json.loads(r) for r in c.hmget(_LEDGER_RECORDS, ids) if r]


def ledger_update_fate(post_id: str, patch: dict) -> int:
    """Patch fate fields (state, notes) on every record with this Tumblr post id."""
    c = get_client()
    updated = 0
    for rid in c.lrange(_LEDGER_ORDER, 0, -1):
        raw = c.hget(_LEDGER_RECORDS, rid)
        if not raw:
            continue
        rec = json.loads(raw)
        if str(rec.get("post_id")) == str(post_id):
            rec.update({k: v for k, v in patch.items() if v is not None})
            c.hset(_LEDGER_RECORDS, rid, json.dumps(rec))
            updated += 1
    return updated
