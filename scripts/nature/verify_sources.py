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
    """GET a JSON document; None on 404.

    Retries timeouts, 429 (honouring Retry-After) and 5xx up to 3 attempts with
    exponential backoff; raises after the last attempt.
    """
    import httpx

    attempts = 3
    for attempt in range(attempts):
        last = attempt == attempts - 1
        wait = 2.0**attempt
        try:
            resp = httpx.get(url, params=params, timeout=20.0, follow_redirects=True)
        except httpx.TransportError:
            if last:
                raise
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            return None
        if resp.status_code == 429 or resp.status_code >= 500:
            if last:
                resp.raise_for_status()
            retry_after = resp.headers.get("Retry-After", "")
            time.sleep(min(float(retry_after), 30.0) if retry_after.isdigit() else wait)
            continue
        resp.raise_for_status()
        return resp.json()
    return None  # unreachable


# ── Pure decision functions ───────────────────────────────────────────────────


def _tokens(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", re.sub(r"<[^>]+>", "", text or ""))
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
    for key in ("published-print", "issued", "published-online", "created"):
        parts = (message.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


# ── Verification ──────────────────────────────────────────────────────────────

NOT_FOUND = "not_found"  # DOI missing / title mismatch: a real verification failure
ERROR = "error"  # network / HTTP problem: says nothing about the DOI


def verify_evidence(
    ev: dict, fetch: FetchJson, mailto: str | None
) -> tuple[dict, str | None, str | None]:
    """Return (updated evidence dict, category or None, reason or None).

    On an ERROR the evidence is returned unchanged.
    """
    out = dict(ev)
    params = {"mailto": mailto} if mailto else None
    try:
        data = fetch(CROSSREF_URL + quote(ev["doi"], safe="/()"), params)
    except Exception as exc:
        return out, ERROR, f"Crossref error: {exc}"
    message = (data or {}).get("message")
    if not message:
        out["verified"] = False
        return out, NOT_FOUND, "DOI not found on Crossref"
    title = (message.get("title") or [""])[0]
    if not title_matches(title, ev.get("citation", "")):
        out["verified"] = False
        return out, NOT_FOUND, f"title mismatch: Crossref says {title!r}"
    out["verified"] = True
    year = _crossref_year(message)
    if year:
        out["year"] = year
    licenses = message.get("license")
    if licenses:  # no licence info from Crossref: keep what the record already says
        licence = licence_from_crossref(licenses)
        out["licence"] = licence
        out["open_access"] = licence is not None
    return out, None, None


def match_organism(org: dict, fetch: FetchJson) -> tuple[dict, str, str | None]:
    """Return (updated organism, outcome: matched | needs_review | error, error message)."""
    out = dict(org)
    try:
        match = fetch(GBIF_URL, {"name": org["scientific_name"]})
    except Exception as exc:
        return out, ERROR, str(exc)
    if not accept_gbif(match):
        return out, "needs_review", None
    out["gbif_usage_key"] = match["usageKey"]
    out["gbif_match_type"] = match["matchType"]
    if match.get("kingdom"):
        out["kingdom"] = match["kingdom"]
    return out, "matched", None


def verify_library(
    records: list[dict],
    fetch: FetchJson = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    mailto: str | None = None,
    delay: float = 0.1,
) -> tuple[list[dict], dict]:
    """Return (updated records in the same order, report dict).

    Counts and failure lists cover only records whose update was actually kept;
    records that fail re-validation are listed under "invalid" and left untouched.
    """
    report: dict = {
        "records": len(records),
        "dois_checked": 0,
        "verified": 0,
        "failed": [],
        "errors": [],
        "organisms_matched": 0,
        "needs_review": [],
        "invalid": [],
    }
    cache: dict = {}

    def cached_fetch(url: str, params: dict | None = None):
        key = (url, json.dumps(params, sort_keys=True))
        if key not in cache:
            cache[key] = fetch(url, params)  # errors propagate and are not cached
            sleep(delay)
        return cache[key]

    updated = []
    for rec in records:
        new = json.loads(json.dumps(rec))
        local = {"dois_checked": 0, "verified": 0, "organisms_matched": 0,
                 "failed": [], "errors": [], "needs_review": []}
        for i, ev in enumerate(new.get("evidence", [])):
            if not ev.get("doi"):
                continue
            local["dois_checked"] += 1
            new["evidence"][i], category, reason = verify_evidence(ev, cached_fetch, mailto)
            if category is None:
                local["verified"] += 1
            elif category == ERROR:
                local["errors"].append({"id": rec["id"], "doi": ev["doi"], "reason": reason})
            else:
                local["failed"].append({"id": rec["id"], "doi": ev["doi"], "reason": reason})
        org = new.get("organism")
        if org and org.get("scientific_name"):
            name = org["scientific_name"]
            new["organism"], outcome, message = match_organism(org, cached_fetch)
            if outcome == "matched":
                local["organisms_matched"] += 1
            elif outcome == ERROR:
                local["errors"].append({"id": rec["id"], "scientific_name": name, "reason": f"GBIF error: {message}"})
            else:
                local["needs_review"].append({"id": rec["id"], "scientific_name": name, "outcome": outcome})
        try:
            LibraryRecord.model_validate(new)
        except Exception as exc:
            report["invalid"].append({"id": rec["id"], "error": str(exc)})
            updated.append(rec)  # keep the original rather than write an invalid record
            continue
        for k in ("dois_checked", "verified", "organisms_matched"):
            report[k] += local[k]
        for k in ("failed", "errors", "needs_review"):
            report[k].extend(local[k])
        updated.append(new)
    return updated, report


def summary_line(report: dict) -> str:
    return (
        f"records={report['records']} dois_checked={report['dois_checked']} "
        f"verified={report['verified']} failed={len(report['failed'])} "
        f"errors={len(report['errors'])} "
        f"organisms_matched={report['organisms_matched']} "
        f"needs_review={len(report['needs_review'])} invalid={len(report['invalid'])}"
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
    for item in report["errors"]:
        print(f"ERROR {item['id']} {item.get('doi') or item.get('scientific_name')}: {item['reason']}")
    for item in report["needs_review"]:
        print(f"REVIEW {item['id']} {item['scientific_name']}: {item['outcome']}")
    for item in report["invalid"]:
        print(f"INVALID {item['id']}: {item['error']}")

    if not args.dry_run:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    if args.report:
        args.report.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(summary_line(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
