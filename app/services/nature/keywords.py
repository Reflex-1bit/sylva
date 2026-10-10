"""
Sylva - Nature arm: keywords that must never assign a function on their own.

Shared by the OpenAlex harvester (Ruling 3-1) and the challenge parser
(matcher.parse_functions). Matched after accent folding. "in water" is listed
because tokenising drops "in", leaving the bare word "water".
"""

WEAK_KEYWORDS = frozenset(
    """
    packaging package container embalaje envase wastewater network red joint joining union
    detergent detergente strength membrane membrana plantilla templating rigid rigidity sliding
    bearing lift wing ala motor cuenca seto mixing modular dirt residue wood cork mold mould
    oxidation cellular flight crack deposit scaling erosion lifetime monitoring reserve
    """.split()
) | {"aguas residuales", "in water"}
