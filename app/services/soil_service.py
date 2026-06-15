"""
Sylva — SoilGrids (ISRIC) data service
"""

import logging
import httpx
from app.models.farm import SoilProfile, TopsoilSummary
from app.utils.soil import usda_texture_class

LOG = logging.getLogger("sylva.soil")

SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
PROPERTIES = ["phh2o", "soc", "nitrogen", "bdod", "clay", "sand", "silt", "cec"]
DEPTHS = ["0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm"]


async def fetch_soil(lat: float, lon: float, timeout: int = 60) -> SoilProfile:
    LOG.info("SoilGrids: querying (%.4f, %.4f)", lat, lon)

    params = [("lon", lon), ("lat", lat), ("value", "mean")]
    params += [("property", p) for p in PROPERTIES]
    params += [("depth", d) for d in DEPTHS]

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(SOILGRIDS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    parsed: dict[str, dict] = {}
    for layer in data.get("properties", {}).get("layers", []):
        name = layer["name"]
        unit = layer.get("unit_measure", {})
        d_factor = unit.get("d_factor", 1) or 1
        depths_out = {}
        for d in layer.get("depths", []):
            mean = d.get("values", {}).get("mean")
            depths_out[d["label"]] = (mean / d_factor) if mean is not None else None
        parsed[name] = {"units": unit.get("target_units"), "depths": depths_out}

    def top(prop: str) -> float | None:
        return parsed.get(prop, {}).get("depths", {}).get("0-5cm")

    ph   = top("phh2o")
    sand = top("sand")
    silt = top("silt")
    clay = top("clay")

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

    LOG.info("SoilGrids: ok — pH=%.1f, texture=%s", ph or -1, topsoil.texture_class)
    return SoilProfile(source="SoilGrids v2.0 (ISRIC)", topsoil=topsoil, raw_properties=parsed)
