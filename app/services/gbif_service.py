"""
Sylva — GBIF species occurrence service
"""

import logging
import httpx
from app.models.farm import SpeciesObservation

LOG = logging.getLogger("sylva.gbif")

GBIF_URL = "https://api.gbif.org/v1/occurrence/search"


async def fetch_species(bbox: dict, limit: int = 300, timeout: int = 60) -> list[SpeciesObservation]:
    """
    Fetch plant species occurrences within bbox from GBIF.
    Returns species sorted by occurrence count, deduplicated.
    """
    LOG.info("GBIF: querying species in bbox")
    params = {
        "decimalLatitude": f"{bbox['south']},{bbox['north']}",
        "decimalLongitude": f"{bbox['west']},{bbox['east']}",
        "kingdom": "Plantae",
        "hasCoordinate": "true",
        "hasGeospatialIssue": "false",
        "limit": limit,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(GBIF_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    counts: dict[str, int] = {}
    for record in data.get("results", []):
        name = record.get("species") or record.get("scientificName")
        if name:
            counts[name] = counts.get(name, 0) + 1

    sorted_species = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    LOG.info("GBIF: ok — %d unique species", len(sorted_species))
    return [SpeciesObservation(name=n, occurrences=c) for n, c in sorted_species]
