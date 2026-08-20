"""The experiment scheduler — picks what to generate and how it gets tagged.

One collage per post, always. Series and wandering happen through TAGS, not photosets.
Topics are drawn from meta-topic buckets so the meta-topic tag is known, not guessed.
Biased toward dense collages.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field, replace

import httpx

from app.publisher.corpora import CONNECTORS, Corpus, is_content, load as load_corpus


@dataclass
class Shot:
    topic: str
    density: str | None = "dense"          # default dense; ladders/neutral use None (auto)
    layout_seed: int | None = None
    meta_topics: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()             # the topic's component parts, e.g. ("still life", "fog")
    source: str = ""                       # corpus source the topic came from (aic | met | cma)
    note: str = ""                         # caption annotation, e.g. '"fog" → de' on a parallax pair


@dataclass
class Experiment:
    name: str
    tag: str
    shots: list[Shot]


# ── meta-topic buckets: bucket -> seed words (every specimen carries its bucket) ──
# Each word lives in exactly one bucket so the meta-topic tag is unambiguous.
META_TOPICS: dict[str, list[str]] = {
    "history": ["almanac", "ledger", "census", "chronicle", "gazette", "archive",
                "manuscript", "parchment", "charter", "decree", "proclamation",
                "broadside", "folio", "dispatch", "registry",
                "codex", "edict", "treaty", "deed", "testament", "indenture",
                "gazetteer", "annals", "obituary", "pamphlet", "circular",
                "memorandum", "docket", "ordinance", "missive"],
    "nature": ["fog", "glacier", "tide", "orchard", "moth", "marsh", "moss", "frost", "estuary",
               "heath", "thicket", "lagoon", "dune", "fjord", "meadow", "grove",
               "ravine", "tundra", "bog", "fen", "bramble", "copse", "reef",
               "atoll", "geyser", "moraine", "floodplain", "salt flat",
               "riverbank", "undergrowth"],
    "science": ["observatory", "telescope", "greenhouse", "specimen", "barometer", "microscope", "herbarium",
                "laboratory", "seismograph", "sundial", "orrery", "astrolabe",
                "sextant", "pendulum", "apothecary",
                "alembic", "centrifuge", "chronometer", "hygrometer", "theodolite",
                "vivarium", "terrarium", "bell jar", "retort", "gyroscope",
                "magnetometer", "spectroscope", "anemometer", "phial", "taxidermy"],
    "art": ["fresco", "engraving", "mosaic", "portrait", "still life", "etching", "tapestry",
            "lithograph", "woodcut", "daguerreotype", "triptych", "watercolor",
            "gilding", "stained glass", "sculpture",
            "gouache", "pastel", "mezzotint", "aquatint", "intaglio", "cameo",
            "filigree", "marquetry", "silhouette", "miniature", "frontispiece",
            "illumination", "bas-relief", "plaster cast", "statuette"],
    "culture": ["carnival", "festival", "arcade", "fairground", "vaudeville", "phonograph", "sideshow", "waxworks",
                "cabaret", "ballroom", "marionette", "pantomime", "music hall",
                "gramophone", "matinee",
                "operetta", "burlesque", "carousel", "ventriloquist", "nickelodeon",
                "tightrope", "acrobat", "ringmaster", "zoetrope", "magic lantern",
                "kinetoscope", "phantasmagoria", "promenade", "gala", "revue"],
    "architecture": ["lighthouse", "aqueduct", "rotunda", "pavilion", "stairwell", "bandstand", "facade", "colonnade",
                     "cupola", "portico", "balustrade", "archway", "spire",
                     "cloister", "veranda",
                     "buttress", "gable", "turret", "parapet", "alcove",
                     "vestibule", "mezzanine", "dome", "minaret", "obelisk",
                     "pergola", "terrace", "courtyard", "dormer", "transept"],
    "transport": ["tram", "canal", "railway", "harbor", "ferry", "locomotive", "dirigible", "funicular",
                  "steamship", "gondola", "carriage", "barge", "viaduct",
                  "zeppelin", "caravan",
                  "stagecoach", "rickshaw", "trolleybus", "monorail", "tugboat",
                  "schooner", "clipper", "icebreaker", "cable car", "drawbridge",
                  "roundhouse", "railcar", "omnibus", "sidecar", "velocipede"],
    "communication": ["telegraph", "switchboard", "telephone", "radio", "typewriter", "transmitter", "teleprinter",
                      "semaphore", "postcard", "antenna", "wireless", "postmark",
                      "heliograph", "pneumatic tube",
                      "morse code", "carrier pigeon", "mailbag", "stenograph",
                      "dictaphone", "megaphone", "loudspeaker", "intercom",
                      "shortwave", "telegram", "envelope", "inkwell",
                      "ticker tape", "signal lamp", "courier", "radiogram"],
    "ritual": ["procession", "masquerade", "shrine", "pilgrimage", "maypole", "vigil", "requiem",
               "incense", "litany", "benediction", "seance", "effigy", "censer", "hymnal",
               "offering", "libation", "rosary", "talisman", "amulet", "votive",
               "ex-voto", "wreath", "bonfire", "divination", "incantation",
               "eulogy", "sacrament", "pageant", "altarpiece", "mourning"],
    "industry": ["loom", "kiln", "foundry", "mill", "cannery", "colliery", "printing press",
                 "forge", "quarry", "tannery", "brewery", "sawmill", "warehouse",
                 "shipyard", "distillery",
                 "smelter", "blast furnace", "cooperage", "glassworks", "ironworks",
                 "brickyard", "ropewalk", "gristmill", "assembly line", "derrick",
                 "crucible", "anvil", "bellows", "lathe", "refinery"],
}

QUALIFIERS = [
    "at night", "at dawn", "at dusk", "at low tide", "at high tide", "at midnight",
    "at noon", "at sunrise", "at sunset",
    "in winter", "in fog", "in storm", "in bloom", "in ruins", "in transit",
    "in drizzle", "in eclipse",
    "under snow", "under glass", "under floodlight", "under construction",
    "under tarpaulin", "under scaffolding", "under restoration", "under ice",
    "by lamplight", "by moonlight", "by candlelight", "by torchlight",
    "by starlight", "by gaslight", "by firelight", "by streetlight",
    "from above", "from below", "from afar", "from memory", "from orbit",
    "from storage", "from exile", "from obscurity",
    "on fire", "on ice", "on display", "on loan", "on hold", "on standby",
    "on film", "on tour",
    "over water", "over rooftops", "over snowfields", "over ashes",
    "over wreckage", "over embers", "over drift", "over horizon",
    "with frost", "with rust", "with moss", "with cobwebs", "with patina",
    "with mildew", "with soot", "with ivy",
    "after hours", "after dark", "after closing", "after curfew",
    "after sundown", "after harvest", "after auction", "after departure",
    "before dawn", "before opening", "before departure", "before restoration",
    "before sunrise", "before arrival", "before auction", "before inventory",
    "near extinction", "near collapse", "near ruin", "near silence",
    "near capacity", "near closure", "near completion", "near shore",
    "behind glass", "behind curtains", "behind scaffolding", "behind canvas",
    "behind velvet", "behind smoke", "behind floodlight", "behind screens",
    "operators", "interior", "abandoned", "diagram", "unfinished",
    "decommissioned", "quarantined", "flooded", "condemned", "restored",
    "relocated", "dismantled", "mothballed", "repurposed",
]
YEARS = [str(y) for y in range(1850, 2027)]
# Single words that fan out across unrelated domains (no single meta-topic).
AMBIGUOUS = [
    "mercury", "delta", "apollo", "saturn", "phoenix", "amazon", "java", "titan",
    "iris", "atlas", "nova", "echo", "vega", "orion", "sable",
    "juno", "neptune", "jupiter", "luna", "aurora", "pandora", "sphinx",
    "meridian", "zenith", "polaris", "hudson", "congo", "geneva", "columbia",
    "valencia",
]

# ── drift: evocative / polysemous / half-surreal seeds that push the system's edges ──
POLYSEMOUS = [
    "mercury", "echo", "current", "charge", "vessel", "mantle", "fault", "relay",
    "signal", "drift", "atlas", "iris", "nova", "ember", "relic", "specter",
    "mirror", "needle", "crown", "vault", "tongue", "compass", "prism", "static",
    "plate", "band", "capital", "organ", "temple", "pupil", "score", "chord",
    "wake", "spring", "grain", "circuit", "spine", "cell",
    "anchor", "key", "bell", "crane", "scale", "conductor", "terminal",
    "cabinet", "chamber", "column", "draft", "seal", "palm", "bark", "staff",
    "note", "press",
]
EVOCATIVE = [
    "vertigo", "mirage", "reverie", "oblivion", "trance", "rupture", "decay",
    "hush", "fever", "halo", "eclipse", "threshold", "undertow", "delirium",
    "longing", "aftermath", "solstice", "penumbra", "murmur", "vestige",
    "afterglow", "torpor", "swoon", "duskfall", "stupor", "hollow", "quietude",
    "elegy", "lament", "nocturne", "overture", "interlude", "phantom",
    "apparition", "twilight", "gloaming", "midsummer", "equinox", "eventide",
    "melancholy", "nostalgia", "resonance", "dissolution", "vanishing",
    "absence", "stillness", "slumber", "daydream", "fugue", "omen",
]
MATTER = [
    "rust", "salt", "ash", "glass", "copper", "neon", "velvet", "smoke", "amber",
    "tar", "chrome", "bone", "wax", "ivory", "obsidian",
    "porcelain", "granite", "lichen", "cinder", "brass", "resin", "graphite",
    "slate", "quartz", "vellum", "silt", "coal", "soot",
    "iron", "tin", "pewter", "bronze", "marble", "limestone", "sandstone", "lead",
    "enamel", "lacquer", "indigo", "ochre", "sepia", "verdigris", "tallow",
    "pitch", "chalk", "clay", "terracotta", "alabaster", "mica", "linen",
    "nickel", "cobalt", "gilt", "mahogany", "ebony", "driftwood", "cork",
    "leather", "felt", "burlap", "muslin", "gauze", "brocade", "mother-of-pearl",
    "tortoiseshell", "whalebone", "horsehair", "beeswax", "charcoal", "plaster",
    "mortar", "basalt", "flint", "pumice", "gypsum",
]
VESSELS = [
    "cathedral", "ruin", "engine", "machine", "garden", "opera", "circus", "asylum",
    "observatory", "reliquary", "mausoleum", "carnival", "altar", "menagerie",
    "conservatory", "amphitheatre", "clocktower", "sanatorium", "planetarium",
    "aviary", "orangery", "crypt", "belfry", "granary", "arboretum", "atrium",
    "monastery", "citadel", "catacomb", "apiary", "pagoda", "ossuary", "gazebo",
    "grotto", "labyrinth", "fountain", "chapel", "boathouse", "watchtower",
    "hippodrome", "bathhouse", "windmill", "silo", "depot", "arsenal",
    "velodrome", "athenaeum", "gasworks", "icehouse", "scriptorium",
    "bazaar", "market hall", "custom house", "mint", "courthouse", "armory",
    "barracks", "fortress", "manor", "cottage", "farmhouse", "stable",
    "dovecote", "wharf", "pier", "quay", "breakwater", "boardwalk",
    "reservoir", "cistern", "teahouse", "tavern", "inn", "infirmary", "solarium",
]

# ── atlas: cities, biased toward evocative/lesser-photographed over the usual
# mega-tourist set (which already dominates Commons/museum scrapes elsewhere) ──
CITIES = [
    "Marrakesh", "Fez", "Tangier", "Zanzibar City", "Lagos", "Accra", "Dakar",
    "Nairobi", "Addis Ababa", "Asmara", "Alexandria", "Isfahan", "Shiraz",
    "Samarkand", "Bukhara", "Tbilisi", "Yerevan", "Baku", "Istanbul",
    "Thessaloniki", "Sarajevo", "Dubrovnik", "Ljubljana", "Kraków", "Gdańsk",
    "Riga", "Vilnius", "Tallinn", "Reykjavik", "Bergen", "Porto", "Seville",
    "Granada", "Palermo", "Trieste", "Kyoto", "Nara", "Kanazawa", "Busan",
    "Hoi An", "Luang Prabang", "Chiang Mai", "Yangon", "Varanasi", "Jaipur",
    "Colombo", "Kathmandu", "Ulaanbaatar", "Vladivostok", "Irkutsk",
    "Valparaíso", "Cusco", "Cartagena", "Oaxaca", "Mérida", "Havana",
    "Salvador", "Ouro Preto", "Montevideo", "La Paz", "Quito", "Wellington",
    "Hobart", "Darwin", "Suva",
    "Timbuktu", "Mombasa", "Khartoum", "Tunis", "Algiers", "Beirut", "Aleppo",
    "Muscat", "Tashkent", "Almaty", "Lahore", "Mandalay", "Phnom Penh",
    "Vientiane", "Surabaya", "Tainan", "Sapporo", "Harbin", "Qingdao",
    "Batumi", "Odesa", "Plovdiv", "Mostar", "Kotor", "Sibiu", "Lviv",
    "Kaunas", "Trondheim", "Bruges", "Leipzig", "Dresden", "Salzburg",
    "Coimbra", "Genoa", "Bologna",
]


def _seed(rng: random.Random) -> int:
    return rng.randint(0, 2**31 - 1)


def _pick_meta(rng: random.Random) -> tuple[str, str]:
    """Return (meta_topic, seed_word)."""
    mt = rng.choice(list(META_TOPICS))
    return mt, rng.choice(META_TOPICS[mt])


_QUAL_PREPS = ("in ", "at ", "under ", "by ", "from ", "on ", "over ",
               "with ", "after ", "before ", "near ", "behind ")


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
    """One prompt, two layout seeds — same fragments, different dice. Grouped by the topic tag.

    Two shots, not three: a pair reads as "same fragments, different dice"; a third
    re-roll of the identical topic just pads the feed with near-duplicates."""
    mt, word = _pick_meta(rng)
    qual = rng.choice(QUALIFIERS)
    topic = f"{word} {qual}"
    parts = (word, _qual_tag(qual))
    shots = [Shot(topic=topic, density="dense", layout_seed=_seed(rng), meta_topics=(mt,), tags=parts)
             for _ in range(2)]
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
    recent_words: frozenset[str] = frozenset()      # lowercased seed words to avoid (short window)
    recent_modes: tuple[str, ...] = ()              # modes of recent records, oldest -> newest
    mode_weights: dict[str, float] = field(default_factory=dict)  # feedback: mode -> multiplier
    source_weights: dict[str, float] = field(default_factory=dict)  # feedback: source -> multiplier
    shape_saturation: dict[str, float] = field(default_factory=dict)  # shape -> recent share
    source_bias: dict[str, float] = field(default_factory=dict)   # steer: corpus source -> weight
    pinned: tuple[str, ...] = ()                     # steer: seed words to lean on


def note_pick(ctx: WalkContext, exp: Experiment) -> WalkContext:
    """Fold a just-picked experiment back into the context, so later picks in the
    SAME batch see it. The ledger only reflects past runs — without this, a
    `--count 4` batch draws all four from one snapshot and the cooldown and
    anti-repeat are blind to their own batch-mates."""
    return replace(
        ctx,
        recent=ctx.recent | {s.topic.strip().lower() for s in exp.shots},
        recent_words=ctx.recent_words | {t.strip().lower() for s in exp.shots for t in s.tags},
        recent_modes=ctx.recent_modes + (exp.tag,) * len(exp.shots),
    )


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
    n = sum(1 for w in words if is_content(w.lower()))
    kind = "composed" if any(w.lower() in CONNECTORS for w in words) else "bare"
    return f"{kind}-{min(n, 4)}w" + ("+" if n >= 4 else "")


def content_words(phrase: str) -> tuple[str, ...]:
    """The taggable words of a phrase. Connectors make useless tags (#of, #the), and so
    do the stray short tokens that survive in a topic (#q from "initial q with saints")."""
    return tuple(w for w in phrase.split() if is_content(w.lower()))


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
    # Only ~2 in 5 corpus phrases are long enough to graft, so a single draw fell back
    # more often than it grafted. Re-draw a few times first, and fall back to a plain
    # lift rather than a frame — if we already hold a composed phrase, lifting it whole
    # beats discarding it for two curated words in a template.
    picked = None
    for _ in range(4):
        picked = _pick_phrase(rng, ctx)
        if picked and len(content_words(picked[0])) >= 3:
            break
    else:
        return build_lift(rng, ctx) if picked else build_frame(rng, ctx)
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


# ── the border crossing: the same concept under another language's name ──────
# Commons descriptions, Flickr titles and Openverse tags are written in the
# uploader's language, so "Nebel" and "霧" retrieve material "fog" never sees.
# Wikipedia langlinks are the keyless translator — human-made and concept-level
# (article titles, not dictionary lookups). The pipeline is untouched: it just
# receives a topic that happens not to be in English.
#
# Languages picked for scraper yield (large Commons/Flickr communities) and for
# script variety — a different script shifts the retrieval the furthest.
_LANGS = {
    "de": "german", "fr": "french", "es": "spanish", "it": "italian",
    "nl": "dutch", "pt": "portuguese", "pl": "polish", "sv": "swedish",
    "cs": "czech", "tr": "turkish", "ru": "russian", "uk": "ukrainian",
    "el": "greek", "fa": "persian", "ar": "arabic", "hi": "hindi",
    "ja": "japanese", "zh": "chinese", "ko": "korean",
}
_TITLE_MAX = 30


def _langlinks(title: str) -> dict[str, str]:
    """The article's title in every language it exists in; {} on any failure.

    Disambiguation pages are rejected outright: their langlinks point at OTHER
    disambigs and pop-culture namesakes ("journey" -> the band's katakana title),
    not at the concept."""
    try:
        resp = httpx.get(
            _WIKI_API,
            params={"action": "query", "prop": "langlinks|pageprops", "titles": title,
                    "ppprop": "disambiguation", "redirects": 1, "lllimit": 500,
                    "format": "json", "formatversion": 2},
            timeout=10,
            headers={"User-Agent": _WIKI_UA},
        )
        page = (resp.json().get("query", {}).get("pages") or [{}])[0]
        if "disambiguation" in (page.get("pageprops") or {}):
            return {}
        links = page.get("langlinks") or []
        return {l["lang"]: l["title"].strip() for l in links if l.get("title")}
    except Exception:
        return {}


def _translations(word: str) -> list[tuple[str, str]]:
    """(lang code, title) pairs usable as topics. Skips titles that merely re-spell
    the English word (no retrieval shift), carry disambiguators or punctuation,
    or run too long to retrieve on the scrapers."""
    out = []
    for code, title in _langlinks(word).items():
        if code not in _LANGS:
            continue
        if title.lower() == word.lower() or any(c in title for c in "(/:,"):
            continue
        if len(title) > _TITLE_MAX or any(c.isdigit() for c in title):
            continue
        out.append((code, title))
    return out


def _pick_translation(rng: random.Random, ctx: WalkContext) -> tuple[str, str, str] | None:
    """(english word, lang code, foreign title), or None if nothing translates.

    Draws from the concrete-leaning pools — museum-harvest words and curated nouns
    tend to have Wikipedia articles; abstract coinages mostly don't and just burn
    a try, so EVOCATIVE stays out of this pool."""
    pool = _corpus_words(ctx) + list(MATTER) + list(VESSELS) \
        + [w for ws in META_TOPICS.values() for w in ws]
    for _ in range(4):
        word = _word(rng, ctx, pool, pinned_p=0.5)
        cands = _translations(word)
        if cands:
            code, title = rng.choice(cands)
            return word, code, title
    return None


def build_calque(rng: random.Random, ctx: WalkContext) -> Experiment:
    """One concept borrowed under another language's name — the scrapers answer in
    that language's material. The caption stays quiet — the foreign word stands
    bare; the tags keep the English word and language as the receipts."""
    picked = _pick_translation(rng, ctx)
    if not picked:
        return build_single(rng, ctx)      # Wikipedia offline / nothing translated
    word, code, title = picked
    return Experiment("calque", "calque",
                      [Shot(topic=title, density="dense", meta_topics=_bucket_of(word),
                            tags=(word, _LANGS[code]))])


def build_parallax(rng: random.Random, ctx: WalkContext) -> Experiment:
    """The same concept posted twice — in English, then in another language. The
    pair shows how much of a "topic" was really the language it was asked in."""
    picked = _pick_translation(rng, ctx)
    if not picked:
        return build_single(rng, ctx)
    word, code, title = picked
    return Experiment("parallax", "parallax", [
        Shot(topic=word, density="dense", meta_topics=_bucket_of(word), tags=(word,)),
        Shot(topic=title, density="dense", meta_topics=_bucket_of(word),
             tags=(word, _LANGS[code]), note=f'"{word}" → {code}'),
    ])


def build_atlas(rng: random.Random) -> Experiment:
    """The parallax trick aimed at geography: a city, posted in English, then again
    under its own place's name for a language with a Wikipedia article on it. Draws
    from a curated CITIES pool (not the corpus) so it's ctx-free like wander — and
    biased toward the evocative/lesser-scraped over the usual tourist-postcard set.
    Falls back to a single English post if nothing translates."""
    city = rng.choice(CITIES)
    cands = _translations(city)
    if not cands:
        return Experiment("atlas", "atlas", [Shot(topic=city, density="dense", tags=(city,))])
    code, title = rng.choice(cands)
    return Experiment("atlas", "atlas", [
        Shot(topic=city, density="dense", tags=(city,)),
        Shot(topic=title, density="dense", tags=(city, _LANGS[code]), note=f'"{city}" → {code}'),
    ])


# Curated structural builders (ctx-free) — variety that was never the "salt vessel"
# problem, so they stay. domain-drift stays available via --experiment but out of
# the random feed — too square to govern the walk on its own.
_CURATED_BUILDERS = {
    "specimen": build_specimen,
    "domain-drift": build_domain_drift,
    "seed-series": build_seed_series,
    "density-ladder": build_density_ladder,
    "neutral-zone": build_neutral_zone,
    "diptych": build_diptych,
    "wander": build_wander,
    "atlas": build_atlas,
}
# Corpus-fed walk builders (take a WalkContext).
_WALK_BUILDERS = {
    "single": build_single,
    "lift": build_lift,
    "graft": build_graft,
    "frame": build_frame,
    "calque": build_calque,
    "parallax": build_parallax,
}
BUILDERS = {**_CURATED_BUILDERS, **_WALK_BUILDERS}

# Base weights: lift is the spine; single/graft/frame carry the rest of the walk; the
# curated builders add structural variety. Feedback tilts these; the exploration floor
# ignores feedback entirely so the space can never collapse onto the optimizer.
#
# graft and frame are the two modes that BUILD a topic out of independent draws rather
# than lifting one, so they're the ones that drift toward arbitrary combos; they're held
# low and lift (now yielding composed, connector-keeping phrases) carries more.
#
# calque rides the walk like graft/frame; parallax is a two-post pair, kept rare.
#
# wander (random Wikipedia subject) and atlas (a city, paired parallax-style with its
# local-language name) are both unbounded/serendipitous rather than corpus-fed, so
# they're kept at parallax-rarity too.
#
# seed-series and density-ladder are the multi-shot "same word again" modes: low
# weight AND a cooldown (below), so they read as an occasional bit, not a habit.
BASE_WEIGHTS = {
    "lift": 7, "single": 4, "graft": 2, "frame": 2, "calque": 2,
    "seed-series": 1, "density-ladder": 1, "diptych": 2, "specimen": 1,
    "neutral-zone": 1, "parallax": 1, "wander": 1, "atlas": 1,
}
# Multi-shot curated modes are a treat, not a staple: after one runs, it sits out
# this many subsequent ledger RECORDS (posts, not days — the walker currently lands
# ~9-12 records/day at count=8, so 70 ≈ a week). A cooled-down mode's weight is zeroed
# even during exploration-floor picks; explicit `--experiment <name>` runs are unaffected.
MODE_COOLDOWN = {"seed-series": 70, "density-ladder": 70}
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


def _word_repeat(exp: Experiment, recent_words: frozenset[str]) -> bool:
    """Did any of this candidate's seed words already headline a recent post?

    Exact-topic anti-repeat is blind to the word level: "chronicle at dusk",
    "chronicle 1904" and "chronicle in fog" are all distinct topics, so a seed
    word from a small curated bucket could cycle back every few posts. The window
    is short (see ledger.recent_words) so this thins echoes without exhausting
    the curated pools — and like all rejection here it's best-effort: the try
    loop is bounded, so a saturated window degrades to the old behavior."""
    return any(t.strip().lower() in recent_words for s in exp.shots for t in s.tags)


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

    def _cooled(n: str) -> float:
        """0 while the mode sits inside its cooldown window, 1 otherwise."""
        k = MODE_COOLDOWN.get(n, 0)
        return 0.0 if k and n in ctx.recent_modes[-k:] else 1.0

    if rng.random() < EXPLORATION_FLOOR:
        weights = [BASE_WEIGHTS[n] * _cooled(n) for n in names]       # pure exploration
    else:
        weights = [BASE_WEIGHTS[n] * _cooled(n)
                   * min(_FEEDBACK_CAP, max(0.0, ctx.mode_weights.get(n, 1.0)))
                   for n in names]

    def draw() -> Experiment:
        return _build_mode(rng.choices(names, weights=weights, k=1)[0], rng, ctx)

    exp = draw()
    for _ in range(_ANTI_REPEAT_TRIES):     # dodge repeats (topic + word level) and shape monoculture
        if (not _is_repeat(exp, ctx.recent)
                and not _word_repeat(exp, ctx.recent_words)
                and not _oversaturated(exp, ctx.shape_saturation, rng)):
            return exp
        exp = draw()
    return exp
