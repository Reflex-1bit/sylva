"""Validate the nature library and industry map; print stats. Exit 1 on any error.

Usage (from repo root):
    python scripts/nature/validate_db.py [--markdown] [--data-dir PATH]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.nature.store import DEFAULT_DIR, NatureDataError, NatureStore  # noqa: E402


def _counts(counter: dict, order: list[str] | None = None, label=None) -> str:
    """'n key, ...' in the given order (missing keys count 0), else by count."""
    keys = order or sorted(counter, key=lambda k: -counter[k])
    return ", ".join(label(k, counter.get(k, 0)) if label else f"{counter.get(k, 0)} {k}" for k in keys)


def _markdown(stats: dict) -> str:
    """The coverage table of data/nature/README.md."""
    plural = lambda t, n: f"{n} {'companies' if t == 'company' else t + 's'}"  # noqa: E731
    named = lambda k, n: f"{k} {n}"  # noqa: E731
    rows = [
        ("Library records", stats["library_total"]),
        ("Served by the API", stats["library_served"]),
        ("Quarantined (never served)", stats["quarantined"]),
        ("Provenance (served records)",
         _counts(stats["by_status"], ["ai_extracted", "disputed", "expert_validated"])),
        ("Records with a measured value",
         f"{stats['with_measured_values']} ({stats['measured_share'] * 100:.1f}%)"),
        ("Records by kind (served)",
         _counts(stats["by_kind"], ["mechanism", "material", "process", "practice"])),
        ("Records by area (served)",
         _counts(stats["by_area"], label=named) + " (a record can have several areas)"),
        ("Map records", f"{stats['map_total']}: " + _counts(stats["map_by_type"], label=plural)),
        ("Map by country", _counts(stats["map_by_country"], label=named)),
        ("Map by sector", _counts(stats["map_by_sector"], list(stats["map_by_sector"]), named)),
    ]
    return "\n".join(["| Metric | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", action="store_true", help="print stats as a markdown table")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args(argv)

    try:
        stats = NatureStore(args.data_dir).stats()
    except (NatureDataError, FileNotFoundError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    if args.markdown:
        print(_markdown(stats))
    else:
        for key, value in stats.items():
            print(f"{key}: {value}")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
