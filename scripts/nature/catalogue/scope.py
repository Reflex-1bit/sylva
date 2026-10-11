"""Scope matching and text helpers shared by the CORDIS and Climate-ADAPT harvesters.

Matching rule (concordance note a): lower-cased, accent-folded, whole words or phrases.
Hyphens count as spaces ("bio-inspired" == "bio inspired"); a trailing plural 's'/'es'
is allowed ("bionic" matches "bionics"), but never a prefix ("symbionic" does not match).
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

SCOPE_TERMS_PATH = Path(__file__).resolve().parent / "scope_terms.json"


def fold(text: str) -> str:
    """Lower-case, strip accents, turn hyphens/underscores into spaces, collapse whitespace."""
    nfkd = unicodedata.normalize("NFKD", text or "")
    plain = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    plain = re.sub(r"[-_‐-―]", " ", plain)
    return re.sub(r"\s+", " ", plain).strip()


def load_scope_terms(path: Path = SCOPE_TERMS_PATH) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    seen: dict[str, None] = {}
    for terms in data.values():
        for t in terms:
            seen[t] = None
    return list(seen)


class ScopeMatcher:
    """Find scope terms present in a text as whole words or phrases."""

    def __init__(self, terms: list[str]):
        self.terms = terms
        pats = []
        for t in terms:
            core = re.escape(fold(t)).replace(r"\ ", " ")
            pats.append((t, re.compile(r"(?<![a-z0-9])" + core + r"(?:s|es)?(?![a-z0-9])")))
        self._pats = pats

    def matches(self, *texts: Optional[str]) -> list[str]:
        folded = fold(" . ".join(t for t in texts if t))
        return [t for t, rx in self._pats if rx.search(folded)]

    def first(self, *texts: Optional[str]) -> Optional[str]:
        m = self.matches(*texts)
        return m[0] if m else None


def cut_summary(text: str, limit: int = 1500) -> str:
    """Collapse whitespace; when too long, cut at the last sentence end within the limit
    (or at a word boundary if there is no sentence end past the first third)."""
    s = re.sub(r"\s+", " ", text or "").strip()
    if len(s) <= limit:
        return s
    window = s[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", window)]
    if ends and ends[-1] >= limit // 3:
        return window[: ends[-1]].strip()
    return window.rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
