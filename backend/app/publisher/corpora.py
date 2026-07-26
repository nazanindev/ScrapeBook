"""Exogenous entropy for the walker — evocative, pre-composed material from OUTSIDE
the loop.

The old walker recombined ~150 hand-typed words through a handful of fixed grammars,
so it repeated its own structures. The fix isn't a bigger word bank; it's an unbounded
source whose *distribution is already evocative*. Museum cataloguers and poets did the
aesthetic filtering for us — we sample their labor.

Hard rule: never harvest from our own scraper output. Topic -> collage -> fragments ->
new topic is a closed loop that collapses (and a page only yields ~60 fragments anyway).
Every source here is external, and the text corpora are fed FIXED neutral seeds that
never come from our topic history, so the harvest stays exogenous.

Two products, cached to disk so we don't hit the network on every pick:
  - phrases: coherent noun-phrases lifted from titles, in two shapes (see below)
  - words:   single salient words mined from the same material

On phrase SHAPE — this is the thing that decides whether the feed feels alive. Splitting
titles only at connectors yields nothing but two-word chunks ("mirror case", "royal
carpet"), and a feed of those reads as arbitrary noun-noun collisions no matter how good
the source is. The relation a cataloguer composed lives IN the connectors:

    "Mirror Case with a Couple Playing Chess"  ->  tight:    mirror case
                                                  composed: mirror case with a couple

So we extract both: tight connector-free runs AND composed spans that keep their
connectors. Composed spans are what stop the walk collapsing into two-word combos.
"""
from __future__ import annotations
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

_HEADERS = {"User-Agent": "ephemera/1.0 (toy project; +https://github.com/nazanindev/ephemera)"}
_CACHE_PATH = Path(__file__).with_name("corpus_cache.json")

# Keyless museum endpoints. AIC and Cleveland return titles inline (cheap); the Met needs
# one round trip per object (kept small — refresh is occasional).
#
# AIC is queried through /artworks/search filtered to public-domain ARTWORKS. The plain
# /artworks listing is paged over the whole catalogue, most of which is archival finding
# aids ("Daniel H. Burnham Collection", "C. William Brubaker Papers") — real titles, but
# a firehose of personal names that poisoned the pool with proper-noun junk.
_AIC_SEARCH = "https://api.artic.edu/api/v1/artworks/search"
_MET_SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1/search"
_MET_OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects"
_CMA_URL = "https://openaccess-api.clevelandart.org/api/artworks/"

# Fixed, generic seeds for the text corpora. Broad nets to pull varied verse/patents —
# deliberately NOT drawn from our topic history (that would close the loop).
_TEXT_SEEDS = ["light", "machine", "water", "flower", "hand", "night", "glass",
               "bird", "iron", "smoke", "star", "root", "clock", "mirror", "tide"]

# Words that break a phrase into chunks — a lifted phrase never spans one of these.
CONNECTORS = {"the", "a", "an", "and", "or", "of", "with", "for", "from", "in", "on",
               "at", "to", "by", "into", "over", "under", "near", "his", "her", "their",
               "off", "against", "upon", "within", "without", "beneath", "below",
               "above", "beside", "between", "through", "across", "along", "around",
               "behind", "beyond", "among", "amid", "toward", "towards", "onto", "about"}

# Gallery/catalog boilerplate — real words, but dead (or grammar-breaking) as topics.
# Three kinds: cataloguing nouns, the participles/verbs that leave phrases reading like
# a museum caption ("depicting a...", "they danced") rather than a composed image, and
# archival finding-aid nouns that mark a title as a records box rather than an object.
_BOILERPLATE = {"untitled", "plate", "recto", "verso", "fig", "sheet", "album", "page",
                "no", "number", "part", "view", "copy", "after", "attributed", "style",
                "manner", "circle", "workshop", "unknown", "various", "artist", "maker",
                "depicting", "showing", "representing", "seated", "standing", "holding",
                "wearing", "dressed", "carved", "before", "presumed", "probably", "possibly",
                "danced", "they", "family", "portrait", "study", "design", "fragment",
                "collection", "papers", "records", "scrapbook", "documentation",
                "microfilm", "inc", "ltd", "jr", "sr", "esq"}

