"""Publish-time screen — the two cheap checks that replace the morning look.

The walk posts straight to public now, so this is the only gate between the pipeline
and the feed. It rejects two things:

1. **Empty-ish canvases.** The frontend drops every image that fails to load, so a
   collage whose sources 404'd renders as a few text scraps on cream. The collage JSON
   still lists the dead images, so we measure the rendered PNG (the ground truth):
   how much of the canvas is not bare background, and how many images actually loaded.

2. **Inappropriate text.** The scrapers already drop violent image titles and DDG runs
   with safesearch on, but text fragments (headlines, snippets, subreddit names), the
   pages images came from, and the walker's own topics are unscreened. A whole-word
   blocklist runs over everything that ends up on the canvas, in the caption, or in
   the tags.

Deliberately conservative and dumb: no image classifier, no model call, and a hit on
any bucket rejects the post. Anything rejected is recorded to the ledger as
`rejected` (so the walk still learns and won't retry the topic), printed with its
reason, and skipped. Tune the thresholds / word lists here; `--no-screen` bypasses.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from app.scrapers._filters import violent_match

# ── empty-canvas thresholds ───────────────────────────────────────────────────
MIN_COVERAGE = 0.40   # fraction of the canvas that must be something other than cream
                      # (measured: full collages 54-89%; broken ones 12% and 35%)
MIN_IMAGES = 4        # distinct images that actually loaded (the JSON count includes dead ones)
                      # (the ranker keeps >= 5 even at explicit sparse density)

_CANVAS_BG = (237, 229, 216)  # the cream background — same constant as caption.palette_tags
_BG_TOL = 22
_TEXT_TYPES = {"headline", "snippet", "metadata"}

# ── text blocklist: bucket -> regex fragments (whole-word unless written otherwise) ──
# Kept narrow on purpose, and every pattern is bounded so old-text / museum vocabulary
# stays clean: "naked" (naked eye), "cock"/"tits" (birds), "dick" (Moby-Dick), "ass",
# "fetish" (African art), "retard" (flame retardant), "chink" (of light), "rapeseed",
# "niggling", "spicy", and "nazi"/"hitler" (WWII-era history is on-topic and the site
# carries a 15+ label) are all deliberately NOT matched. Image titles are the only
# handle on pictures — a nude titled "Torso" passes.
_BUCKETS: dict[str, list[str]] = {
    "sexual": [
        r"porn\w*", r"xxx", r"nsfw", r"hentai", r"erotica?", r"bdsm",
        r"orgasms?", r"dildos?", r"blowjobs?", r"handjobs?", r"cumshots?",
        r"masturbat\w*", r"strip club", r"onlyfans", r"camgirls?",
        r"sex tape", r"sex toys?", r"sexting", r"nudes?", r"nudity", r"topless",
        r"incest\w*", r"bestiality", r"pedophil\w*", r"paedophil\w*", r"child porn\w*",
        r"rape[sd]?", r"rapists?", r"molest\w*",
    ],
    "profane": [
        r"fuck\w*", r"motherfuck\w*", r"cunts?", r"shit(?:s|ty|ting|head)?", r"bullshit",
        r"assholes?", r"bitch(?:es|y)?", r"whores?", r"sluts?",
    ],
    "slur": [
        r"nigg(?:er|ers|a|as|uh)", r"fagg?ots?", r"kikes?", r"spics?", r"gooks?",
        r"wetbacks?", r"tranny", r"trannies", r"ragheads?", r"towelheads?",
    ],
    "self-harm": [
        r"suicid\w*", r"self[- ]harm\w*",
    ],
    "violent": [  # for free text; image titles also get the scrapers' broader filter
        r"massacre[sd]?", r"beheading", r"decapitat\w*", r"genocide", r"lynch(?:ing|ed)",
        r"dismember\w*", r"mutilat\w*", r"war crimes?", r"mass graves?", r"dead bod(?:y|ies)",
        r"terrorist attacks?", r"mass shootings?", r"school shootings?", r"shooting spree",
        r"child abuse",
    ],
}
_BUCKET_RE = {b: re.compile(r"\b(?:" + "|".join(pats) + r")\b", re.IGNORECASE)
              for b, pats in _BUCKETS.items()}


@dataclass
class Verdict:
    ok: bool
    reason: str = ""
    coverage: float = 0.0
    images: int = 0
    hits: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        head = "ok" if self.ok else f"REJECTED ({self.reason})"
        return f"{head} · coverage {self.coverage:.0%} · {self.images} image(s) loaded"


# ── canvas ────────────────────────────────────────────────────────────────────
def canvas_coverage(png_path) -> float:
    """Fraction of the rendered canvas that is not bare background (downsampled)."""
    from PIL import Image
    im = Image.open(png_path).convert("RGB")
    im.thumbnail((160, 220))
    total = ink = 0
    for r, g, b in im.getdata():
        total += 1
        if abs(r - _CANVAS_BG[0]) < _BG_TOL and abs(g - _CANVAS_BG[1]) < _BG_TOL \
                and abs(b - _CANVAS_BG[2]) < _BG_TOL:
            continue
        ink += 1
    return ink / total if total else 0.0


# ── text ──────────────────────────────────────────────────────────────────────
def _url_words(url: str) -> str:
    """The page path as words — the closest thing to a title for image fragments
    (File:Reclining_Nude.jpg, /r/sub/comments/x/thread_title_slug/)."""
    if not url:
        return ""
    path = unquote(urlparse(url).path)
    return re.sub(r"[/_\-.+]+", " ", path)


def collage_texts(collage: dict) -> list[str]:
    """Every string a viewer could read on the canvas, plus each source's page path
    and og metadata (image titles included — the only handle we have on pictures)."""
    out: list[str] = []
    for f in collage.get("fragments", []):
        if f.get("type") in _TEXT_TYPES:
            out.append(f.get("content") or "")
        for v in (f.get("og") or {}).values():
            if isinstance(v, str):
                out.append(v)
        out.append(_url_words(f.get("source_url") or ""))
    return out


def image_titles(collage: dict) -> list[str]:
    """Titles of the picture fragments (set by the extractor since the screen exists;
    older backends leave og empty and these simply go unscreened)."""
    return [(f.get("og") or {}).get("title") or ""
            for f in collage.get("fragments", []) if f.get("type") not in _TEXT_TYPES]


def flagged_terms(texts, titles=()) -> list[str]:
    """Blocklist hits across `texts`, as 'bucket:term' — empty when clean.

    `titles` (image titles, the topic) additionally go through the scrapers' violent
    title filter. That list is tuned for captions of pictures ("execution", "on the
    wall") and would misfire on prose ("executed in oil"), so it stays off free text."""
    hits: list[str] = []
    for t in texts:
        if not t:
            continue
        t = re.sub(r"[_\-]+", " ", t)  # r/nsfw_gifs, file-name-slugs: let \b see the words
        for bucket, rx in _BUCKET_RE.items():
            for m in rx.finditer(t):
                hits.append(f"{bucket}:{m.group(0).lower()}")
    for t in titles:
        v = violent_match(t)
        if v:
            hits.append(f"violent-title:{v.lower()}")
    # de-dupe, keep order
    seen: set[str] = set()
    return [h for h in hits if not (h in seen or seen.add(h))]


# ── the gate ──────────────────────────────────────────────────────────────────
def check(*, png_path, images_loaded: int, collage: dict, topic: str = "",
          caption: str = "", tags=(), note: str = "") -> Verdict:
    """Decide whether one rendered shot may go public."""
    coverage = canvas_coverage(png_path)
    hits = flagged_terms([topic, note, caption, *tags, *collage_texts(collage)],
                         titles=[topic, *image_titles(collage)])
    if hits:
        return Verdict(False, "flagged: " + ", ".join(hits[:6]), coverage, images_loaded, hits)
    if images_loaded < MIN_IMAGES:
        return Verdict(False, f"empty: only {images_loaded} image(s) loaded (min {MIN_IMAGES})",
                       coverage, images_loaded)
    if coverage < MIN_COVERAGE:
        return Verdict(False, f"empty: coverage {coverage:.0%} < {MIN_COVERAGE:.0%}",
                       coverage, images_loaded)
    return Verdict(True, "", coverage, images_loaded)
