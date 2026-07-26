"""Client for the walker's private memory.

What the walker generated and how each post landed lives server-side on the backend API
(never in the public repo — it holds post ids / states / note counts). This is a thin,
authenticated HTTP client plus the pure functions that turn recorded history into the
three things the picker needs: a recent-topic set (anti-repeat), soft per-mode feedback
weights, and an "interesting" ranking for the `review` surface.

Every network call degrades to a no-op/empty on failure — a flaky ledger must never sink
a generation run. It does NOT degrade silently, though: a swallowed failure here is
invisible for months and leaves the walk running open-loop (no anti-repeat, no feedback)
while still looking healthy. Every failure prints a one-line warning to stderr.
"""
from __future__ import annotations
import os
import sys
from collections import defaultdict

import httpx

_TIMEOUT = 10.0


def _warn(op: str, exc: Exception) -> None:
    """Loud enough to notice in CI logs, quiet enough never to sink a run."""
    detail = ""
    if isinstance(exc, httpx.HTTPStatusError):
        detail = f" HTTP {exc.response.status_code}: {exc.response.text[:200]}"
    print(f"  ! ledger {op} failed ({type(exc).__name__}){detail}", file=sys.stderr)


class Ledger:
    def __init__(self, base_url: str, secret: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.secret = (secret if secret is not None else os.getenv("LEDGER_SECRET", "")).strip()
        self._headers = {"X-Ledger-Secret": self.secret} if self.secret else {}

    @property
    def enabled(self) -> bool:
        return bool(self.secret)

    def record(self, *, topic: str, mode: str = "", source: str = "", shape: str = "",
               components=(), tags=(), post_id=None, state=None, notes=None) -> dict | None:
        if not self.enabled:
            return None
        try:
            r = httpx.post(f"{self.base_url}/ledger", headers=self._headers, timeout=_TIMEOUT,
                           json={"topic": topic, "mode": mode, "source": source, "shape": shape,
                                 "components": list(components), "tags": list(tags),
                                 # Tumblr ids arrive as ints; the API expects a string.
                                 "post_id": None if post_id is None else str(post_id),
                                 "state": state, "notes": notes})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            _warn("record", e)
            return None

    def recent(self, n: int = 100) -> list[dict]:
        if not self.enabled:
            return []
        try:
            r = httpx.get(f"{self.base_url}/ledger/recent", params={"n": n},
                          headers=self._headers, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json().get("records", [])
        except Exception as e:
            _warn("recent", e)
            return []

    def set_fate(self, post_id, state=None, notes=None) -> int:
        if not self.enabled:
            return 0
        try:
            r = httpx.post(f"{self.base_url}/ledger/fate", headers=self._headers, timeout=_TIMEOUT,
                           json={"post_id": str(post_id), "state": state, "notes": notes})
            r.raise_for_status()
            return r.json().get("updated", 0)
        except Exception as e:
            _warn("set_fate", e)
            return 0


# ── pure derivations: records -> walk inputs ────────────────────────────────────
def recent_topics(records: list[dict]) -> frozenset[str]:
    """Lowercased topics to steer away from (anti-repeat)."""
    return frozenset(r["topic"].strip().lower() for r in records if r.get("topic"))


def _reward(record: dict) -> float:
    """How well one post landed. Publishing is the curation signal — the walk posts to
    drafts and you promote the keepers by hand — so it carries most of the weight;
    notes are a capped bonus on top."""
    reward = 1.0 if record.get("state") == "published" else 0.0
    return reward + min(record.get("notes") or 0, 20) / 20.0


def _avg_reward_by(records: list[dict], key: str) -> dict[str, float]:
    score: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    for r in records:
        bucket = r.get(key)
        if not bucket:
            continue
        count[bucket] += 1
        score[bucket] += _reward(r)
    return {b: 1.0 + score[b] / count[b] for b in count}      # 1.0 baseline + avg reward


def feedback_weights(records: list[dict]) -> dict[str, float]:
    """Soft per-mode multipliers from how each mode's posts landed. Published + engaged
    modes tilt up; the rest stay near baseline. Deliberately gentle and bounded — the
    exploration floor in the picker guarantees the space can't collapse regardless."""
    return _avg_reward_by(records, "mode")


def source_weights(records: list[dict]) -> dict[str, float]:
    """Same signal, bucketed by corpus source — lets a good source (met) outrank a
    noisy one (aic) without touching the mode mix."""
    return _avg_reward_by(records, "source")


def shape_saturation(records: list[dict], window: int = 40) -> dict[str, float]:
    """What fraction of the last `window` posts had each topic shape (1w / 2w / 3w / 4w+).

    This is the diversity signal the walk was missing. Feedback alone can only say
    "this mode lands well" — it cannot notice that nine of the last ten posts were
    two-word combos, because that sameness is spread across several modes.
    """
    shapes = [r.get("shape") for r in records[-window:] if r.get("shape")]
    if not shapes:
        return {}
    total = len(shapes)
    counts: dict[str, int] = defaultdict(int)
    for s in shapes:
        counts[s] += 1
    return {s: n / total for s, n in counts.items()}


def interesting(records: list[dict], k: int = 15) -> list[dict]:
    """Posted topics ranked by engagement then publish-state — the `review` surface."""
    posted = [r for r in records if r.get("post_id")]
    posted.sort(key=lambda r: ((r.get("notes") or 0),
                               1 if r.get("state") == "published" else 0), reverse=True)
    return posted[:k]


def breakdown(records: list[dict], key: str) -> list[dict]:
    """Per-bucket counts and outcome rates for the `metrics` surface.

    Returns rows sorted by volume: how often the walk chose each bucket, how many of
    those posts you kept, and the average engagement — i.e. what the walk is actually
    doing versus what's actually working.
    """
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        buckets[r.get(key) or "?"].append(r)
    rows = []
    for name, rs in buckets.items():
        posted = [r for r in rs if r.get("post_id")]
        published = [r for r in posted if r.get("state") == "published"]
        notes = [r.get("notes") or 0 for r in posted]
        rows.append({
            "name": name,
            "count": len(rs),
            "share": len(rs) / len(records) if records else 0.0,
            "posted": len(posted),
            "published": len(published),
            "keep_rate": len(published) / len(posted) if posted else 0.0,
            "avg_notes": sum(notes) / len(notes) if notes else 0.0,
        })
    rows.sort(key=lambda r: r["count"], reverse=True)
    return rows
