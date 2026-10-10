"""
Sylva - Nature arm tokenizer: lowercase, accent fold, EN+ES stopwords, light plural strip.
"""

import re
import unicodedata

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS_EN = """
a an the and or but if then else of to in on at by for with without from into onto over under
is are was were be been being am do does did done has have had having it its this that these those
as not no nor so than too very can could should would will may might must we you they he she i me my
our your their his her them us which who whom whose what when where why how all any each both few
more most other some such only own same about above below between through during before after
up down out off again further once here there also per via
""".split()

_STOPWORDS_ES = """
el la los las un una unos unas y o u e de del al a en con sin por para como que se su sus es son
fue ser esta este estos estas ese esa eso esto lo le les me te nos mi tu si no ni pero mas muy
sobre entre desde hasta cada todo toda todos todas otro otra otros otras tambien hay
""".split()


def normalise(s: str) -> str:
    """Lowercase and strip accents (NFKD, drop combining marks)."""
    decomposed = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


# Stopwords are compared after normalisation, so store them folded.
STOPWORDS = frozenset(normalise(w) for w in _STOPWORDS_EN + _STOPWORDS_ES)


# Words whose plural does not follow the suffix rules below.
_IRREGULAR = {"gases": "gas", "biases": "bias", "buses": "bus"}
# English plurals in -ores that must not be read as Spanish (flores -> flor).
_NOT_SPANISH_ORES = frozenset(
    "scores stores cores pores spores shores chores explores restores ignores bores".split()
)


def _singular(tok: str) -> str:
    """Conservative EN+ES plural strip. Applied to queries and documents alike.

    Known limitation: irregular plurals are not handled (leaves stays 'leave',
    never 'leaf'), and a Spanish singular (proceso) is not joined to its English
    cognate (process).
    """
    n = len(tok)
    if tok in _IRREGULAR:
        return _IRREGULAR[tok]
    if n > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if n > 4 and tok.endswith("sses"):
        return tok[:-2]
    # English -es after a sibilant: processes, boxes, patches, brushes
    if n > 4 and tok.endswith(("xes", "ches", "shes")):
        return tok[:-2]
    # Spanish -es: materiales, ciudades, naciones, flores
    if n >= 7 and tok.endswith(("ales", "dades", "iones")):
        return tok[:-2]
    if n >= 6 and tok.endswith("ores") and tok not in _NOT_SPANISH_ORES:
        return tok[:-2]
    if n > 3 and tok.endswith("s") and not tok.endswith(("ss", "us", "is")):
        return tok[:-1]
    return tok


def tokenize(s: str) -> list[str]:
    out = []
    for tok in _TOKEN_RE.findall(normalise(s)):
        if len(tok) < 2 or tok in STOPWORDS:
            continue
        tok = _singular(tok)
        if len(tok) >= 2:
            out.append(tok)
    return out
