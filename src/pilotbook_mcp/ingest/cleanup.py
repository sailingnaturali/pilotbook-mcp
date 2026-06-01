"""Deterministic prose cleanup — strip chartlet-key sub-spot letters left in the body.

Pilot-book chartlets label anchor positions with small letters (q, r, s, …); the
extracted prose often keeps them ("q Good protection…", "r (East of Head): …").
This removes them from the BODY only, never the frontmatter.

Safety: it matches a single lowercase letter in **q–z** only (none are English words,
so it can't eat "a" or "i"), standing alone (not part of a word), followed by a space
and an uppercase letter or "(" — the shape of a sub-spot label. Numbers ("3 Brown's
Bay Resort") are left alone.
"""

from __future__ import annotations

import re

# a lone q–z letter, not part of a word and not a possessive 's, followed by " X" or " ("
# (the shape of a sub-spot label). The apostrophe exclusion protects "God's Pocket" etc.
_SUBSPOT_RE = re.compile(r"(?<![A-Za-z'’])([q-z]) (?=[A-Z(])")


def strip_subspot_letters(prose: str) -> tuple[str, int]:
    """Return (cleaned prose, number of sub-spot letters removed)."""
    return _SUBSPOT_RE.subn("", prose)


def clean_file_text(text: str) -> tuple[str, int]:
    """Clean the prose body of a record's raw markdown, preserving frontmatter verbatim."""
    if not text.startswith("---"):
        return strip_subspot_letters(text)
    parts = text.split("---", 2)  # ['', frontmatter, body]
    if len(parts) < 3:
        return text, 0
    body, n = strip_subspot_letters(parts[2])
    return f"---{parts[1]}---{body}", n


def examples(prose: str, limit: int = 1) -> list[str]:
    """A few short 'X …' snippets showing what would be stripped (for dry-run preview)."""
    out = []
    for m in _SUBSPOT_RE.finditer(prose):
        snippet = prose[m.start():m.start() + 32].replace("\n", " ").strip()
        out.append(snippet)
        if len(out) >= limit:
            break
    return out
