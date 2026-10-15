"""Stage candidate nature-library records from DOIs (AI extraction, human review required).

For each DOI: fetch the OpenAlex work (title, year, topics, open-access licence; the
abstract is never read), optionally fetch the open-access full text when the licence is
CC BY or CC0, ask Gemini for a LibraryRecord and append the validated result to
library_staging.json as stg-NNNN. Invalid output is logged and dropped. The pipeline,
not the model, owns the id, provenance, evidence list and legal/consent flags.

The fetched text is never stored. A supporting_sentence is kept only if it is an exact
substring of the fetched text and the licence is CC BY / CC0, otherwise it is null.

Usage (from repo root):
    python scripts/nature/extract_mechanisms.py --dois dois.txt [--fetch-text] [--data-dir PATH]
Needs GEMINI_API_KEY (or GOOGLE_API_KEY); without a key it prints a message and exits 0.
Optional env OPENALEX_API_KEY.
"""

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _http import fetch_json  # noqa: E402
from _files import read_json_list, write_json_atomic  # noqa: E402
from app.models.nature import LibraryRecord  # noqa: E402
from app.services.nature.store import DEFAULT_DIR  # noqa: E402
from app.services.rag_service import _api_key, _call_gemini  # noqa: E402

OPENALEX_URL = "https://api.openalex.org/works/doi:"
SELECT = "id,doi,title,publication_year,topics,open_access,primary_location,best_oa_location"
CONCURRENCY = 2
MAX_RETRIES = 4
MAX_TEXT_CHARS = 20000
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
# OpenAlex licence string -> stored licence. Everything else (by-sa, nc, nd, unknown) is not allowed.
ALLOWED_LICENCES = {"cc-by": "CC-BY", "cc0": "CC0"}
EXTRACTED_BY = "gemini extract_mechanisms v0"

FetchJson = Callable[[str, Optional[dict]], Optional[dict]]
FetchText = Callable[[str], str]

PROMPT = """You extract ONE candidate record for a nature-inspired design library from the
source below. Write the summary, trait, structure and mechanism in your own words (1-4 sentences
for the summary); never copy text. Use null for anything the source does not state. Do not
invent numbers, organisms or species.

Return a single JSON object with exactly these keys:
kind ("mechanism"|"material"|"process"|"practice"), title, summary, areas, functions,
sector_tags, organism ({{"scientific_name","common_names":[]}} or null), trait, structure,
mechanism (required when kind is "mechanism"), trait_type
("morphological"|"biochemical"|"genetic"|"behavioural"|"ecological"|"not_applicable"),
performance ([{{"metric","value" (number or null),"units","measured_in":"literature"}}]),
known_products ([]), popular_claim_note (or null), confidence ("low"|"medium"|"high"),
caveat (non-empty: limits and what is not shown), supporting_sentence (one sentence copied
verbatim from the TEXT section, or null; null when there is no TEXT section).

Allowed ids. areas: {areas}. functions: {functions}. sector_tags: {sectors}.
Use only ids from these lists.

SOURCE
Title: {title}
Year: {year}
Topics: {topics}
{text_block}"""


# ── Pure helpers ──────────────────────────────────────────────────────────────


def normalise_doi(raw: str) -> str:
    doi = raw.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    return doi.lower()


def allowed_licence(openalex_licence: str | None) -> str | None:
    """Stored licence string for a CC BY / CC0 OpenAlex licence, else None."""
    return ALLOWED_LICENCES.get((openalex_licence or "").strip().lower())


