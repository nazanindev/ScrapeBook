from __future__ import annotations
import re

import httpx

from app.pipeline.vibe import classify_vibe

# Fixed on every post: identity + the discovery communities we want to be found in.
BRAND_TAGS = ["ephemera", "collage", "digitalcollage", "webweaving"]

# substring found in a fragment's source_domain -> the source label we tag.
_DOMAIN_SOURCES = [
    ("wikipedia", "wikipedia"),
    ("wikimedia", "wikimedia"),
    ("wikiquote", "wikiquote"),
    ("reddit", "reddit"),
    ("ycombinator", "hacker news"),
    ("musicbrainz", "musicbrainz"),
    ("patents.google", "patents"),
    ("archive.org", "internet archive"),
    ("poetrydb", "poetry"),
]

# image_source field -> the source label we tag (nicer than the raw slug).
_IMAGE_SOURCES = {"artic": "art institute"}

_YEAR_RE = re.compile(r"\b(1[89]\d\d|20[0-2]\d)\b")
_CANVAS_BG = (237, 229, 216)  # the cream background; excluded from palette analysis
_TEXT_TYPES = {"headline", "snippet", "metadata"}


def vibe_band(vibe: float) -> str:
    if vibe < 0.40:
        return "sparse"
    if vibe > 0.60:
        return "dense"
    return "neutral-zone"


def _seed_hex(collage: dict) -> str:
    seed = collage.get("layout_seed")
    if seed is None:
        seed = collage.get("seed")
    return f"{seed:08x}" if isinstance(seed, int) else "—"


def lab_line(topic: str, collage: dict, density: str | None) -> str:
    """Data readout — ends at fragment count. No source counts (tags), no prose."""
    vibe = classify_vibe(topic)
    n = len(collage.get("fragments", []))
    return f"vibe {vibe:.2f} · {density or 'auto'} · seed {_seed_hex(collage)} · {n} fragments"


# ── tag axes ────────────────────────────────────────────────────────────────

def collage_sources(collage: dict) -> list[str]:
    """Every distinct content source present in the collage."""
    found: set[str] = set()
    for f in collage.get("fragments", []):
        if f.get("type") == "archive_screenshot":
            found.add("wayback machine")
        src = f.get("image_source")
        if src:
            found.add(_IMAGE_SOURCES.get(src, src))
        dom = (f.get("source_domain") or "").lower()
        for needle, label in _DOMAIN_SOURCES:
            if needle in dom:
                found.add(label)
                break
    return sorted(found)


def _years(topic: str) -> set[int]:
    """Only the topic's own year(s) — the one intentional era signal.

    Skips fragment years entirely: text years are article publication dates and
    archive years are Wayback capture dates, neither of which describe the subject.
    """
    return {int(y) for y in _YEAR_RE.findall(topic)}


def _era(year: int) -> str:
    if year < 1901:
        return "victorian"
    if year <= 1945:
        return "early 20th century"
    if year <= 1970:
        return "midcentury"
    if year <= 2000:
        return "late 20th century"
    return "21st century"