# Composed-span limits. Kept tight: the topic still has to retrieve on the scrapers, and
# a six-word title returns nothing. 2-4 content words with their connectives is the band
# where a phrase reads as composed but still pulls fragments.
_SPAN_MIN_CONTENT = 2
_SPAN_MAX_CONTENT = 4
_SPAN_MAX_CONNECTORS = 2
_SPAN_MAX_CHARS = 40
_SPANS_PER_SEGMENT = 2

# Titles carry provenance after a comma ("Big River, from the Rancherie, Mendocino,
# California") and quoted series names. Neither belongs in a lifted phrase.
_DROP_PARENS = re.compile(r"\(.*?\)")
_DROP_QUOTED = re.compile(r"[\"“”'’]{1}[^\"“”]{0,60}[\"“”]{1}")
_SEGMENT_SPLIT = re.compile(r"[,;:•|/]|\s[—–]\s")


@dataclass
class Corpus:
    """The cached entropy pools. `by_source` keeps provenance so `steer` can bias
    toward a source (e.g. --toward met) without re-fetching."""
    phrases: list[str] = field(default_factory=list)
    words: list[str] = field(default_factory=list)
    by_source: dict[str, list[str]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.phrases or self.words)


# ── extraction: raw title/line -> coherent phrases + salient words ────────────────
def _segments(title: str) -> list[list[str]]:
    """Split a title into comma-free segments of lowercased tokens, connectors KEPT.

    "Mirror Case with a Couple Playing Chess"
        -> [["mirror", "case", "with", "a", "couple", "playing", "chess"]]
    """
    t = _DROP_QUOTED.sub(" ", title)
    t = _DROP_PARENS.sub(" ", t.lower())         # drop parentheticals: "(recto)"
    out: list[list[str]] = []
    for seg in _SEGMENT_SPLIT.split(t):
        seg = re.sub(r"[^a-z'\s-]", " ", seg)    # drop digits + remaining punctuation
        toks: list[str] = []
        for tok in seg.split():
            tok = tok.strip("'-")
            # apostrophe survivors are possessives/contractions — nearly always
            # proper-name noise ("vulcan's", "ingres's"); break the segment there.
            if not tok or "'" in tok:
                if toks:
                    out.append(toks)
                    toks = []
                continue
            toks.append(tok)
        if toks:
            out.append(toks)
    return out


def _is_content(tok: str) -> bool:
    return tok not in CONNECTORS and len(tok) >= 3


def _tight_runs(seg: list[str]) -> list[list[str]]:
    """Runs of content words, breaking at connectors — the original 2-3 word chunks."""
    runs, cur = [], []
    for tok in seg:
        if _is_content(tok):
            cur.append(tok)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def _composed_spans(seg: list[str]) -> list[str]:
    """Spans that KEEP their connectors, so the composed relation survives.

    Anchored at each content word and extended greedily to the limits; a span must
    start and end on content and contain at least one connector, which is precisely
    what distinguishes "mirror case with a couple" from a bare noun-noun pair.
    """
    spans: list[str] = []
    for i, tok in enumerate(seg):
        # Anchor only at a natural phrase boundary — the start of the segment, or the
        # word after a connector. Anchoring mid-noun-phrase yields sliced-open spans
        # ("case with a couple playing chess" out of "Mirror Case with a Couple...").
        if not _is_content(tok) or (i and _is_content(seg[i - 1])):
            continue
        span, content, last_content = [], 0, -1
        for j in range(i, len(seg)):
            t = seg[j]
            if _is_content(t):
                if content == _SPAN_MAX_CONTENT:
                    break
                content += 1
                last_content = len(span)
            else:
                if _connectors(span) == _SPAN_MAX_CONNECTORS or content == 0:
                    break
            span.append(t)
            if len(" ".join(span)) > _SPAN_MAX_CHARS:
                break
        span = span[:last_content + 1]           # always end on a content word
        # If the word after the span is more CONTENT, we cut inside a noun phrase and
        # the span ends on a dangling modifier ("water ewer for rituals with incised");
        # drop that word. If the next word is a CONNECTOR, the phrase completed at a
        # natural boundary ("storage jar with horizontal bands") — leave it alone.
        after = i + last_content + 1
        if after < len(seg) and _is_content(seg[after]):
            span = _drop_last_content(span)
        text = " ".join(span)
        if (_connectors(span) and _content_count(span) >= _SPAN_MIN_CONTENT
                and len(text) <= _SPAN_MAX_CHARS
                and not any(w in _BOILERPLATE for w in span)):
            spans.append(text)
        if len(spans) >= _SPANS_PER_SEGMENT:
            break
    return spans


