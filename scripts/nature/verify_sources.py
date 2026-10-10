"""Verify nature library citations against Crossref and organisms against GBIF.

For each record:
  * every evidence.doi is looked up on Crossref; evidence.verified is set when the
    DOI resolves and the Crossref title shares >= 60% of its tokens with the citation.
    year, open_access and licence are filled from Crossref (only CC BY / CC0 count).
  * organism.scientific_name is matched on GBIF; usage key, match type and kingdom
    are filled only for EXACT/FUZZY matches with confidence >= 90.

Usage (from repo root):
    python scripts/nature/verify_sources.py [--data-dir PATH] [--dry-run] [--report out.json]
Set CROSSREF_MAILTO to use the Crossref polite pool. Always exits 0 (report tool).
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.models.nature import LibraryRecord  # noqa: E402
from app.services.nature.store import DEFAULT_DIR  # noqa: E402

CROSSREF_URL = "https://api.crossref.org/works/"
GBIF_URL = "https://api.gbif.org/v1/species/match"
TITLE_THRESHOLD = 0.6
GBIF_MIN_CONFIDENCE = 90
GBIF_ACCEPTED_TYPES = {"EXACT", "FUZZY"}

FetchJson = Callable[[str, Optional[dict]], Optional[dict]]


def fetch_json(url: str, params: dict | None = None) -> dict | None:
    """GET a JSON document; None on 404. Other HTTP errors raise."""
    import httpx

    resp = httpx.get(url, params=params, timeout=20.0, follow_redirects=True)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


# ── Pure decision functions ───────────────────────────────────────────────────


def _tokens(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c)).lower()
    return set(re.findall(r"[a-z0-9]+", folded))


def title_matches(crossref_title: str, citation: str, threshold: float = TITLE_THRESHOLD) -> bool:
    """True when >= threshold of the Crossref title's tokens appear in the citation."""
    title_tokens = _tokens(crossref_title)
    if not title_tokens:
        return False
    shared = len(title_tokens & _tokens(citation))
    return shared / len(title_tokens) >= threshold


_CC_RE = re.compile(r"creativecommons\.org/(licenses|publicdomain)/([a-z\-]+)/(\d+\.\d+)", re.I)


def licence_from_crossref(licenses: list[dict] | None) -> str | None:
    """Open licence id from Crossref license[] (CC BY, BY-SA, CC0).

    NC/ND variants and anything else are not open for our purposes -> None.
    """
    for item in licenses or []:
        m = _CC_RE.search(item.get("URL", "") or "")
        if not m:
            continue
        kind, variant, version = m.group(1).lower(), m.group(2).lower(), m.group(3)
        if kind == "publicdomain" and variant == "zero":
            return "CC0-1.0"
        if kind == "licenses" and variant == "by":
            return f"CC-BY-{version}"
        if kind == "licenses" and variant == "by-sa":
            return f"CC-BY-SA-{version}"
    return None


def accept_gbif(match: dict | None) -> bool:
    if not match:
        return False
    return (
        match.get("matchType") in GBIF_ACCEPTED_TYPES
        and (match.get("confidence") or 0) >= GBIF_MIN_CONFIDENCE
        and match.get("usageKey") is not None
    )


def _crossref_year(message: dict) -> int | None:
    for key in ("issued", "published", "published-print", "published-online"):
        parts = (message.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


# ── Verification ──────────────────────────────────────────────────────────────


def verify_evidence(ev: dict, fetch: FetchJson, mailto: str | None) -> tuple[dict, str | None]:
    """Return (updated evidence dict, failure reason or None)."""
    out = dict(ev)
    params = {"mailto": mailto} if mailto else None
    try:
        data = fetch(CROSSREF_URL + quote(ev["doi"], safe="/()"), params)
    except Exception as exc:  # network / HTTP error: report, do not crash
        out["verified"] = False
        return out, f"Crossref error: {exc}"
    message = (data or {}).get("message")
    if not message:
        out["verified"] = False
        return out, "DOI not found on Crossref"
    title = (message.get("title") or [""])[0]
    if not title_matches(title, ev.get("citation", "")):
        out["verified"] = False
        return out, f"title mismatch: Crossref says {title!r}"
    out["verified"] = True
    year = _crossref_year(message)
    if year:
        out["year"] = year
    licence = licence_from_crossref(message.get("license"))
    out["licence"] = licence
    out["open_access"] = licence is not None
    return out, None


def match_organism(org: dict, fetch: FetchJson) -> tuple[dict, str]:
    """Return (updated organism dict, outcome: matched | needs_review | error)."""
    out = dict(org)
    try:
        match = fetch(GBIF_URL, {"name": org["scientific_name"]})
    except Exception:
        return out, "error"
    if not accept_gbif(match):
        return out, "needs_review"
    out["gbif_usage_key"] = match["usageKey"]
    out["gbif_match_type"] = match["matchType"]
    if match.get("kingdom"):
        out["kingdom"] = match["kingdom"]
    return out, "matched"


def verify_library(
    records: list[dict],
    fetch: FetchJson = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    mailto: str | None = None,
    delay: float = 0.1,
) -> tuple[list[dict], dict]:
    """Return (updated records in the same order, report dict)."""
    report: dict = {
        "records": len(records),
        "dois_checked": 0,
        "verified": 0,
        "failed": [],
        "organisms_matched": 0,
        "needs_review": [],
        "invalid": [],
    }
    updated = []
    for rec in records:
        new = json.loads(json.dumps(rec))
        for i, ev in enumerate(new.get("evidence", [])):
            if not ev.get("doi"):
                continue
            report["dois_checked"] += 1
            new["evidence"][i], reason = verify_evidence(ev, fetch, mailto)
            sleep(delay)
            if reason is None:
                report["verified"] += 1
            else:
                report["failed"].append({"id": rec["id"], "doi": ev["doi"], "reason": reason})
        org = new.get("organism")
        if org and org.get("scientific_name"):
            new["organism"], outcome = match_organism(org, fetch)
            sleep(delay)
            if outcome == "matched":
                report["organisms_matched"] += 1
            else:
                report["needs_review"].append(
                    {"id": rec["id"], "scientific_name": org["scientific_name"], "outcome": outcome}
                )
        try:
            LibraryRecord.model_validate(new)
        except Exception as exc:
            report["invalid"].append({"id": rec["id"], "error": str(exc)})
            new = rec  # keep the original rather than write an invalid record
        updated.append(new)
    return updated, report


def summary_line(report: dict) -> str:
    return (
        f"records={report['records']} dois_checked={report['dois_checked']} "
        f"verified={report['verified']} failed={len(report['failed'])} "
        f"organisms_matched={report['organisms_matched']} "
        f"needs_review={len(report['needs_review'])}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--dry-run", action="store_true", help="do not write library.json")
    parser.add_argument("--report", type=Path, help="write the report as JSON to this path")
    args = parser.parse_args(argv)

    path = args.data_dir / "library.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    updated, report = verify_library(records, mailto=os.environ.get("CROSSREF_MAILTO"))

    for item in report["failed"]:
        print(f"FAILED {item['id']} {item['doi']}: {item['reason']}")
    for item in report["needs_review"]:
        print(f"REVIEW {item['id']} {item['scientific_name']}: {item['outcome']}")
    for item in report["invalid"]:
        print(f"INVALID {item['id']}: {item['error']}")

    if not args.dry_run:
        path.write_text(
            json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    if args.report:
        args.report.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(summary_line(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
