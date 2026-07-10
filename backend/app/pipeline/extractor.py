from __future__ import annotations
import re
from urllib.parse import urlparse
from app.models import Fragment, FragmentType

_GENERIC_SITES = {
    "wikipedia", "hacker news", "hackernews", "reddit", "youtube",
    "medium", "substack", "wordpress", "blogspot", "tumblr",
    "github", "twitter", "x.com", "quora", "pinterest",
    "internet archive", "musicbrainz", "patent", "lyrics.ovh",
}

_MB_NOISE_TAGS = {
    "united states", "united kingdom", "the netherlands", "australia",
    "canada", "germany", "france", "sweden", "norway", "ireland",
    "english", "american", "british", "australian", "european",
    "dutch", "french", "german", "italian", "spanish", "japanese",
    "portuguese", "swedish", "korean", "chinese", "russian", "polish",
    "norwegian", "danish", "finnish", "scottish", "welsh", "canadian",
    "mexican", "brazilian", "argentinian", "indian", "african",
}

_TRACKLIST_RE = re.compile(r"\*\*tracklist\*\*|\b\d+\.\s+\w.{0,40}feat\.", re.IGNORECASE)
_BROKEN_START_RE = re.compile(r"^\S*\)")


def _is_clean_content(text: str) -> bool:
    if _TRACKLIST_RE.search(text):
        return False
    if _BROKEN_START_RE.match(text):
        return False
    return True


def extract_fragments(
    images: list[dict],
    texts: list[dict],
    archive: list[dict],
    wikimedia: list[dict] | None = None,
    enriched_texts: list[dict] | None = None,
    artic: list[dict] | None = None,
) -> list[Fragment]:
    fragments: list[Fragment] = []

    for img in images:
        fragments.append(Fragment(
            type=FragmentType.image,
            content=img["url"],
            source_url=img.get("source_url", ""),
            source_domain=urlparse(img.get("source_url", "")).netloc,
            image_source="openverse",
        ))

    for img in (wikimedia or []):
        fragments.append(Fragment(
            type=FragmentType.image,
            content=img["url"],
            source_url=img.get("source_url", ""),
            source_domain=urlparse(img.get("source_url", "")).netloc,
            image_source="wikimedia",
        ))

    for img in (artic or []):
        fragments.append(Fragment(
            type=FragmentType.image,
            content=img["url"],
            source_url=img.get("source_url", ""),
            source_domain=urlparse(img.get("source_url", "")).netloc,
            image_source="artic",
        ))

    all_texts = list(texts) + list(enriched_texts or [])
    for item in all_texts:
        domain = item.get("domain", urlparse(item.get("url", "")).netloc)
        og = item.get("og", {})

        title = item.get("title", "")
        if title and _is_clean_content(title):
            fragments.append(Fragment(
                type=FragmentType.headline,
                content=title,
                source_url=item.get("url", ""),
                source_domain=domain,
                og=og,
            ))

        snippet = item.get("snippet", "")
        if snippet and _is_clean_content(snippet):
            fragments.append(Fragment(
                type=FragmentType.snippet,
                content=snippet,
                source_url=item.get("url", ""),
                source_domain=domain,
                og=og,
            ))

        for extra in item.get("extra_snippets", []):
            if extra and _is_clean_content(extra):
                fragments.append(Fragment(
                    type=FragmentType.snippet,
                    content=extra,
                    source_url=item.get("url", ""),
                    source_domain=domain,
                    og=og,
                ))

        desc = og.get("description", "")
        if desc and len(desc) > 60:
            fragments.append(Fragment(
                type=FragmentType.snippet,
                content=desc[:280],
                source_url=item.get("url", ""),
                source_domain=domain,
            ))

        fragments.extend(_extract_metadata_fragments(item, domain, og))

    for snap in archive:
        year = snap["year"]
        fragments.append(Fragment(
            type=FragmentType.archive_screenshot,
            content=snap["thumbnail_url"],
            source_url=snap["wayback_url"],
            source_domain=snap["domain"],
            captured_at=snap["timestamp"],
            og={
                "year": year,
                "original_url": snap["original_url"],
            },
        ))
        if year and str(year).isdigit() and 1900 <= int(year) <= 2030:
            fragments.append(Fragment(
                type=FragmentType.metadata,
                content=str(year),
                source_url=snap["wayback_url"],
                source_domain=snap["domain"],
            ))

    return fragments


def _extract_metadata_fragments(item: dict, domain: str, og: dict) -> list[Fragment]:
    frags = []
    url = item.get("url", "")
    emitted_subreddit = False

    # 1. Subreddit name (topical, personal)
    subreddit = item.get("subreddit", "")
    if subreddit:
        frags.append(Fragment(
            type=FragmentType.metadata,
            content=subreddit,
            source_url=url,
            source_domain=domain,
        ))
        emitted_subreddit = True

    # 2. Wikipedia categories (short, non-tracking)
    for cat in (item.get("categories") or [])[:2]:
        cat = cat.split(":")[-1].strip()
        if 8 <= len(cat) <= 35 and not any(w in cat for w in ("Wikipedia", "Articles", "pages")):
            frags.append(Fragment(
                type=FragmentType.metadata,
                content=cat,
                source_url=url,
                source_domain=domain,
            ))

    # 3. Publication year
    pub_time = og.get("published_time", "")
    if pub_time:
        year_str = str(pub_time)[:4]
        if year_str.isdigit() and 1900 <= int(year_str) <= 2030:
            frags.append(Fragment(
                type=FragmentType.metadata,
                content=year_str,
                source_url=url,
                source_domain=domain,
            ))

    # 4. Site name — only if non-generic, non-noise, and we didn't already emit a subreddit
    site_name = og.get("site_name", "")
    if site_name and not emitted_subreddit \
            and site_name.lower() not in _GENERIC_SITES \
            and site_name.lower() not in _MB_NOISE_TAGS \
            and len(site_name) > 3:
        frags.append(Fragment(
            type=FragmentType.metadata,
            content=site_name,
            source_url=url,
            source_domain=domain,
        ))

    return frags
