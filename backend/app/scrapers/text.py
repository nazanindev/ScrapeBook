from __future__ import annotations
import re
import httpx
from urllib.parse import urlparse, quote


def _topic_as_whole_word(topic: str, *texts: str) -> bool:
    """Return True if topic appears as a standalone word in any of the texts."""
    # Use negative lookbehind/lookahead for letters to avoid substring matches
    # e.g. "bloom" should NOT match inside "bloomberg" or "bloomtech"
    pattern = r"(?<![a-zA-Z])" + re.escape(topic) + r"(?![a-zA-Z])"
    for text in texts:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def scrape_text(topic: str, max_results: int = 60) -> list[dict]:
    results: list[dict] = []
    results.extend(_fetch_wikipedia(topic))
    results.extend(_fetch_hackernews(topic))
    results.extend(_fetch_reddit(topic))
    return results[:max_results]


def scrape_text_enriched(topic: str) -> list[dict]:
    """Phase 2 — slower, richer text sources."""
    from app.scrapers.patents import scrape_patents
    from app.scrapers.poetry import scrape_poetry
    results: list[dict] = []
    results.extend(_fetch_wikiquote(topic))
    results.extend(_fetch_ia_descriptions(topic))
    results.extend(_fetch_wikipedia_deep(topic))
    results.extend(scrape_patents(topic))
    results.extend(scrape_poetry(topic))
    return results


def scrape_ddg_text(topic: str, max_results: int = 10) -> list[dict]:
    """DDG web search text snippets — varied sources, different registers than Wikipedia/HN."""
    try:
        from duckduckgo_search import DDGS
        raw = list(DDGS(timeout=8).text(topic, max_results=max_results))
    except Exception:
        return []

    results = []
    for r in raw:
        title = (r.get("title") or "").strip()
        body = (r.get("body") or "").strip()
        url = r.get("href", "")
        domain = urlparse(url).netloc.lower().lstrip("www.")
        if not body or len(body) < 25:
            continue
        sub = [s.strip() for s in _split_sentences(body) if 25 <= len(s.strip()) <= 200]
        results.append({
            "title": title,
            "snippet": body[:300],
            "url": url,
            "domain": domain,
            "og": {"site_name": domain},
            "extra_snippets": sub[1:4],
        })
    return results


def _fetch_wikipedia(topic: str) -> list[dict]:
    try:
        resp = httpx.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": topic,
                "format": "json",
                "srlimit": 15,
                "utf8": 1,
            },
            timeout=8,
            headers={"User-Agent": "ephemera/1.0"},
        )
        items = resp.json().get("query", {}).get("search", [])
        results = []
        for item in items:
            title = item.get("title", "")
            snippet = (item.get("snippet", "")
                       .replace('<span class="searchmatch">', "")
                       .replace("</span>", ""))
            if not _topic_as_whole_word(topic, title, snippet):
                continue
            url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
            results.append({
                "title": title,
                "snippet": snippet,
                "url": url,
                "domain": "en.wikipedia.org",
                "og": {"site_name": "Wikipedia"},
            })
        return results
    except Exception:
        return []


def _fetch_hackernews(topic: str) -> list[dict]:
    try:
        resp = httpx.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": topic, "tags": "story", "hitsPerPage": 20},
            timeout=8,
        )
        results = []
        for hit in resp.json().get("hits", []):
            title = hit.get("title", "")
            if not title:
                continue
            if not _topic_as_whole_word(topic, title):
                continue
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            created = (hit.get("created_at") or "")[:10]
            results.append({
                "title": title,
                "snippet": "",
                "url": url,
                "domain": urlparse(url).netloc,
                "og": {"site_name": "Hacker News", "published_time": created},
            })
        return results
    except Exception:
        return []