def _connectors(span: list[str]) -> int:
    return sum(1 for t in span if not _is_content(t))


def _content_count(span: list[str]) -> int:
    return sum(1 for t in span if _is_content(t))


def _drop_last_content(span: list[str]) -> list[str]:
    """Remove the trailing content word, then any connectors it left dangling."""
    while span and not _is_content(span[-1]):
        span = span[:-1]
    if span:
        span = span[:-1]
    while span and not _is_content(span[-1]):
        span = span[:-1]
    return span


def _extract(title: str, exclude: frozenset[str] = frozenset()) -> tuple[list[str], set[str]]:
    """Return (phrases, words) for one title.

    Phrases come in both shapes — tight connector-free runs and composed connector-keeping
    spans. `exclude` drops tokens belonging to the record's own creator, which is what
    keeps artist names ("miriam hopkins", "louis betts") out of the pool.
    """
    phrases: list[str] = []
    words: set[str] = set()
    for seg in _segments(title):
        if exclude and any(t in exclude for t in seg):
            continue                              # creator name leaked into the title
        for run in _tight_runs(seg):
            run = [w for w in run if w not in _BOILERPLATE]
            for w in run:
                if len(w) >= 4:
                    words.add(w)
            if 2 <= len(run) <= 3:
                phrase = " ".join(run)
                if len(phrase) <= 30:
                    phrases.append(phrase)
        phrases.extend(_composed_spans(seg))
    return phrases, words


def _name_tokens(name: str | None) -> frozenset[str]:
    """Lowercased tokens of a creator name, for suppressing proper nouns."""
    if not name:
        return frozenset()
    return frozenset(t for t in re.sub(r"[^a-z\s]", " ", name.lower()).split() if len(t) >= 3)


# ── sources (all keyless; every fetch degrades to [] on any failure) ──────────────
# Each returns (title, creator) pairs — the creator is used only to suppress its own
# tokens from the harvest, never stored.
def _fetch_aic(rng: random.Random, pages: int = 4, per_page: int = 100) -> list[tuple[str, str]]:
    """Public-domain artworks only — see the note by _AIC_SEARCH."""
    out: list[tuple[str, str]] = []
    try:
        for page in rng.sample(range(1, 60), k=pages):
            resp = httpx.get(
                _AIC_SEARCH,
                params={"query[term][is_public_domain]": "true",
                        "fields": "title,artist_title", "limit": per_page, "page": page},
                timeout=15, headers=_HEADERS,
            )
            if resp.status_code != 200:
                continue
            for art in resp.json().get("data", []):
                t = (art.get("title") or "").strip()
                if t:
                    out.append((t, art.get("artist_title") or ""))
    except Exception:
        pass
    return out


def _fetch_met(rng: random.Random, seeds: int = 3, per_seed: int = 15) -> list[tuple[str, str]]:
    """The Met, sampled across SEVERAL seeds — one seed per refresh made this source
    contribute a couple dozen phrases all clustered on one theme."""
    out: list[tuple[str, str]] = []
    for seed in rng.sample(_TEXT_SEEDS, k=min(seeds, len(_TEXT_SEEDS))):
        try:
            r = httpx.get(_MET_SEARCH, params={"q": seed, "hasImages": "true"},
                          timeout=15, headers=_HEADERS)
            ids = r.json().get("objectIDs") or []
            for oid in rng.sample(ids, k=min(per_seed, len(ids))):
                try:
                    obj = httpx.get(f"{_MET_OBJECT}/{oid}", timeout=10, headers=_HEADERS).json()
                    t = (obj.get("title") or "").strip()
                    if t:
                        out.append((t, obj.get("artistDisplayName") or ""))
                except Exception:
                    continue
        except Exception:
            continue
    return out


