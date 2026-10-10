"""Validate the nature library and industry map; print stats. Exit 1 on any error.

Usage (from repo root):
    python scripts/nature/validate_db.py [--markdown] [--data-dir PATH]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.nature.store import DEFAULT_DIR, NatureDataError, NatureStore  # noqa: E402


def _markdown(stats: dict) -> str:
    lines = ["| Metric | Value |", "|---|---|"]
    for key, value in stats.items():
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


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
