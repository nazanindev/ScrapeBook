from __future__ import annotations
import httpx

# PoetryDB — public-domain verse. `/lines/<word>` returns whole poems containing the
# word, so it thrives on exactly the evocative/abstract topics ("fog", "rust vertigo")
# that starve the factual scrapers.
_LINES_URL = "https://poetrydb.org/lines"
_HEADERS = {"User-Agent": "ephemera/1.0 (toy project; +https://github.com/nazanindev/ephemera)"}


def _key(topic: str) -> str:
    """The most evocative token of the topic — longest word is a fine heuristic."""
    words = [w for w in topic.strip().split() if w.isalpha()]
    return max(words, key=len) if words else topic.strip()


def scrape_poetry(topic: str, max_lines: int = 6) -> list[dict]:
    key = _key(topic)
    if not key:
        return []
    try:
        resp = httpx.get(f"{_LINES_URL}/{key}", timeout=8, headers=_HEADERS)
        poems = resp.json()
    except Exception:
        return []

    # A miss returns a dict ({"status": 404, ...}); a hit returns a list of poems.
    if not isinstance(poems, list):
        return []

    kl = key.lower()
    results: list[dict] = []
    seen: set[str] = set()
    for poem in poems:
        author = (poem.get("author") or "").strip()
        for raw in poem.get("lines", []):
            line = raw.strip().strip("—-").strip()
            if not (25 <= len(line) <= 90) or kl not in line.lower():
                continue
            if line in seen:
                continue
            seen.add(line)
            results.append({
                "title": "",
                "snippet": line,
                "url": "",
                "domain": "poetrydb.org",
                "og": {"site_name": author or "poetry"},
            })
            break  # one line per poem — spread across authors, not one poem's stanza
        if len(results) >= max_lines:
            break
    return results