def work_licence(work: dict) -> tuple[str | None, str | None]:
    """(allowed stored licence or None, OA url) from best_oa_location / primary_location."""
    for key in ("best_oa_location", "primary_location"):
        loc = work.get(key) or {}
        lic = allowed_licence(loc.get("license"))
        if lic:
            return lic, loc.get("pdf_url") or loc.get("landing_page_url")
    return None, None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def fetch_oa_text(url: str, transport=None) -> str:
    """Fetch an OA page as plain text; PDFs only if pdfplumber is importable.

    Only http/https URLs; the body is streamed and capped at MAX_DOWNLOAD_BYTES. Returns ''
    on any failure and prints the reason.
    """
    import httpx

    if urlparse(url).scheme.lower() not in ("http", "https"):
        print(f"SKIP text fetch {url}: only http/https URLs are allowed", file=sys.stderr)
        return ""
    try:
        body = bytearray()
        with httpx.Client(timeout=30.0, follow_redirects=True, transport=transport) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "").lower()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_DOWNLOAD_BYTES:
                        print(f"SKIP text fetch {url}: over {MAX_DOWNLOAD_BYTES} bytes", file=sys.stderr)
                        return ""
    except Exception as exc:
        print(f"SKIP text fetch {url}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return ""
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        try:
            import io

            import pdfplumber
        except ImportError:
            print(f"SKIP text fetch {url}: PDF but pdfplumber is not installed", file=sys.stderr)
            return ""
        try:
            with pdfplumber.open(io.BytesIO(bytes(body))) as pdf:
                text = " ".join((p.extract_text() or "") for p in pdf.pages)
            return re.sub(r"\s+", " ", text).strip()
        except Exception as exc:
            print(f"SKIP text fetch {url}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return ""
    return html_to_text(bytes(body).decode("utf-8", errors="replace"))


def build_prompt(work: dict, text: str, taxonomy: dict) -> str:
    topics = ", ".join(t.get("display_name", "") for t in (work.get("topics") or [])[:5])
    text_block = f"TEXT (open licence)\n{text[:MAX_TEXT_CHARS]}\n" if text else "(no text available)\n"
    return PROMPT.format(
        areas=[a["id"] for a in taxonomy.get("areas", [])],
        functions=[f["id"] for f in taxonomy.get("functions", [])],
        sectors=[s["id"] for s in taxonomy.get("sectors", [])],
        title=work.get("title") or "",
        year=work.get("publication_year") or "unknown",
        topics=topics or "none",
        text_block=text_block,
    )


def build_record(
    raw: dict, work: dict, doi: str, licence: str | None, text: str, stg_id: str, taxonomy: dict
) -> LibraryRecord:
    """Turn the model output into a validated staged record; raises on anything invalid.

    The pipeline owns id, provenance, evidence, legal_review and consent. The supporting
    sentence is kept only for an open licence and when it is an exact substring of the text.
    """
    rec = dict(raw)
    sentence = rec.pop("supporting_sentence", None)
    if not (licence and text and isinstance(sentence, str) and sentence.strip() and sentence in text):
        sentence = None
    for key, field in (("areas", "areas"), ("functions", "functions"), ("sector_tags", "sectors")):
        known = {x["id"] for x in taxonomy.get(field, [])}
        unknown = [v for v in rec.get(key) or [] if v not in known]
        if unknown:
            raise ValueError(f"unknown {key}: {unknown}")
    # Model-owned fields we do not trust: identifiers are filled by verify_sources, the rest is human-set.
    if isinstance(rec.get("organism"), dict):
        rec["organism"] = {**rec["organism"], "gbif_usage_key": None, "gbif_match_type": None}
    if isinstance(rec.get("performance"), list):
        rec["performance"] = [
            {**p, "measured_in": "literature"} if isinstance(p, dict) else p for p in rec["performance"]
        ]
    for key in ("see_also", "contributors", "source_region"):
        rec.pop(key, None)
    title = work.get("title") or ""
    year = work.get("publication_year")
    rec.update(
        id=stg_id,
        knowledge_source="peer_reviewed",
        legal_review="pending" if rec.get("trait_type") in ("biochemical", "genetic") else "not_required",
        consent="not_applicable",
        evidence=[
            {
                "citation": f"{title} ({year})" if year else title,
                "doi": doi,
                "url": f"https://doi.org/{doi}",
                "year": year,
                "open_access": bool((work.get("open_access") or {}).get("is_oa")),
                "licence": licence,
                "supporting_sentence": sentence,
                "verified": False,
            }
        ],
        provenance={
            "status": "ai_extracted",
            "extracted_by": EXTRACTED_BY,
            "extracted_on": date.today().isoformat(),
        },
    )
    return LibraryRecord.model_validate(rec)


def next_stg_id(staged: list[dict]) -> str:
    nums = [int(m.group(1)) for r in staged if (m := re.fullmatch(r"stg-(\d+)", r.get("id", "")))]
    return f"stg-{max(nums, default=0) + 1:04d}"


# ── Pipeline ──────────────────────────────────────────────────────────────────


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "quota" in msg or "resource_exhausted" in msg


async def _extract_json(api_key: str, prompt: str) -> dict:
    for attempt in range(MAX_RETRIES):
        try:
            data, _model = await _call_gemini(api_key, prompt)
            return data
        except Exception as exc:
            if _is_rate_limit(exc) and attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2**attempt * 5)
                continue
            raise
    raise RuntimeError("unreachable")


async def extract_all(
    dois: list[str],
    data_dir: Path,
    api_key: str,
    taxonomy: dict,
    fetch: FetchJson = fetch_json,
    fetch_text: FetchText = fetch_oa_text,
    with_text: bool = False,
) -> dict:
    """Extract every DOI; returns counts and a list of (doi, reason) drops."""
    staging_path = data_dir / "library_staging.json"
    staged = read_json_list(staging_path)
    records = staged + read_json_list(data_dir / "library.json")
    seen = {normalise_doi(e["doi"]) for r in records for e in r.get("evidence", []) if e.get("doi")}

    sem = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()
    result = {"staged": 0, "dropped": [], "skipped_existing": 0}
    loop = asyncio.get_running_loop()
    params = {"select": SELECT}
    if os.environ.get("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]

    async def one(doi: str) -> None:
        if doi in seen:
            result["skipped_existing"] += 1
            return
        async with sem:
            try:
                url = OPENALEX_URL + quote(doi, safe="/()")
                work = await loop.run_in_executor(None, fetch, url, params)
                if not work:
                    result["dropped"].append((doi, "not found on OpenAlex"))
                    return
                licence, oa_url = work_licence(work)
                text = ""
                if with_text and licence and oa_url:
                    text = (await loop.run_in_executor(None, fetch_text, oa_url))[:MAX_TEXT_CHARS]
                raw = await _extract_json(api_key, build_prompt(work, text, taxonomy))
                if not isinstance(raw, dict):
                    raise ValueError("model output is not a JSON object")
                async with lock:
                    rec = build_record(raw, work, doi, licence, text, next_stg_id(staged), taxonomy)
                    staged.append(rec.model_dump(mode="json"))
                    write_json_atomic(staging_path, staged)
                    seen.add(doi)
                    result["staged"] += 1
            except Exception as exc:
                result["dropped"].append((doi, f"{type(exc).__name__}: {exc}"))

    await asyncio.gather(*(one(d) for d in dois))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dois", type=Path, required=True, help="text file, one DOI per line")
    parser.add_argument("--fetch-text", action="store_true", help="fetch CC BY/CC0 OA full text")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args(argv)

    api_key = _api_key()
    if not api_key:
        print("GEMINI_API_KEY (or GOOGLE_API_KEY) is not set: nothing extracted.")
        return 0
    try:
        lines = args.dois.read_text(encoding="utf-8").splitlines()
        taxonomy = json.loads((args.data_dir / "taxonomy.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    dois = list(dict.fromkeys(normalise_doi(x) for x in lines if x.strip() and not x.startswith("#")))

    result = asyncio.run(extract_all(dois, args.data_dir, api_key, taxonomy, with_text=args.fetch_text))
    for doi, reason in result["dropped"]:
        print(f"DROPPED {doi}: {reason}")
    print(
        f"dois={len(dois)} staged={result['staged']} dropped={len(result['dropped'])} "
        f"skipped_existing={result['skipped_existing']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
