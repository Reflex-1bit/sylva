"""
Sylva soil utilities — USDA 12-class texture triangle
"""


def usda_texture_class(sand: float, silt: float, clay: float) -> str:
    if None in (sand, silt, clay):
        return "unknown"
    s, si, c = sand, silt, clay
    if c >= 40 and si < 40 and s <= 45:
        return "clay"
    if c >= 40 and si >= 40:
        return "silty clay"
    if c >= 35 and s >= 45:
        return "sandy clay"
    if 27 <= c < 40 and 20 < s <= 45:
        return "clay loam"
    if 27 <= c < 40 and s <= 20:
        return "silty clay loam"
    if 20 <= c < 35 and si < 28 and s > 45:
        return "sandy clay loam"
    if 7 <= c < 27 and 28 <= si < 50 and s <= 52:
        return "loam"
    if si >= 50 and (12 <= c < 27 or (c < 12 and si < 80)):
        return "silt loam"
    if si >= 80 and c < 12:
        return "silt"
    if c < 15 and s >= 70 and si + 1.5 * c < 15:
        return "sand"
    if c < 15 and s >= 70 and 15 <= si + 1.5 * c < 30:
        return "loamy sand"
    if c < 20 and s > 52:
        return "sandy loam"
    return "loam"
