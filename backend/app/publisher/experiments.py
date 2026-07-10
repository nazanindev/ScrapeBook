"""The experiment scheduler — picks what to generate and how it gets tagged.

One collage per post, always. Series and wandering happen through TAGS, not photosets.
Topics are drawn from meta-topic buckets so the meta-topic tag is known, not guessed.
Biased toward dense collages.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field

import httpx


@dataclass
class Shot:
    topic: str
    density: str | None = "dense"          # default dense; ladders/neutral use None (auto)
    layout_seed: int | None = None
    meta_topics: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()             # the topic's component parts, e.g. ("still life", "fog")


@dataclass
class Experiment:
    name: str
    tag: str
    shots: list[Shot]


# ── meta-topic buckets: bucket -> seed words (every specimen carries its bucket) ──
# Each word lives in exactly one bucket so the meta-topic tag is unambiguous.
META_TOPICS: dict[str, list[str]] = {
    "history": ["almanac", "ledger", "census", "chronicle", "gazette", "archive"],
    "nature": ["fog", "glacier", "tide", "orchard", "moth", "marsh", "moss", "frost", "estuary"],
    "science": ["observatory", "telescope", "greenhouse", "specimen", "barometer", "microscope", "herbarium"],
    "art": ["fresco", "engraving", "mosaic", "portrait", "still life", "etching", "tapestry"],
    "culture": ["carnival", "festival", "arcade", "fairground", "vaudeville", "phonograph", "sideshow", "waxworks"],
    "architecture": ["lighthouse", "aqueduct", "rotunda", "pavilion", "stairwell", "bandstand", "facade", "colonnade"],
    "transport": ["tram", "canal", "railway", "harbor", "ferry", "locomotive", "dirigible", "funicular"],
    "communication": ["telegraph", "switchboard", "telephone", "radio", "typewriter", "transmitter", "teleprinter"],
    "ritual": ["procession", "masquerade", "shrine", "pilgrimage", "maypole", "vigil", "requiem"],
    "industry": ["loom", "kiln", "foundry", "mill", "cannery", "colliery", "printing press"],
}

QUALIFIERS = [
    "at night", "in winter", "operators", "interior", "abandoned", "under snow",
    "by lamplight", "from above", "in fog", "diagram",
]
YEARS = [str(y) for y in range(1890, 1979)]
# Single words that fan out across unrelated domains (no single meta-topic).
AMBIGUOUS = [
    "mercury", "delta", "apollo", "saturn", "phoenix", "amazon", "java", "titan",
    "iris", "atlas", "nova", "echo", "vega", "orion", "sable",
]

# ── drift: evocative / polysemous / half-surreal seeds that push the system's edges ──
POLYSEMOUS = [
    "mercury", "echo", "current", "charge", "vessel", "mantle", "fault", "relay",
    "signal", "drift", "atlas", "iris", "nova", "ember", "relic", "specter",
    "mirror", "needle", "crown", "vault", "tongue", "compass", "prism", "static",
    "plate", "band", "capital", "organ", "temple", "pupil", "score", "chord",
    "wake", "spring", "grain", "circuit", "spine", "cell",
]
EVOCATIVE = [
    "vertigo", "mirage", "reverie", "oblivion", "trance", "rupture", "decay",
    "hush", "fever", "halo", "eclipse", "threshold", "undertow", "delirium",
    "longing", "aftermath", "solstice", "penumbra", "murmur", "vestige",
    "afterglow", "torpor", "swoon", "duskfall", "stupor", "hollow", "quietude",
]
MATTER = [
    "rust", "salt", "ash", "glass", "copper", "neon", "velvet", "smoke", "amber",
    "tar", "chrome", "bone", "wax", "ivory", "obsidian",
    "porcelain", "granite", "lichen", "cinder", "brass", "resin", "graphite",
    "slate", "quartz", "vellum", "silt", "coal", "soot",
]
VESSELS = [
    "cathedral", "ruin", "engine", "machine", "garden", "opera", "circus", "asylum",
    "observatory", "reliquary", "mausoleum", "carnival", "altar", "menagerie",
    "conservatory", "amphitheatre", "clocktower", "sanatorium", "planetarium",
    "aviary", "orangery", "crypt", "belfry", "granary", "arboretum", "atrium",
]


def _seed(rng: random.Random) -> int:
    return rng.randint(0, 2**31 - 1)


def _pick_meta(rng: random.Random) -> tuple[str, str]:
    """Return (meta_topic, seed_word)."""
    mt = rng.choice(list(META_TOPICS))
    return mt, rng.choice(META_TOPICS[mt])


_QUAL_PREPS = ("in ", "at ", "under ", "by ", "from ", "on ", "over ")


def _qual_tag(qual: str) -> str:
    """The taggable noun of a qualifier: 'in fog' -> 'fog', 'by lamplight' -> 'lamplight'."""
    for p in _QUAL_PREPS:
        if qual.startswith(p):
            return qual[len(p):]
    return qual


def build_specimen(rng: random.Random) -> Experiment:
    """A plain dense pull — a specimen of ordinary system behavior."""
    mt, word = _pick_meta(rng)
    topic = f"{word} {rng.choice(YEARS)}" if rng.random() < 0.5 else word
    return Experiment("specimen", "specimen",
                      [Shot(topic=topic, density="dense", meta_topics=(mt,), tags=(word,))])


def build_domain_drift(rng: random.Random) -> Experiment:
    """One ambiguous word the collage catches mid-confusion (spans meta-topics)."""
    word = rng.choice(AMBIGUOUS)
    return Experiment("domain drift", "domain-drift",
                      [Shot(topic=word, density="dense", meta_topics=(), tags=(word,))])


def build_seed_series(rng: random.Random) -> Experiment:
    """One prompt, N layout seeds — same fragments, different dice. Grouped by the topic tag."""
    mt, word = _pick_meta(rng)
    qual = rng.choice(QUALIFIERS)
    topic = f"{word} {qual}"
    parts = (word, _qual_tag(qual))
    shots = [Shot(topic=topic, density="dense", layout_seed=_seed(rng), meta_topics=(mt,), tags=parts)
             for _ in range(3)]
    return Experiment("seed series", "seed-series", shots)


def build_density_ladder(rng: random.Random) -> Experiment:
    """word -> word qual -> word qual year. Auto density so vibe climbs across the posts."""
    mt, word = _pick_meta(rng)
    qual, year = rng.choice(QUALIFIERS), rng.choice(YEARS)
    qn = _qual_tag(qual)
    rungs = [(word, (word,)),
             (f"{word} {qual}", (word, qn)),
             (f"{word} {qual} {year}", (word, qn))]
    return Experiment("density ladder", "density-ladder",
                      [Shot(topic=t, density=None, meta_topics=(mt,), tags=tg) for t, tg in rungs])


def build_neutral_zone(rng: random.Random) -> Experiment:
    """Two words from one bucket whose vibe is decided by an md5, not meaning."""
    mt = rng.choice(list(META_TOPICS))
    pair = rng.sample(META_TOPICS[mt], 2)
    return Experiment("neutral zone", "neutral-zone",
                      [Shot(topic=t, density=None, meta_topics=(mt,), tags=(t,)) for t in pair])


def build_diptych(rng: random.Random) -> Experiment:
    """Two posts from two different buckets — a cross-domain pairing under one tag.

    Unlike neutral-zone (one bucket), the two halves come from unrelated meta-topics,
    so the pair reads as a deliberate juxtaposition (industry × ritual, transport × art).
    """
    mt_a, mt_b = rng.sample(list(META_TOPICS), 2)
    word_a = rng.choice(META_TOPICS[mt_a])
    word_b = rng.choice(META_TOPICS[mt_b])
    return Experiment("diptych", "diptych", [
        Shot(topic=word_a, density="dense", meta_topics=(mt_a,), tags=(word_a,)),
        Shot(topic=word_b, density="dense", meta_topics=(mt_b,), tags=(word_b,)),
    ])


def _drift_pick(rng: random.Random) -> tuple[str, tuple[str, ...]]:
    """Return (topic, component_tags). Several grammars, none dominant."""
    r = rng.random()
    if r < 0.28:                                   # single polysemous/evocative word -> domain drift
        w = rng.choice(POLYSEMOUS + EVOCATIVE)
        return w, (w,)
    if r < 0.50:                                   # concrete matter + charged vessel
        m, v = rng.choice(MATTER), rng.choice(VESSELS)
        return f"{m} {v}", (m, v)                  # "salt cathedral", "neon circus"
    if r < 0.68:                                   # matter + evocative abstraction
        m, e = rng.choice(MATTER), rng.choice(EVOCATIVE)
        return f"{m} {e}", (m, e)                  # "rust vertigo", "amber undertow"
    if r < 0.83:                                   # polysemous noun + matter -> real-ish, still strange
        p, m = rng.choice(POLYSEMOUS), rng.choice(MATTER)
        return f"{p} {m}", (p, m)                  # "mercury glass", "signal copper"
    if r < 0.94:                                   # evocative + charged vessel
        e, v = rng.choice(EVOCATIVE), rng.choice(VESSELS)
        return f"{e} {v}", (e, v)                  # "delirium carnival", "oblivion observatory"
    m, y = rng.choice(MATTER), rng.choice(YEARS)   # matter anchored to a year -> temporal drift
    return f"{m} {y}", (m,)                        # "amber 1931" (only the matter is a tag)


def build_drift(rng: random.Random) -> Experiment:
    """The walk: evocative, polysemous, half-surreal seeds that make the system drift."""
    topic, parts = _drift_pick(rng)
    return Experiment("drift", "drift", [Shot(topic=topic, density="dense", meta_topics=(), tags=parts)])


# ── the infinite engine: random Wikipedia subjects ──────────────────────────
_WIKI_API = "https://en.wikipedia.org/w/api.php"
_WIKI_UA = "ephemera/1.0 (ephemera tumblr bot; +https://github.com/nazanindev/ephemera)"


def _good_seed(title: str) -> bool:
    """Skip titles that make poor collage prompts (disambiguation, lists, dates)."""
    if not title or len(title) > 38:
        return False
    low = title.lower()
    if "(" in title:
        return False
    if low.startswith(("list of", "index of", "outline of", "timeline of", "glossary of")):
        return False
    if sum(c.isdigit() for c in title) >= 3:  # "2007 in film", catalog numbers, dates
        return False
    return True


def random_wikipedia_topic(rng: random.Random | None = None) -> str | None:
    """A clean random Wikipedia article title — an unbounded, serendipitous seed."""
    try:
        resp = httpx.get(
            _WIKI_API,
            params={"action": "query", "list": "random", "rnnamespace": 0,
                    "rnlimit": 12, "format": "json"},
            timeout=10,
            headers={"User-Agent": _WIKI_UA},
        )
        titles = [x["title"] for x in resp.json().get("query", {}).get("random", [])]
    except Exception:
        return None
    good = [t for t in titles if _good_seed(t)]
    if good:
        return (rng or random).choice(good)
    return titles[0] if titles else None


def build_wander(rng: random.Random) -> Experiment:
    """Wander: a random Wikipedia subject — the never-repeating feed.

    Falls back to a curated dense specimen if Wikipedia is unreachable.
    """
    title = random_wikipedia_topic(rng)
    if not title:
        mt, word = _pick_meta(rng)
        return Experiment("wander", "wander", [Shot(topic=word, density="dense", meta_topics=(mt,))])
    return Experiment("wander", "wander", [Shot(topic=title, density="dense", meta_topics=())])


BUILDERS = {
    "drift": build_drift,
    "wander": build_wander,
    "specimen": build_specimen,
    "domain-drift": build_domain_drift,
    "seed-series": build_seed_series,
    "density-ladder": build_density_ladder,
    "neutral-zone": build_neutral_zone,
    "diptych": build_diptych,
}

# drift still carries the walk (pushes the system's edges), but no longer swamps the
# feed — the curated/structured builders get enough weight to break the monotony.
# wander (Wikipedia) stays available via --experiment but is out of the random feed —
# too square to govern the walk.
WEIGHTS = {
    "drift": 8,
    "specimen": 3,
    "density-ladder": 2,
    "seed-series": 2,
    "diptych": 2,
}


def build(name: str, rng: random.Random | None = None) -> Experiment:
    rng = rng or random.Random()
    if name not in BUILDERS:
        raise KeyError(f"unknown experiment {name!r}; choices: {', '.join(BUILDERS)}")
    return BUILDERS[name](rng)


def pick_experiment(rng: random.Random | None = None) -> Experiment:
    rng = rng or random.Random()
    names = list(WEIGHTS)
    name = rng.choices(names, weights=[WEIGHTS[n] for n in names], k=1)[0]
    return BUILDERS[name](rng)
