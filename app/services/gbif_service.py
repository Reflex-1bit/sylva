"""
Sylva — GBIF species occurrence service

Returns ONLY plants (kingdom Plantae). GBIF's search endpoint ignores a
`kingdom=Plantae` string param — you must use the numeric taxonKey (6 = Plantae).
We also post-filter to drop anything whose kingdom didn't come back as Plantae,
as a belt-and-braces guard.
"""

import logging
import httpx
from app.models.farm import SpeciesObservation

LOG = logging.getLogger("sylva.gbif")

GBIF_URL = "https://api.gbif.org/v1/occurrence/search"
PLANTAE_TAXON_KEY = 6  # GBIF kingdom key for Plantae


async def fetch_species(bbox: dict, limit: int = 300, timeout: int = 60) -> list[SpeciesObservation]:
    """Fetch plant species occurrences within bbox from GBIF."""
    LOG.info("GBIF: querying plant species in bbox")
    params = {
        "decimalLatitude": f"{bbox['south']},{bbox['north']}",
        "decimalLongitude": f"{bbox['west']},{bbox['east']}",
        "taxonKey": PLANTAE_TAXON_KEY,       # <-- the actual fix (numeric, not 'Plantae')
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
        # Belt-and-braces: only keep records GBIF actually classified as Plantae
        if record.get("kingdom") and record.get("kingdom") != "Plantae":
            continue
        name = record.get("species") or record.get("scientificName")
        if name:
            counts[name] = counts.get(name, 0) + 1

    sorted_species = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    LOG.info("GBIF: ok — %d unique plant species", len(sorted_species))
    return [SpeciesObservation(name=n, occurrences=c) for n, c in sorted_species]
