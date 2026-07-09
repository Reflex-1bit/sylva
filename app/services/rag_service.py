"""
Sylva — RAG farm plan generation service (demo)

Simple RAG pipeline:
  1. matched species list + farm profile come in
  2. retrieve relevant agroforestry knowledge chunks (in-memory demo corpus)
  3. stuff context + profile + species into Gemini
  4. return a structured, farmer-readable transition plan

This is the DEMO version — a small in-memory keyword-retrieval corpus stands
in for the full ChromaDB/graph-RAG pipeline. The OKF-style structured memory
layer is being built separately; this proves the end-to-end flow works.
"""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass

LOG = logging.getLogger("sylva.rag")


# ── Tiny demo knowledge corpus ────────────────────────────────────────────────
# In production this becomes ChromaDB (simple RAG) then OKF structured memory
# (graph RAG). Each entry is a self-contained agroforestry fact.

KNOWLEDGE_CORPUS: list[dict] = [
    {"id": "alley-cropping", "tags": ["spacing", "layout", "cropland"],
     "text": "Alley cropping places rows of trees with wide alleys between them for "
             "growing annual crops. Tree rows are typically spaced 12-20m apart, oriented "
             "east-west to reduce shading of the crop alleys."},
    {"id": "n-fixing-benefit", "tags": ["nitrogen", "soil", "legume"],
     "text": "Nitrogen-fixing trees (legumes) form root nodules with Rhizobium bacteria, "
             "adding 50-200 kg N/ha/year to soil. Interplanting them with cereals can cut "
             "fertiliser needs by 30-50% once established."},
    {"id": "degraded-restoration", "tags": ["degraded", "restoration", "erosion"],
     "text": "On degraded land, start with hardy pioneer species that tolerate poor soil and "
             "drought. Nitrogen-fixing, drought-tolerant species rebuild soil biology fastest and "
             "create shade that lets more sensitive species establish later."},
    {"id": "establishment-phase", "tags": ["timeline", "cashflow", "establishment"],
     "text": "Years 0-3 are the establishment phase: trees are planted, growth is slow, and there "
             "is little or no tree income while crops continue. Years 3-7 bring first diversification "
             "income from fruit, pods and thinnings. Years 7+ compound as inputs drop and outputs rise."},
    {"id": "mediterranean-species", "tags": ["mediterranean", "spain", "drought"],
     "text": "For Mediterranean climates with dry summers, olive, carob, almond, fig and stone pine "
             "are proven agroforestry species. They tolerate alkaline soils, summer drought and only "
             "need irrigation during establishment."},
    {"id": "windbreak", "tags": ["shelter", "wind", "layout"],
     "text": "Shelterbelts of trees on field edges reduce wind speed for a distance of 10-15x the "
             "tree height downwind, cutting soil erosion and crop water stress. Use dense, wind-firm "
             "species on the windward edge."},
    {"id": "soil-ph-matching", "tags": ["ph", "soil", "matching"],
     "text": "Match species to soil pH: most Mediterranean trees prefer neutral to alkaline soils "
             "(pH 6.5-8.5). Acid-loving species struggle above pH 7.5. Always confirm topsoil pH "
             "before selecting species."},
    {"id": "intercrop-spacing", "tags": ["spacing", "competition", "water"],
     "text": "Space trees far enough from crops to limit root competition for water — typically a "
             "buffer of 1-2m of cultivated strip between the tree row and the crop. Wider on dry sites."},
]


def retrieve(farm_profile: dict, species_names: list[str], k: int = 4) -> list[dict]:
    """
    Dead-simple keyword retrieval over the demo corpus. Scores each chunk by how
    many query terms (derived from the farm profile + matched species) it matches.
    Real version swaps this for vector similarity / OKF structured retrieval.
    """
    terms: set[str] = set()

    soil = (farm_profile.get("soil") or {}).get("topsoil") or {}
    if soil.get("texture_class"):
        terms.update(soil["texture_class"].lower().split())
    ph = soil.get("ph")
    if ph is not None:
        terms.add("ph")
        terms.add("soil")

    ndvi = farm_profile.get("ndvi") or {}
    if ndvi.get("health_score") is not None and ndvi["health_score"] <= 0.3:
        terms.update(["degraded", "restoration"])

    country = (farm_profile.get("country") or "").lower()
    if country:
        terms.add(country)
    if country in ("spain", "portugal", "italy", "greece"):
        terms.add("mediterranean")

    # matched species imply layout/nitrogen concerns
    terms.update(["spacing", "layout", "timeline", "nitrogen"])

    scored = []
    for chunk in KNOWLEDGE_CORPUS:
        score = len(terms.intersection(chunk["tags"]))
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:k]]


