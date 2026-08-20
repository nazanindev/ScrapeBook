from __future__ import annotations
import httpx
from app.scrapers._filters import is_violent

# Art Institute of Chicago — a single search call returns image ids + a public-domain
# flag, so no per-object round trips. Great for abstract/surreal topics that Openverse
# and Wikipedia return nothing for.
_SEARCH_URL = "https://api.artic.edu/api/v1/artworks/search"
_IIIF_BASE = "https://www.artic.edu/iiif/2"
_HEADERS = {"User-Agent": "ephemera/1.0 (toy project; +https://github.com/nazanindev/ephemera)"}

# When a query matches nothing, AIC's search does NOT return empty — it falls back
# to match-all over the whole collection (pagination.total ≈ 132k) sorted by internal
# boost, i.e. the same dozen artworks for every weak query (Portrait of Edouard Molé
# et al. haunting every obscure topic). Real matches score ~1-100; the match-all
# noise floor is ~2.5e-05, so any sane threshold separates them cleanly.
_MIN_SCORE = 0.1


def scrape_artic(topic: str, max_results: int = 12) -> list[dict]:
    try:
        resp = httpx.get(
            _SEARCH_URL,
            params={
                "q": topic,
                "limit": 20,
                "fields": "id,title,image_id,date_display,is_public_domain",
            },
            timeout=10,
            headers=_HEADERS,
        )
        if resp.status_code != 200:
            return []
        data = resp.json().get("data", [])
    except Exception:
        return []

    results = []
    for art in data:
        if (art.get("_score") or 0) < _MIN_SCORE:
            continue
        if not art.get("is_public_domain"):
            continue
        image_id = art.get("image_id")
        if not image_id:
            continue
        title = (art.get("title") or "").strip()
        if is_violent(title):
            continue
        results.append({
            # 843-wide IIIF derivative — clears the tiny-image floor, dodges hotlink blocks
            "url": f"{_IIIF_BASE}/{image_id}/full/843,/0/default.jpg",
            "source_url": f"https://www.artic.edu/artworks/{art.get('id', '')}",
            "title": title,
            "width": 843,
            "height": 0,
        })
        if len(results) >= max_results:
            break
    return results