def _fetch_cma(rng: random.Random, pages: int = 3, per_page: int = 100) -> list[tuple[str, str]]:
    """Cleveland Museum of Art open access — keyless, and its object titles are unusually
    well composed ("Mirror Case with a Couple Playing Chess").

    This replaces the patents harvester: PatentsView retired the keyless endpoint and
    `search.patentsview.org` no longer resolves, so that source silently contributed
    nothing (`patents: 0` in every cached corpus).
    """
    out: list[tuple[str, str]] = []
    for skip in rng.sample(range(0, 8000, per_page), k=pages):
        try:
            resp = httpx.get(
                _CMA_URL,
                params={"limit": per_page, "skip": skip, "has_image": 1, "cc0": 1,
                        "fields": "title,creators"},
                timeout=20, headers=_HEADERS,
            )
            if resp.status_code != 200:
                continue
            for art in resp.json().get("data", []):
                t = (art.get("title") or "").strip()
                if not t:
                    continue
                creators = art.get("creators") or []
                name = creators[0].get("description", "") if creators else ""
                out.append((t, name))
        except Exception:
            continue
    return out


def _harvest_poetry(rng: random.Random, seeds: int = 4) -> list[str]:
    """Poem lines — mid-sentence, so we mine them for WORDS only (chunking a line into
    2-3 word 'phrases' produces grammatical fragments like 'fain would')."""
    from app.scrapers.poetry import scrape_poetry
    out: list[str] = []
    for seed in rng.sample(_TEXT_SEEDS, k=seeds):
        try:
            out += [r["snippet"] for r in scrape_poetry(seed, max_lines=6) if r.get("snippet")]
        except Exception:
            pass
    return out


# ── refresh / load ────────────────────────────────────────────────────────────────
def refresh(path: Path = _CACHE_PATH, rng: random.Random | None = None) -> Corpus:
    """Pull fresh material from every source, extract, dedup, and cache to disk.

    Museum titles feed both phrases and words; poem lines feed words only — their
    mid-sentence chunks make poor lifted phrases."""
    rng = rng or random.Random()
    title_sources = {
        "aic": _fetch_aic(rng),
        "met": _fetch_met(rng),
        "cma": _fetch_cma(rng),
    }
    by_source: dict[str, list[str]] = {}
    words: set[str] = set()
    for src, records in title_sources.items():
        src_phrases: set[str] = set()
        for title, creator in records:
            ph, ws = _extract(title, _name_tokens(creator))
            src_phrases.update(ph)
            words.update(ws)
        by_source[src] = sorted(src_phrases)

    for line in _harvest_poetry(rng):        # words only
        _, ws = _extract(line)
        words.update(ws)

    phrases = sorted({p for lst in by_source.values() for p in lst})
    corpus = Corpus(phrases=phrases, words=sorted(words), by_source=by_source)
    path.write_text(json.dumps(
        {"phrases": phrases, "words": corpus.words, "by_source": by_source}, indent=1))
    return corpus


def load(path: Path = _CACHE_PATH) -> Corpus:
    """Read the cached pools; empty Corpus if the cache is missing/unreadable."""
    try:
        d = json.loads(path.read_text())
        return Corpus(d.get("phrases", []), d.get("words", []), d.get("by_source", {}))
    except Exception:
        return Corpus()


def summary(corpus: Corpus) -> str:
    counts = ", ".join(f"{s}:{len(v)}" for s, v in corpus.by_source.items())
    composed = sum(1 for p in corpus.phrases if any(w in CONNECTORS for w in p.split()))
    return (f"{len(corpus.phrases)} phrases ({composed} composed), "
            f"{len(corpus.words)} words ({counts})")