PLAN_PROMPT = """You are an expert agroforestry advisor writing a farm transition plan.

FARM PROFILE:
{profile}

TOP MATCHED SPECIES (already filtered to this farm's soil and climate):
{species}

RELEVANT AGROFORESTRY KNOWLEDGE:
{context}

Write a concise, practical agroforestry transition plan for this specific farm.
Structure it as JSON with these keys:
- "summary": 2-3 sentence overview of the opportunity for this farm
- "recommended_layout": which agroforestry design fits (alley cropping, silvopasture, shelterbelt, etc.) and why
- "priority_species": list of 3-5 species from the matched list with a one-line reason each
- "phased_plan": object with "years_0_3", "years_3_7", "years_7_plus" describing what happens in each phase
- "soil_notes": what the soil data means for this plan

Base everything on the actual farm data and matched species above. Do not invent species that aren't in the matched list. Output ONLY valid JSON.
"""


@dataclass
class RAGResult:
    plan: dict
    retrieved_chunks: list[str]
    model: str


async def generate_farm_plan(
    farm_profile: dict,
    matched_species: list[dict],
    top_species: int = 8,
) -> RAGResult:
    """
    Generate a farm plan via retrieval + Gemini. Falls back to a structured
    non-LLM plan if no API key is set, so the demo always returns something.
    """
    species_subset = matched_species[:top_species]
    species_names = [s.get("species", "") for s in species_subset]
    chunks = retrieve(farm_profile, species_names)
    context_text = "\n".join(f"- {c['text']}" for c in chunks)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        LOG.warning("GEMINI_API_KEY not set — returning fallback plan (no LLM)")
        return RAGResult(
            plan=_fallback_plan(farm_profile, species_subset, chunks),
            retrieved_chunks=[c["id"] for c in chunks],
            model="fallback (no API key)",
        )

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            "gemini-1.5-flash",
            generation_config={"response_mime_type": "application/json", "temperature": 0.3},
        )
        prompt = PLAN_PROMPT.format(
            profile=json.dumps(_slim_profile(farm_profile), indent=2),
            species=json.dumps(
                [{"species": s.get("species"), "uses": s.get("uses"),
                  "nitrogen_fixer": s.get("nitrogen_fixer")} for s in species_subset],
                indent=2,
            ),
            context=context_text,
        )
        resp = await model.generate_content_async(prompt)
        plan = json.loads(resp.text)
        return RAGResult(plan=plan, retrieved_chunks=[c["id"] for c in chunks], model="gemini-1.5-flash")
    except Exception as e:
        LOG.warning("LLM generation failed (%s) — returning fallback", e)
        return RAGResult(
            plan=_fallback_plan(farm_profile, species_subset, chunks),
            retrieved_chunks=[c["id"] for c in chunks],
            model=f"fallback (LLM error: {e})",
        )


def _slim_profile(profile: dict) -> dict:
    """Trim the full profile to just what the LLM needs."""
    soil = (profile.get("soil") or {}).get("topsoil") or {}
    ndvi = profile.get("ndvi") or {}
    return {
        "country": profile.get("country"),
        "lat": profile.get("lat"), "lon": profile.get("lon"),
        "soil_ph": soil.get("ph"),
        "soil_texture": soil.get("texture_class"),
        "organic_carbon_g_kg": soil.get("organic_carbon_g_kg"),
        "ndvi_health_score": ndvi.get("health_score"),
        "ndvi_label": ndvi.get("health_label"),
    }


def _fallback_plan(profile: dict, species: list[dict], chunks: list[dict]) -> dict:
    """Deterministic non-LLM plan so the demo works without an API key."""
    soil = (profile.get("soil") or {}).get("topsoil") or {}
    ndvi = profile.get("ndvi") or {}
    degraded = ndvi.get("health_score") is not None and ndvi["health_score"] <= 0.3
    layout = "restoration planting with pioneer species" if degraded else "alley cropping"
    return {
        "summary": (
            f"This {profile.get('country', 'farm')} site has pH {soil.get('ph')} "
            f"{soil.get('texture_class', '')} soil. "
            + ("Vegetation health is low, so the priority is soil restoration. "
               if degraded else "Conditions support diversified agroforestry. ")
            + f"{len(species)} species match this farm's profile."
        ),
        "recommended_layout": layout,
        "priority_species": [
            {"species": s.get("species"),
             "reason": "nitrogen-fixing, builds soil" if s.get("nitrogen_fixer")
                       else f"suited to this soil; uses: {', '.join(s.get('uses', [])[:2])}"}
            for s in species[:5]
        ],
        "phased_plan": {
            "years_0_3": "Establish trees, minimal tree income, crops continue as normal.",
            "years_3_7": "First diversification income from fruit/pods/thinnings; reduce fertiliser.",
            "years_7_plus": "Compounding returns as input costs fall and tree outputs mature.",
        },
        "soil_notes": f"Topsoil pH {soil.get('ph')}, texture {soil.get('texture_class')}, "
                      f"organic carbon {soil.get('organic_carbon_g_kg')} g/kg.",
        "_note": "Generated without LLM (no GEMINI_API_KEY). Set the key for a richer plan.",
    }
