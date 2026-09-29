"""Filename derivation for downloaded assets."""

from __future__ import annotations

import re

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_WORDS = 6
_MAX_SLUG_LENGTH = 48


def slugify_prompt(prompt: str) -> str:
    """Turn a prompt into a short, safe filename slug.

    "A futuristic cyberpunk helmet" -> "futuristic-cyberpunk-helmet"

    Filters out path separators, traversal sequences and anything else that is
    not [a-z0-9-], so the result is always safe to put in a
    Content-Disposition header.
    """
    slug = _NON_SLUG.sub("-", prompt.lower()).strip("-")
    if not slug:
        return "model"

    # Drop leading articles so the name starts with something meaningful.
    words = [w for w in slug.split("-") if w]
    while words and words[0] in {"a", "an", "the"}:
        words.pop(0)
    if not words:
        return "model"

    slug = "-".join(words[:_MAX_SLUG_WORDS])[:_MAX_SLUG_LENGTH].strip("-")
    return slug or "model"


def build_filename(prompt: str) -> str:
    """Build the user-facing download filename for a prompt."""
    return f"formly-{slugify_prompt(prompt)}.glb"
