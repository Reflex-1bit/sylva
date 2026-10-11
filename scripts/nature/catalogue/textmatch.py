"""Pure text-matching helpers for the catalogue build (concordance notes a and b).

Keyword matching is whole-word on folded text: lower case, accents stripped (NFKD),
every run of non-alphanumerics turned into one space. A term matches only as a whole
word or a whole phrase, never as a substring ("bionic" does not hit "symbionic").
CPC codes are compared in compact form (upper case, spaces and slashes removed) and
the longest matching prefix wins.
"""

import re
import unicodedata
from functools import lru_cache
from typing import Iterable, Optional

_NON_ALNUM = re.compile(r"[\W_]+")


def fold(text: Optional[str]) -> str:
    """Lower-case, strip accents (NFKD), non-alphanumerics to spaces, collapse spaces."""
    if not text:
        return ""
    if text.isascii():  # fast path: nothing to decompose
        stripped = text.lower()
    else:
        decomposed = unicodedata.normalize("NFKD", text)
        stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return _NON_ALNUM.sub(" ", stripped).strip()


@lru_cache(maxsize=65536)
def fold_term(term: str) -> str:
    """fold() with a cache, for keyword lists that are folded over and over."""
    return fold(term)


def has_term(folded_text: str, term: str) -> bool:
    """True when the folded term is a whole word or phrase of folded_text (space padded)."""
    t = fold_term(term)
    if not t:
        return False
    return f" {t} " in f" {folded_text} "


class FoldedText:
    """A folded text prepared once for many has_term look-ups (same result, faster)."""

    __slots__ = ("text", "padded", "tokens")

    def __init__(self, text: str, already_folded: bool = False):
        self.text = text if already_folded else fold(text)
        self.padded = f" {self.text} "
        self.tokens = frozenset(self.text.split())

    def has(self, term: str) -> bool:
        return self.has_folded(fold_term(term))

    def has_folded(self, t: str) -> bool:
        """has() for a term that is already folded (hot loops pre-fold their term lists)."""
        if not t:
            return False
        if " " not in t:
            return t in self.tokens
        first = t.split(" ", 1)[0]
        return first in self.tokens and f" {t} " in self.padded


def find_terms(text, terms: Iterable[str]) -> list[str]:
    """Distinct terms (in the given order, by folded form) that hit text (str or FoldedText)."""
    ft = text if isinstance(text, FoldedText) else FoldedText(text, already_folded=True)
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        t = fold_term(term)
        if t and t not in seen and ft.has(t):
            seen.add(t)
            out.append(term)
    return out


def count_terms(text, terms: Iterable[str]) -> int:
    """Number of distinct terms (by folded form) that hit text (str or FoldedText)."""
    return len(find_terms(text, terms))


def compact_cpc(code: str) -> str:
    """CPC code in compact form: upper case, spaces and slashes removed."""
    return re.sub(r"[\s/]+", "", code or "").upper()


def longest_prefix(code: str, prefixes: Iterable[str]) -> Optional[str]:
    """The longest prefix (as given) whose compact form starts the compact code; None if none."""
    c = compact_cpc(code)
    best: Optional[str] = None
    best_len = -1
    for p in prefixes:
        cp = compact_cpc(p)
        if cp and c.startswith(cp) and len(cp) > best_len:
            best, best_len = p, len(cp)
    return best