def _fetch_reddit(topic: str) -> list[dict]:
    try:
        resp = httpx.get(
            "https://www.reddit.com/search.json",
            params={"q": topic, "sort": "top", "limit": 15, "t": "year"},
            timeout=8,
            headers={"User-Agent": "ephemera/1.0"},
        )
        results = []
        for child in resp.json().get("data", {}).get("children", []):
            d = child.get("data", {})
            title = d.get("title", "")
            selftext = d.get("selftext", "")[:500]
            if not _topic_as_whole_word(topic, title, selftext):
                continue
            url = d.get("url", "")
            domain = d.get("domain", urlparse(url).netloc)
            created = str(d.get("created_utc", ""))[:10]
            subreddit = d.get("subreddit", "")
            subreddit_prefixed = d.get("subreddit_name_prefixed", "")
            results.append({
                "title": title,
                "snippet": selftext,
                "url": url,
                "domain": domain,
                "subreddit": subreddit,
                "og": {"site_name": subreddit_prefixed or "Reddit", "published_time": created},
            })
        return results
    except Exception:
        return []


def _fetch_wikiquote(topic: str) -> list[dict]:
    try:
        resp = httpx.get(
            "https://en.wikiquote.org/w/api.php",
            params={
                "action": "query",
                "prop": "extracts",
                "explaintext": 1,
                "titles": topic,
                "format": "json",
            },
            timeout=8,
            headers={"User-Agent": "ephemera/1.0"},
        )
        pages = resp.json().get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {})
        if page.get("pageid", -1) == -1:
            return []
        extract = page.get("extract", "")
        lines = [l.strip() for l in extract.splitlines() if l.strip()]
        quotes = []
        for line in lines:
            if len(line) < 30 or len(line) > 220:
                continue
            if line.startswith('"') or "—" in line or " - " in line:
                quotes.append(line)
            if len(quotes) >= 5:
                break
        url = f"https://en.wikiquote.org/wiki/{quote(topic.replace(' ', '_'))}"
        return [
            {
                "title": "",
                "snippet": q,
                "url": url,
                "domain": "en.wikiquote.org",
                "og": {"site_name": "Wikiquote"},
            }
            for q in quotes
        ]
    except Exception:
        return []


def _fetch_ia_descriptions(topic: str) -> list[dict]:
    try:
        resp = httpx.get(
            "https://archive.org/advancedsearch.php",
            params={
                "q": topic,
                "fl[]": ["description", "title", "year"],
                "rows": 6,
                "output": "json",
            },
            timeout=8,
        )
        docs = resp.json().get("response", {}).get("docs", [])
        results = []
        for doc in docs:
            desc = (doc.get("description") or "").strip()
            if not desc or desc.startswith("http"):
                continue
            title = (doc.get("title") or "")
            results.append({
                "title": title,
                "snippet": desc[:300],
                "url": "https://archive.org",
                "domain": "archive.org",
                "og": {"site_name": "Internet Archive"},
            })
        return results
    except Exception:
        return []


def _fetch_wikipedia_deep(topic: str) -> list[dict]:
    """Fetch sentence-level extracts from top Wikipedia articles."""
    search_results = _fetch_wikipedia(topic)
    titles = [r["title"] for r in search_results[:3]]
    if not titles:
        return []

    results = []
    try:
        resp = httpx.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "extracts",
                "explaintext": 1,
                "exsentences": 6,
                "titles": "|".join(titles),
                "format": "json",
                "utf8": 1,
            },
            timeout=10,
            headers={"User-Agent": "ephemera/1.0"},
        )
        pages = resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            title = page.get("title", "")
            extract = page.get("extract", "")
            url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
            sentences = _split_sentences(extract)
            good = [s for s in sentences if _is_interesting_sentence(s)]
            if good:
                results.append({
                    "title": "",
                    "snippet": "",
                    "url": url,
                    "domain": "en.wikipedia.org",
                    "og": {"site_name": "Wikipedia"},
                    "extra_snippets": good[:4],
                })
    except Exception:
        pass
    return results


def _split_sentences(text: str) -> list[str]:
    import re
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def _is_interesting_sentence(s: str) -> bool:
    if len(s) < 25 or len(s) > 300:
        return False
    words = s.split()
    if len(words) < 3:
        return False
    # Drop sentences that are mostly proper nouns (>60% capitalized words)
    cap_count = sum(1 for w in words if w and w[0].isupper())
    if cap_count / len(words) > 0.6:
        return False
    return True
