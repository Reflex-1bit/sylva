"""
Query the Sylva-wild index from the command line.

    python -m scripts.nature.wild.query "coating that stops ice forming on wind turbine blades"
    python -m scripts.nature.wild.query "cooling a building without air conditioning" --sector buildings -k 5
"""

import argparse
import sys
import time

from app.services.wild.index import WildIndex


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=8)
    ap.add_argument("--sector", default=None, help="soft boost for this sector id")
    args = ap.parse_args(argv)

    t0 = time.time()
    idx = WildIndex()
    t1 = time.time()
    hits = idx.search(args.query, k=args.k, sector=args.sector)
    t2 = time.time()
    print(f"{len(idx)} records, loaded in {t1 - t0:.1f}s, searched in {(t2 - t1) * 1000:.0f} ms\n")
    for n, h in enumerate(hits, 1):
        org = (h.get("organism") or {}).get("name")
        print(f"{n}. [{h['score']:.2f}] {h['title']} ({h.get('year', '?')}, {h['kind']}, {h['primary_sector']})")
        print(f"   {h['url']}   ranks bm25={h['ranks']['bm25']} dense={h['ranks']['dense']}"
              + (f"   organism={org}" if org else ""))
        for g in h["groups"]:
            print(f"   donate: {g['name']} {g['donate_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
