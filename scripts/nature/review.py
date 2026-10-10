"""Human review CLI for the nature library.

    python scripts/nature/review.py [--data-dir PATH] <command>

    list                          staged records and their status
    show <id>                     print a staged (stg-) or library (lib-) record; logs the open time
    promote <stg-id> --by NAME    move a staged record into library.json under the next lib- id
    validate <lib-id> --by NAME   mark a library record expert_validated
    dispute <lib-id> --by NAME --reason TEXT
                                  mark a library record disputed and append the reason to caveat
    timing [--json]               median minutes from the latest `show` to each validate/dispute

Every action appends one line to review_log.jsonl. library_staging.json and review_log.jsonl
are created on demand under --data-dir. Exits non-zero on errors.
"""

import argparse
import json
import re
import statistics
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _files import read_json_list, write_json_atomic  # noqa: E402
from app.models.nature import LibraryRecord  # noqa: E402
from app.services.nature.store import DEFAULT_DIR  # noqa: E402

LOG_NAME = "review_log.jsonl"
STAGING_NAME = "library_staging.json"
LIBRARY_NAME = "library.json"


class ReviewError(Exception):
    """A user-facing failure; the CLI prints it and exits 1."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def log_action(data_dir: Path, action: str, record_id: str, by: str | None = None, **extra) -> None:
    entry = {"ts": _now().isoformat(), "action": action, "id": record_id, "by": by, **extra}
    with (data_dir / LOG_NAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_taxonomy_ids(data_dir: Path) -> dict[str, set[str]] | None:
    path = data_dir / "taxonomy.json"
    if not path.exists():
        return None
    tax = json.loads(path.read_text(encoding="utf-8"))
    return {k: {x["id"] for x in tax.get(k, [])} for k in ("areas", "functions", "sectors")}


def _check_taxonomy(rec: LibraryRecord, ids: dict[str, set[str]] | None) -> None:
    if ids is None:
        return
    for field, key in (("areas", "areas"), ("functions", "functions"), ("sector_tags", "sectors")):
        unknown = [v for v in getattr(rec, field) if v not in ids[key]]
        if unknown:
            raise ReviewError(f"{rec.id}: unknown {field} {unknown}")


def _find(records: list[dict], rec_id: str) -> int | None:
    return next((i for i, r in enumerate(records) if r.get("id") == rec_id), None)


def _library_record(data_dir: Path, lib_id: str) -> tuple[list[dict], int]:
    if not lib_id.startswith("lib-"):
        raise ReviewError(f"{lib_id}: validate/dispute act on library records (lib-NNNN) only")
    library = read_json_list(data_dir / LIBRARY_NAME)
    idx = _find(library, lib_id)
    if idx is None:
        raise ReviewError(f"unknown library id {lib_id}")
    return library, idx


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_list(data_dir: Path) -> int:
    staged = read_json_list(data_dir / STAGING_NAME)
    if not staged:
        print("No staged records.")
        return 0
    for r in staged:
        print(f"{r['id']}  [{r.get('kind')}]  {r.get('title')}  ({r['provenance']['status']})")
    print(f"{len(staged)} staged record(s).")
    return 0


def cmd_show(data_dir: Path, rec_id: str) -> int:
    source = STAGING_NAME if rec_id.startswith("stg-") else LIBRARY_NAME
    records = read_json_list(data_dir / source)
    idx = _find(records, rec_id)
    if idx is None:
        raise ReviewError(f"unknown id {rec_id}")
    print(json.dumps(records[idx], indent=2, ensure_ascii=False))
    log_action(data_dir, "show", rec_id)
    return 0


def next_lib_id(library: list[dict]) -> str:
    nums = [int(m.group(1)) for r in library if (m := re.fullmatch(r"lib-(\d+)", r.get("id", "")))]
    return f"lib-{max(nums, default=0) + 1:04d}"


def _duplicate_in_library(staged_rec: dict, library: list[dict]) -> str | None:
    """Id of the library record with the same DOI (or the same title when the staged one has no DOI)."""
    dois = {e["doi"].lower() for e in staged_rec.get("evidence", []) if e.get("doi")}
    title = (staged_rec.get("title") or "").strip().lower()
    for r in library:
        if dois:
            if dois & {e["doi"].lower() for e in r.get("evidence", []) if e.get("doi")}:
                return r["id"]
        elif title and (r.get("title") or "").strip().lower() == title:
            return r["id"]
    return None


def cmd_promote(data_dir: Path, stg_id: str, by: str) -> int:
    staged = read_json_list(data_dir / STAGING_NAME)
    idx = _find(staged, stg_id)
    if idx is None:
        raise ReviewError(f"unknown staged id {stg_id}")
    library = read_json_list(data_dir / LIBRARY_NAME)

    dup = _duplicate_in_library(staged[idx], library)
    if dup:  # a previous promote wrote the library but crashed before cleaning staging
        del staged[idx]
        write_json_atomic(data_dir / STAGING_NAME, staged)
        log_action(data_dir, "promote_dedup", stg_id, by, library_id=dup)
        print(f"{stg_id} is already in the library as {dup}; removed from staging")
        return 0

    rec = dict(staged[idx])
    rec["provenance"] = {
        **rec.get("provenance", {}),
        "status": "ai_extracted",
        "validated_by": None,
        "validated_on": None,
    }
    rec["id"] = next_lib_id(library)
    if rec.get("trait_type") in ("biochemical", "genetic"):
        rec["legal_review"] = "pending"
    if rec.get("knowledge_source") == "traditional" and rec.get("consent") == "not_applicable":
        rec["consent"] = "pending"
    try:
        model = LibraryRecord.model_validate(rec)
    except Exception as exc:
        raise ReviewError(f"{stg_id} fails validation, not promoted: {exc}") from exc
    _check_taxonomy(model, _load_taxonomy_ids(data_dir))

    library.append(model.model_dump(mode="json"))
    write_json_atomic(data_dir / LIBRARY_NAME, library)
    del staged[idx]
    write_json_atomic(data_dir / STAGING_NAME, staged)
    log_action(data_dir, "promote", stg_id, by, library_id=model.id)
    note = " (legal_review pending: quarantined)" if model.legal_review == "pending" else ""
    print(f"Promoted {stg_id} -> {model.id}{note}")
    return 0


def cmd_validate(data_dir: Path, lib_id: str, by: str) -> int:
    library, idx = _library_record(data_dir, lib_id)
    rec = dict(library[idx])
    rec["provenance"] = {
        **rec["provenance"],
        "status": "expert_validated",
        "validated_by": by,
        "validated_on": date.today().isoformat(),
    }
    LibraryRecord.model_validate(rec)
    library[idx] = rec
    write_json_atomic(data_dir / LIBRARY_NAME, library)
    log_action(data_dir, "validate", lib_id, by)
    print(f"{lib_id} marked expert_validated by {by}")
    return 0


def cmd_dispute(data_dir: Path, lib_id: str, by: str, reason: str) -> int:
    library, idx = _library_record(data_dir, lib_id)
    rec = dict(library[idx])
    rec["provenance"] = {**rec["provenance"], "status": "disputed"}
    rec["caveat"] = f"{rec['caveat'].rstrip()} Disputed by {by}: {reason}"
    LibraryRecord.model_validate(rec)
    library[idx] = rec
    write_json_atomic(data_dir / LIBRARY_NAME, library)
    log_action(data_dir, "dispute", lib_id, by, reason=reason)
    print(f"{lib_id} marked disputed by {by}")
    return 0


def compute_timing(entries: list[dict]) -> dict:
    """Median minutes from the most recent `show` before a record's last validate/dispute.

    Records with a decision but no earlier show are skipped and counted.
    """
    parsed = []
    for e in entries:
        try:
            parsed.append({**e, "_t": datetime.fromisoformat(e["ts"])})
        except (KeyError, ValueError):
            continue
    parsed.sort(key=lambda e: e["_t"])

    shows: dict[str, list[datetime]] = {}
    last_decision: dict[str, dict] = {}
    for e in parsed:
        if e.get("action") == "show":
            shows.setdefault(e["id"], []).append(e["_t"])
        elif e.get("action") in ("validate", "dispute"):
            last_decision[e["id"]] = e

    per_record = {}
    skipped = []
    for rec_id, decision in last_decision.items():
        earlier = [t for t in shows.get(rec_id, []) if t <= decision["_t"]]
        if not earlier:
            skipped.append(rec_id)
            continue
        per_record[rec_id] = round((decision["_t"] - max(earlier)).total_seconds() / 60, 2)
    median = round(statistics.median(per_record.values()), 2) if per_record else None
    return {
        "records_measured": len(per_record),
        "records_skipped_no_show": len(skipped),
        "skipped_ids": sorted(skipped),
        "median_minutes": median,
        "per_record_minutes": per_record,
    }


def cmd_timing(data_dir: Path, as_json: bool) -> int:
    log = data_dir / LOG_NAME
    entries = []
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    result = compute_timing(entries)
    if as_json:
        print(json.dumps(result, indent=2))
        return 0
    if result["median_minutes"] is None:
        print("No validate/dispute actions with a preceding show.")
    else:
        print(f"Median minutes from show to validate/dispute: {result['median_minutes']}")
    print(f"Records measured: {result['records_measured']}")
    print(f"Records skipped (no show): {result['records_skipped_no_show']}")
    for rec_id, minutes in result["per_record_minutes"].items():
        print(f"  {rec_id}: {minutes} min")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("show").add_argument("id")
    p = sub.add_parser("promote")
    p.add_argument("id")
    p.add_argument("--by", required=True)
    p = sub.add_parser("validate")
    p.add_argument("id")
    p.add_argument("--by", required=True)
    p = sub.add_parser("dispute")
    p.add_argument("id")
    p.add_argument("--by", required=True)
    p.add_argument("--reason", required=True)
    sub.add_parser("timing").add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    d = args.data_dir
    try:
        if args.command == "list":
            return cmd_list(d)
        if args.command == "show":
            return cmd_show(d, args.id)
        if args.command == "promote":
            return cmd_promote(d, args.id, args.by)
        if args.command == "validate":
            return cmd_validate(d, args.id, args.by)
        if args.command == "dispute":
            return cmd_dispute(d, args.id, args.by, args.reason)
        return cmd_timing(d, args.json)
    except (ReviewError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
