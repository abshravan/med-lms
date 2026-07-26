"""Slug generation.

Slugs are user-facing URL identifiers. They are generated from a title once, then
treated as immutable for published content — students bookmark and share these
URLs, and search engines index them.
"""

from __future__ import annotations

import re
import unicodedata

MAX_SLUG_LENGTH = 160

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
_EDGE_HYPHENS = re.compile(r"^-+|-+$")


def slugify(value: str, *, max_length: int = MAX_SLUG_LENGTH) -> str:
    """Convert arbitrary text into a URL-safe slug.

    Unicode is normalised to its closest ASCII form rather than percent-encoded,
    so "Cardiología Básica" becomes `cardiologia-basica` instead of a URL full of
    escape sequences.

    Returns an empty string when the input contains nothing sluggable (for example
    only punctuation or only CJK characters, which NFKD cannot fold to ASCII).
    Callers must handle that — see `unique_slug`.
    """
    normalised = unicodedata.normalize("NFKD", value)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower().strip()
    hyphenated = _NON_ALPHANUMERIC.sub("-", lowered)
    trimmed = _EDGE_HYPHENS.sub("", hyphenated)

    if len(trimmed) <= max_length:
        return trimmed

    cut = trimmed[:max_length]
    # Only walk back to the previous boundary when the cut actually lands
    # mid-word. If the next character is a hyphen, the cut is already on a
    # boundary and trimming further would discard a word that fits.
    if trimmed[max_length] != "-" and "-" in cut:
        cut = cut.rsplit("-", 1)[0]
    return _EDGE_HYPHENS.sub("", cut)


def unique_slug(
    value: str,
    *,
    taken: set[str],
    fallback: str = "item",
    max_length: int = MAX_SLUG_LENGTH,
) -> str:
    """Return a slug for `value` that is not already in `taken`.

    Collisions get a numeric suffix (`anatomy`, `anatomy-2`, `anatomy-3`). The
    base is shortened as needed so the suffix never pushes the result past
    `max_length`.

    This resolves collisions *known to the caller*. The database's unique
    constraint remains the actual guarantee — two concurrent creates can still
    race, and the service layer translates that into a 409.
    """
    base = slugify(value, max_length=max_length) or fallback

    if base not in taken:
        return base

    suffix = 2
    while True:
        tail = f"-{suffix}"
        candidate = f"{base[: max_length - len(tail)]}{tail}"
        if candidate not in taken:
            return candidate
        suffix += 1
