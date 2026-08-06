"""
Sylva — SoilGrids (ISRIC) data service

Note: SoilGrids can return a well-formed response with every value null when
the query point lands on a no-data cell (water, urban, or an unmapped pixel).
We detect that case and raise, so the caller records a real error instead of
showing a hollow soil card. We also nudge the query onto land by trying the
exact point first, then a couple of small offsets if it comes back empty.
"""

import logging
import httpx
from app.models.farm import SoilProfile, TopsoilSummary
from app.utils.soil import usda_texture_class

LOG = logging.getLogger("sylva.soil")

SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
PROPERTIES = ["phh2o", "soc", "nitrogen", "bdod", "clay", "sand", "silt", "cec"]
DEPTHS = ["0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm"]

# Small lat/lon nudges (deg) to try if the exact point returns no data.
# ~0.01 deg ≈ 1.1 km. Keeps us within the same farm while dodging dead pixels.
OFFSETS = [(0.0, 0.0), (0.01, 0.0), (-0.01, 0.0), (0.0, 0.01), (0.0, -0.01)]


async def _query(client: httpx.AsyncClient, lat: float, lon: float) -> dict:
    params = [("lon", lon), ("lat", lat), ("value", "mean")]
    params += [("property", p) for p in PROPERTIES]
    params += [("depth", d) for d in DEPTHS]
    resp = await client.get(
        SOILGRIDS_URL,
        params=params,
        headers={"User-Agent": "SylvaAgroforestry/0.2 (farm-profile; contact=sylva)"},
    )
    resp.raise_for_status()
    return resp.json()


def _parse(data: dict) -> tuple[dict, bool]:
    """Return (parsed properties, any_value_present)."""
    parsed: dict[str, dict] = {}
    any_value = False
    for layer in data.get("properties", {}).get("layers", []):
        name = layer["name"]
        unit = layer.get("unit_measure", {})
        d_factor = unit.get("d_factor", 1) or 1
        depths_out = {}
        for d in layer.get("depths", []):
            mean = d.get("values", {}).get("mean")
            if mean is not None:
                any_value = True
                depths_out[d["label"]] = mean / d_factor
            else:
                depths_out[d["label"]] = None
        parsed[name] = {"units": unit.get("target_units"), "depths": depths_out}
    return parsed, any_value


async def fetch_soil(lat: float, lon: float, timeout: int = 25) -> SoilProfile:
    LOG.info("SoilGrids: querying (%.4f, %.4f)", lat, lon)

    parsed: dict = {}
    used_lat, used_lon = lat, lon

    async with httpx.AsyncClient(timeout=timeout) as client:
        for dlat, dlon in OFFSETS:
            q_lat, q_lon = lat + dlat, lon + dlon
            data = await _query(client, q_lat, q_lon)
            parsed, any_value = _parse(data)
            if any_value:
                used_lat, used_lon = q_lat, q_lon
                break

    if not parsed or not any(
        v is not None
        for prop in parsed.values()
        for v in prop["depths"].values()
    ):
        raise RuntimeError(
            "SoilGrids returned no data for this location (likely water, urban, "
            "or an unmapped cell). Try a coordinate on cultivated land."
        )

    if (used_lat, used_lon) != (lat, lon):
        LOG.info("SoilGrids: exact point empty, used nearby (%.4f, %.4f)", used_lat, used_lon)

    def top(prop: str):
        return parsed.get(prop, {}).get("depths", {}).get("0-5cm")

    ph, sand, silt, clay = top("phh2o"), top("sand"), top("silt"), top("clay")

    topsoil = TopsoilSummary(
        ph=ph,
        organic_carbon_g_kg=top("soc"),
        nitrogen_g_kg=top("nitrogen"),
        clay_pct=clay,
        sand_pct=sand,
        silt_pct=silt,
        bulk_density_kg_dm3=top("bdod"),
        cec_cmol_kg=top("cec"),
        texture_class=usda_texture_class(sand, silt, clay) if None not in (sand, silt, clay) else None,
    )

    LOG.info("SoilGrids: ok — pH=%s, texture=%s", ph, topsoil.texture_class)
    return SoilProfile(source="SoilGrids v2.0 (ISRIC)", topsoil=topsoil, raw_properties=parsed)
