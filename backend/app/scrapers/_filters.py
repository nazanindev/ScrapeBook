from __future__ import annotations
import re

# Whole-word matches — specific enough that false positives are unlikely
_VIOLENT_WORDS = {
    "gore", "gory", "massacre", "massacred", "execution", "executed",
    "beheading", "beheaded", "decapitation", "decapitated",
    "atrocity", "atrocities", "lynching", "lynched",
    "mutilation", "mutilated", "dismemberment", "dismembered",
    "genocide", "war crime", "war crimes", "torture", "tortured",
    "slaughter", "slaughtered",
}

# Substring matches — phrases specific enough to not catch innocent words
_VIOLENT_PHRASES = (
    "blood spatter", "blood spat", "blood pool", "blood stain",
    "bloodshed", "blood on", "on the wall",
    "dead body", "dead bodies", "dead soldier", "dead soldiers",
    "human remains", "mass grave", "mass graves",
    "bullet hole", "bullet wound",
    "911 attack", "sept 11", "september 11",  # 9/11 site imagery specifically
    "wtc fire", "wtc attack", "world trade center fire",
)

_WORD_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in _VIOLENT_WORDS) + r")\b", re.IGNORECASE)


def violent_match(text: str) -> str | None:
    """The violent word/phrase found in `text`, or None. Shared by the scrapers'
    title filter and the publisher's publish-time screen (which wants the reason)."""
    if not text:
        return None
    m = _WORD_RE.search(text)
    if m:
        return m.group(0)
    lower = text.lower()
    return next((phrase for phrase in _VIOLENT_PHRASES if phrase in lower), None)


def is_violent(title: str) -> bool:
    """Return True if the image title suggests violent content to avoid."""
    return violent_match(title) is not None