def _time_tags(topic: str) -> list[str]:
    years = _years(topic)
    if not years:
        return []
    tags = [f"{(y // 10) * 10}s" for y in sorted({(y // 10) * 10 for y in years})[:2]]
    tags.append(_era(min(years)))
    return tags


def _composition_tags(collage: dict) -> list[str]:
    frags = collage.get("fragments", [])
    has_text = any(f.get("type") in _TEXT_TYPES for f in frags)
    tags = ["with-text" if has_text else "image-only"]
    if any(f.get("type") == "archive_screenshot" for f in frags):
        tags.append("with-archive")
    return tags


def _shape_tags(topic: str) -> list[str]:
    return ["one-word" if len(topic.split()) == 1 else "multi-word"]


def palette_tags(image_path: str | None) -> list[str]:
    """Warmth / saturation / brightness of the actual imagery (background excluded)."""
    if not image_path:
        return []
    try:
        from PIL import Image
        im = Image.open(image_path).convert("RGB")
    except Exception:
        return []
    im.thumbnail((90, 124))
    rs = gs = bs = sat = 0.0
    n = 0
    for r, g, b in im.getdata():
        if abs(r - _CANVAS_BG[0]) < 22 and abs(g - _CANVAS_BG[1]) < 22 and abs(b - _CANVAS_BG[2]) < 22:
            continue  # skip cream background
        rs += r; gs += g; bs += b; n += 1
        mx, mn = max(r, g, b), min(r, g, b)
        sat += 0.0 if mx == 0 else (mx - mn) / mx
    if n < 40:
        return []
    ar, ag, ab, asat = rs / n, gs / n, bs / n, sat / n
    bright, warmth = (ar + ag + ab) / 3, ar - ab
    tags = ["warm" if warmth > 14 else "cool" if warmth < -6 else "neutral-tone"]
    if asat < 0.16:
        tags.append("sepia" if warmth > 12 else "monochrome")
    elif asat > 0.42:
        tags.append("vivid")
    if bright < 95:
        tags.append("dark")
    elif bright > 182:
        tags.append("bright")
    return tags


# ── content-aware tags: ask Wikipedia what the subject actually IS ────────────
_API_URL = "https://en.wikipedia.org/w/api.php"
_WIKI_UA = "ephemera/1.0 (ephemera tumblr bot; +https://github.com/nazanindev/ephemera)"
_ANY_YEAR_RE = re.compile(r"\b(1\d{3}|20[0-2]\d)\b")  # 1000–2029, for founding years
_TYPE_STOP = {"the", "a", "an", "of", "and", "or", "former", "small", "large"}


def _era_broad(year: int) -> str:
    if year < 500:
        return "ancient"
    if year < 1500:
        return "medieval"
    if year < 1800:
        return "early modern"
    if year < 1900:
        return "19th century"
    if year < 2001:
        return "20th century"
    return "21st century"


def _wiki_data(topic: str) -> dict | None:
    """Wikipedia page metadata: Wikidata description, categories, coordinates, intro."""
    try:
        r = httpx.get(_API_URL, params={
            "action": "query", "format": "json", "redirects": "1",
            "titles": topic.strip(),
            "prop": "description|categories|coordinates|extracts",
            "exintro": "1", "explaintext": "1", "cllimit": "30", "clshow": "!hidden",
        }, timeout=10, headers={"User-Agent": _WIKI_UA})
        pages = r.json().get("query", {}).get("pages", {})
    except Exception:
        return None
    page = next(iter(pages.values()), None) if pages else None
    if not page or "missing" in page:
        return None
    return page


def semantic_tags(topic: str) -> list[str]:
    """Place / subject-type / founding-year, mined from the topic's Wikipedia article.

    The Wikidata one-liner ("castle in Scotland", "1962 film") gives type + place;
    the extract gives the founding year. Real subjects (the wander feed) get rich
    tags; curated combo-topics 404 and return [].
    """
    page = _wiki_data(topic)
    if not page:
        return []
    desc = (page.get("description") or "").strip().lower()
    extract = page.get("extract") or ""
    cats = [c["title"].split(":", 1)[-1].lower() for c in page.get("categories", [])]
    if desc == "topics referred to by the same term" or any("disambiguation" in c for c in cats):
        return []

    tags: list[str] = []
    if desc and len(desc) <= 60:
        head = desc
        if " in " in desc:
            head, _, where = desc.partition(" in ")
            where = where.strip()
            if not re.fullmatch(r"\d{3,4}", where.split(",")[0].strip()):  # "in 1612" is a date, not a place
                parts = [p.strip().removeprefix("the ") for p in re.split(r"[,(/]", where) if p.strip()]
                if parts:
                    place = parts[-1]
                    if len(place) > 24 and place.split():  # long phrase -> the country word
                        place = place.split()[-1]
                    tags.append(place)
                    if len(parts) >= 2 and 2 < len(parts[0]) <= 20:
                        tags.append(parts[0])               # sub-region
        head = head.split(" by ")[0]                        # drop "by <author/director>"
        words = [w for w in re.findall(r"[a-z]+", head) if w not in _TYPE_STOP]
        if words and len(words[-1]) > 2:
            tags.append(words[-1])                           # subject type (castle/river/painter/film)
    if page.get("coordinates"):
        tags.append("place")

    # year: a birth/establishment category (reliable, present even w/o description)
    # wins; then the description's year; then the extract's earliest.
    cat_years = []
    for ct in cats:
        if any(k in ct for k in ("births", "establishments", "completions", "openings")):
            m = _ANY_YEAR_RE.search(ct)
            if m:
                cat_years.append(int(m.group(0)))
    desc_years = [int(y) for y in _ANY_YEAR_RE.findall(desc)]
    ext_years = [int(y) for y in _ANY_YEAR_RE.findall(extract) if 1000 <= int(y) <= 2026]
    year = (min(cat_years) if cat_years else
            desc_years[0] if desc_years else
            min(ext_years) if ext_years else None)
    if year and 1000 <= year <= 2026:
        tags += [f"{(year // 10) * 10}s", _era_broad(year)]
    return [t for t in tags if 2 < len(t) <= 24]


def build_tags(topic, collage, density, experiment, meta_topics, image_path=None, extra_tags=()) -> list[str]:
    """Rich, navigational tag set — the blog's whole index lives here."""
    band = density or vibe_band(classify_vibe(topic))
    core = list(BRAND_TAGS)
    if experiment is not None and experiment.tag:
        core.append(experiment.tag)
    if experiment is None or experiment.tag != "drift":
        core.extend(semantic_tags(topic))  # place/subject/year: useful for concrete subjects, noise on drift
    core.extend(meta_topics or ())
    core.extend(t.strip().lower().replace(" ", "-") for t in extra_tags if t)  # topic components: still-life, fog
    core.append(band)

    axes = _time_tags(topic) + palette_tags(image_path) \
        + _composition_tags(collage) + _shape_tags(topic)

    sources = collage_sources(collage)
    if len(sources) >= 4:
        axes.append("multi-source")

    ordered = core + axes + [topic.strip().lower()] + sources
    seen: set[str] = set()
    out = [t for t in ordered if t and not (t in seen or seen.add(t))]
    return out[:28]  # Tumblr's per-post ceiling is ~30


def build_caption(topic, collage, density, experiment=None, meta_topics=(), image_path=None, extra_tags=()) -> tuple[str, list[str]]:
    caption = f'"{topic}"\n{lab_line(topic, collage, density)}'
    return caption, build_tags(topic, collage, density, experiment, meta_topics, image_path, extra_tags)
