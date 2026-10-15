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
        seen: set[str] = set()
        cores = {fold(t) for t in terms}
        for t in terms:
            core = fold(t)
            if core in seen:  # "bio-inspired" / "bio inspired" fold alike: keep the first
                continue
            # a plural listed next to its singular is redundant (the pattern allows s/es)
            if (core.endswith("s") and core[:-1] in cores) or (core.endswith("es") and core[:-2] in cores):
                continue
            seen.add(core)
            rx = re.compile(r"(?<![a-z0-9])" + re.escape(core).replace(r"\ ", " ") + r"(?:s|es)?(?![a-z0-9])")
            pats.append((t, rx))
        self._pats = pats

    def counts(self, *texts: Optional[str]) -> dict[str, int]:
        """Occurrences of each matching term (a plural counts for its singular)."""
        folded = fold(" . ".join(t for t in texts if t))
        out = {}
        for t, rx in self._pats:
            n = len(rx.findall(folded))
            if n:
                out[t] = n
        return out

    def matches(self, *texts: Optional[str]) -> list[str]:
        return list(self.counts(*texts))

    def first(self, *texts: Optional[str]) -> Optional[str]:
        m = self.matches(*texts)
        return m[0] if m else None


# A sentence end is . ! ? followed by a capital, digit, quote or bracket (or the end), and not
# preceded by a common abbreviation or a lone capital letter (initials).
_NOT_AFTER = (
    r"(?<!\be\.g)(?<!\bi\.e)(?<!\betc)(?<!\bProf)(?<!\bDr)(?<!\bMr)(?<!\bMrs)(?<!\bMs)"
    r"(?<!\bet al)(?<!\bcf)(?<!\bvs)(?<!\bFig)(?<!\bNo)(?<!\bapprox)(?<!\bincl)(?<!\bresp)"
    r"(?<!\bca)(?<!\bSt)(?<!\b[A-Z])"
)
_SENTENCE_END = re.compile(_NOT_AFTER + r"[.!?](?=\s+[A-Z0-9\"'(\[]|\s*$)")


def cut_summary(text: str, limit: int = 1500) -> str:
    """Collapse whitespace; when too long, cut at the last safe sentence end within the limit,
    else at the last word boundary with an ellipsis appended."""
    s = re.sub(r"\s+", " ", text or "").strip()
    if len(s) <= limit:
        return s
    window = s[:limit]
    ends = [m.end() for m in _SENTENCE_END.finditer(window)]
    if ends and ends[-1] >= limit // 3:
        return window[: ends[-1]].strip()
    return window.rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
