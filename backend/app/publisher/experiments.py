"""The experiment scheduler — picks what to generate and how it gets tagged.

One collage per post, always. Series and wandering happen through TAGS, not photosets.
Topics are drawn from meta-topic buckets so the meta-topic tag is known, not guessed.
Biased toward dense collages.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field

import httpx

from app.publisher.corpora import CONNECTORS, Corpus, load as load_corpus


@dataclass
class Shot:
    topic: str
    density: str | None = "dense"          # default dense; ladders/neutral use None (auto)
    layout_seed: int | None = None
    meta_topics: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()             # the topic's component parts, e.g. ("still life", "fog")
    source: str = ""                       # corpus source the topic came from (aic | met | cma)


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


# ── the walk: corpus-fed, relation-first ─────────────────────────────────────
# The old drift grammar jammed two independent random draws together ("salt vessel").
# Two orthogonal dice can only ever be arbitrary — interesting for ~10 posts, noise
# after. These modes instead LIFT pre-composed phrases (relation baked in by whoever
# named the object) or combine atoms through connective grammar, never bare noun-noun.

_CURATED_WORDS = POLYSEMOUS + EVOCATIVE + MATTER      # single-word fodder + graft swaps
_WORD_BUCKET = {w: mt for mt, ws in META_TOPICS.items() for w in ws}

# Frame templates assert a RELATION (the vessel stained BY / immersed IN the matter),
# not a collision. Kept short so the topic still retrieves on the current scrapers.
_FRAMES = ["{m}-stained {v}", "{m}-eaten {v}", "{m}-flecked {v}",
           "{v} in {m}", "{v} of {m}", "{v} under {m}"]


@dataclass
class WalkContext:
    """Everything the picker needs beyond dice. Assembled by the caller from the
    corpus (entropy), the ledger (anti-repeat + feedback), and steer (direction),
    so this module stays pure and testable — it never does I/O itself."""
    corpus: Corpus = field(default_factory=Corpus)
    recent: frozenset[str] = frozenset()            # lowercased topics to avoid
    mode_weights: dict[str, float] = field(default_factory=dict)  # feedback: mode -> multiplier
    source_weights: dict[str, float] = field(default_factory=dict)  # feedback: source -> multiplier
    shape_saturation: dict[str, float] = field(default_factory=dict)  # shape -> recent share
    source_bias: dict[str, float] = field(default_factory=dict)   # steer: corpus source -> weight
    pinned: tuple[str, ...] = ()                     # steer: seed words to lean on


def topic_shape(topic: str) -> str:
    """The topic's form: content-word count, and whether it keeps its connectives.

    "salt vessel"            -> bare-2w
    "rock of hautepierre"    -> composed-2w
    "storage jar with bands" -> composed-3w

    Shape is the axis the walk was blind to. Per-mode feedback cannot see that lift,
    graft and frame were all emitting two-word combos at once — the sameness is spread
    across modes, so only a shape bucket catches it. Bare and composed are separate
    buckets because they are what actually differ to a reader: a bare pair is two dice,
    a composed one states a relation.
    """
    words = topic.split()
    n = sum(1 for w in words if w.lower() not in CONNECTORS)
    kind = "composed" if any(w.lower() in CONNECTORS for w in words) else "bare"
    return f"{kind}-{min(n, 4)}w" + ("+" if n >= 4 else "")


def content_words(phrase: str) -> tuple[str, ...]:
    """The taggable words of a phrase — connectors make useless tags (#of, #the)."""
    return tuple(w for w in phrase.split() if w.lower() not in CONNECTORS)


def _bucket_of(word: str) -> tuple[str, ...]:
    b = _WORD_BUCKET.get(word)
    return (b,) if b else ()


def _corpus_words(ctx: WalkContext) -> list[str]:
    return ctx.corpus.words or []


def _word(rng: random.Random, ctx: WalkContext, base: list[str], pinned_p: float) -> str:
    """Draw a word, giving injected steer-seeds a strong chance so a direction is
    actually felt (but never total — the exploration floor still fires unsteered picks)."""
    if ctx.pinned and rng.random() < pinned_p:
        return rng.choice(ctx.pinned)
    return rng.choice(base or ctx.pinned or ["ephemera"])


def _pick_word(rng: random.Random, ctx: WalkContext) -> str:
    """A single evocative word: pinned steer-seeds, corpus harvest, curated pools."""
    return _word(rng, ctx, _corpus_words(ctx) + list(_CURATED_WORDS), pinned_p=0.5)


def _pick_phrase(rng: random.Random, ctx: WalkContext) -> tuple[str, str] | None:
    """A pre-composed phrase as (phrase, source), honoring steer bias AND how each
    source has been landing. None if the corpus has none."""
    srcs = [s for s, ph in ctx.corpus.by_source.items() if ph]
    if srcs:
        weights = [max(0.0, ctx.source_bias.get(s, 1.0)) * ctx.source_weights.get(s, 1.0)
                   for s in srcs]
        if sum(weights) <= 0:
            weights = [1.0] * len(srcs)
        src = rng.choices(srcs, weights=weights, k=1)[0]
        pool = ctx.corpus.by_source.get(src) or ctx.corpus.phrases
    else:
        src, pool = "", ctx.corpus.phrases
    return (rng.choice(pool), src) if pool else None


def build_single(rng: random.Random, ctx: WalkContext) -> Experiment:
    """One evocative word — the purest mode, no collision possible. Optionally + year."""
    word = _pick_word(rng, ctx)
    topic = f"{word} {rng.choice(YEARS)}" if rng.random() < 0.35 else word
    return Experiment("single", "single",
                      [Shot(topic=topic, density="dense", meta_topics=_bucket_of(word), tags=(word,))])


def build_lift(rng: random.Random, ctx: WalkContext) -> Experiment:
    """The spine: a coherent phrase lifted whole from an exogenous corpus.

    Prefers a phrase that keeps its connectors ("storage jar with horizontal bands")
    over a bare two-word chunk — the connectors carry the relation a cataloguer
    composed, which is the whole reason lifting beats recombining.
    """
    picked = _pick_phrase(rng, ctx)
    if not picked:
        return build_single(rng, ctx)               # empty/offline corpus fallback
    phrase, src = picked
    if not _is_composed(phrase):                    # one re-draw toward the richer shape
        alt = _pick_phrase(rng, ctx)
        if alt and _is_composed(alt[0]):
            phrase, src = alt
    return Experiment("lift", "lift",
                      [Shot(topic=phrase, density="dense", meta_topics=(),
                            tags=content_words(phrase), source=src)])


def build_graft(rng: random.Random, ctx: WalkContext) -> Experiment:
    """One controlled degree of surprise: lift a phrase, swap exactly one CONTENT word.

    Gated to phrases of 3+ content words. Swapping one word of a two-word phrase
    destroys half the composed relation and leaves exactly the arbitrary noun-noun
    collision this module exists to avoid — at 3+ words, enough structure survives
    for the swap to read as a mutation rather than a dice roll.
    """
    picked = _pick_phrase(rng, ctx)
    if not picked or len(content_words(picked[0])) < 3:
        return build_frame(rng, ctx)
    phrase, src = picked
    words = phrase.split()
    swappable = [i for i, w in enumerate(words) if w.lower() not in CONNECTORS]
    # Curated NOUN pools only. The corpus harvest is untyped — it's full of adjectives
    # and participles ("wild", "horned", "enthroned"), and dropping one of those into a
    # noun slot yields "crozier head with wild enthroned" rather than a mutation.
    swap_pool = list(MATTER) + list(EVOCATIVE) + list(POLYSEMOUS)
    words[rng.choice(swappable)] = _word(rng, ctx, swap_pool, pinned_p=0.4)
    topic = " ".join(words)
    return Experiment("graft", "graft",
                      [Shot(topic=topic, density="dense", meta_topics=(),
                            tags=content_words(topic), source=src)])


def _is_composed(phrase: str) -> bool:
    return any(w.lower() in CONNECTORS for w in phrase.split())


def build_frame(rng: random.Random, ctx: WalkContext) -> Experiment:
    """Combine atoms through connective grammar — a relation, not a collision.

    The material slot draws from MATTER only. Letting arbitrary corpus nouns in
    breaks the templates' semantics: "rust-eaten cathedral" states a relation,
    "menagerie under book" and "cathedral of piercing" are just two nouns colliding
    inside a preposition — the failure the frames were meant to prevent.
    """
    m = _word(rng, ctx, list(MATTER), pinned_p=0.35)
    v = rng.choice(VESSELS)
    topic = rng.choice(_FRAMES).format(m=m, v=v)
    return Experiment("frame", "frame",
                      [Shot(topic=topic, density="dense", meta_topics=(), tags=(m, v))])


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


# Curated structural builders (ctx-free) — variety that was never the "salt vessel"
# problem, so they stay. build_wander (random Wikipedia) stays available via
# --experiment but out of the random feed — too square to govern the walk.
_CURATED_BUILDERS = {
    "specimen": build_specimen,
    "domain-drift": build_domain_drift,
    "seed-series": build_seed_series,
    "density-ladder": build_density_ladder,
    "neutral-zone": build_neutral_zone,
    "diptych": build_diptych,
    "wander": build_wander,
}
# Corpus-fed walk builders (take a WalkContext).
_WALK_BUILDERS = {
    "single": build_single,
    "lift": build_lift,
    "graft": build_graft,
    "frame": build_frame,
}
BUILDERS = {**_CURATED_BUILDERS, **_WALK_BUILDERS}

# Base weights: lift is the spine; single/graft/frame carry the rest of the walk; the
# curated builders add structural variety. Feedback tilts these; the exploration floor
# ignores feedback entirely so the space can never collapse onto the optimizer.
#
# graft and frame are the two modes that BUILD a topic out of independent draws rather
# than lifting one, so they're the ones that drift toward arbitrary combos; they're held
# low and lift (now yielding composed, connector-keeping phrases) carries more.
BASE_WEIGHTS = {
    "lift": 7, "single": 4, "graft": 2, "frame": 2,
    "seed-series": 2, "density-ladder": 2, "diptych": 2, "specimen": 1, "neutral-zone": 1,
}
EXPLORATION_FLOOR = 0.4      # fraction of picks that ignore feedback (pure exploration)
_FEEDBACK_CAP = 3.0          # a mode's feedback multiplier is clamped to [0, cap]
_ANTI_REPEAT_TRIES = 6

# Shape governor. If more than this share of recent posts had a topic shape, candidates
# of that shape get resampled — the walk is allowed to favour a shape, not to collapse
# onto one. Rejection is probabilistic and proportional to the excess, so a saturated
# shape is thinned rather than banned outright.
SHAPE_CAP = 0.45
_SHAPE_MAX_REJECT = 0.8      # never reject more than this share, even at total saturation


def _build_mode(name: str, rng: random.Random, ctx: WalkContext) -> Experiment:
    if name in _WALK_BUILDERS:
        return _WALK_BUILDERS[name](rng, ctx)
    return _CURATED_BUILDERS[name](rng)


def build(name: str, rng: random.Random | None = None, ctx: WalkContext | None = None) -> Experiment:
    rng = rng or random.Random()
    if name not in BUILDERS:
        raise KeyError(f"unknown experiment {name!r}; choices: {', '.join(BUILDERS)}")
    return _build_mode(name, rng, ctx or WalkContext(corpus=load_corpus()))


def _is_repeat(exp: Experiment, recent: frozenset[str]) -> bool:
    return any(s.topic.strip().lower() in recent for s in exp.shots)


def _oversaturated(exp: Experiment, saturation: dict[str, float], rng: random.Random) -> bool:
    """Should this candidate be resampled for being the same shape as everything lately?

    Rejection probability scales with how far past the cap the shape already is, so a
    shape at 50% is only lightly thinned while one at 90% is nearly always resampled.
    """
    if not saturation:
        return False
    share = max(saturation.get(topic_shape(s.topic), 0.0) for s in exp.shots)
    if share <= SHAPE_CAP:
        return False
    excess = (share - SHAPE_CAP) / (1.0 - SHAPE_CAP)
    return rng.random() < excess * _SHAPE_MAX_REJECT


def pick_experiment(rng: random.Random | None = None, ctx: WalkContext | None = None) -> Experiment:
    """Weighted pick with an exploration floor, anti-repeat, and a shape governor.
    `ctx` carries the corpus, recent-topic set, feedback weights, recent shape mix, and
    steer bias; defaults to a corpus-only walk."""
    rng = rng or random.Random()
    ctx = ctx or WalkContext(corpus=load_corpus())
    names = list(BASE_WEIGHTS)
    if rng.random() < EXPLORATION_FLOOR:
        weights = [BASE_WEIGHTS[n] for n in names]                    # pure exploration
    else:
        weights = [BASE_WEIGHTS[n] * min(_FEEDBACK_CAP, max(0.0, ctx.mode_weights.get(n, 1.0)))
                   for n in names]

    def draw() -> Experiment:
        return _build_mode(rng.choices(names, weights=weights, k=1)[0], rng, ctx)

    exp = draw()
    for _ in range(_ANTI_REPEAT_TRIES):     # dodge exact repeats and shape monoculture
        if not _is_repeat(exp, ctx.recent) and not _oversaturated(exp, ctx.shape_saturation, rng):
            return exp
        exp = draw()
    return exp
