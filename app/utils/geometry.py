"""
Sylva geometry utilities
"""

import math

EARTH_KM_PER_DEG_LAT = 111.32


def km_to_deg(km: float, lat: float) -> tuple[float, float]:
    dlat = km / EARTH_KM_PER_DEG_LAT
    dlon = km / (EARTH_KM_PER_DEG_LAT * math.cos(math.radians(lat)))
    return dlat, dlon


def bbox_from_radius(lat: float, lon: float, radius_km: float) -> dict:
    dlat, dlon = km_to_deg(radius_km, lat)
    return {
        "south": round(lat - dlat, 6),
        "north": round(lat + dlat, 6),
        "west": round(lon - dlon, 6),
        "east": round(lon + dlon, 6),
    }


def bbox_polygon(bbox: dict) -> list[list[float]]:
    """Closed [lon, lat] ring."""
    w, e, s, n = bbox["west"], bbox["east"], bbox["south"], bbox["north"]
    return [[w, s], [e, s], [e, n], [w, n], [w, s]]
