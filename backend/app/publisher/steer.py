"""The injected direction — how you push the walker without editing code.

A tiny JSON file (`direction.json`) that biases which corpus source the walk draws from
and pins seed words it should lean on. Loaded into the WalkContext at the start of each
run; edited via `publish.py steer`. Steering only *tilts* the walk — the exploration
floor still fires pure-random picks, so a direction narrows the feed without collapsing it.

This file holds preferences, not secrets (the private data is the ledger), so it's safe
to keep locally / gitignore.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path

_PATH = Path(__file__).with_name("direction.json")


@dataclass
class Direction:
    source_bias: dict[str, float] = field(default_factory=dict)  # corpus source -> weight, e.g. {"met": 2.0}
    pinned: list[str] = field(default_factory=list)              # seed words to lean on
    note: str = ""                                               # free-text reminder of intent

    def __bool__(self) -> bool:
        return bool(self.source_bias or self.pinned)


def load(path: Path = _PATH) -> Direction:
    try:
        d = json.loads(path.read_text())
        return Direction(d.get("source_bias", {}), d.get("pinned", []), d.get("note", ""))
    except Exception:
        return Direction()


def save(direction: Direction, path: Path = _PATH) -> None:
    path.write_text(json.dumps({
        "source_bias": direction.source_bias,
        "pinned": direction.pinned,
        "note": direction.note,
    }, indent=1))


def clear(path: Path = _PATH) -> None:
    save(Direction(), path)


def describe(direction: Direction) -> str:
    if not direction:
        return "no direction set (pure walk)"
    bits = []
    if direction.source_bias:
        bits.append("toward " + ", ".join(f"{s}×{w:g}" for s, w in direction.source_bias.items()))
    if direction.pinned:
        bits.append("pinned: " + ", ".join(direction.pinned))
    if direction.note:
        bits.append(f'“{direction.note}”')
    return " · ".join(bits)
