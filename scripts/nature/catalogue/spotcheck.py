"""Spot-check tooling for the rules-only sector sort (plan Phase 6, S8).

Usage (from repo root):
    python scripts/nature/catalogue/spotcheck.py sample [--n 200] [--seed 11] [--force]
    python scripts/nature/catalogue/spotcheck.py packets [--size 50]
    python scripts/nature/catalogue/spotcheck.py merge-verdicts reviewer.csv
    python scripts/nature/catalogue/spotcheck.py score [--checked-by "agent, owner-skimmed"]

This file only builds the tooling. Verdicts are filled by a separate reviewer (never by this script);
`merge-verdicts` copies a reviewer's answers into spotcheck.csv. No network access.
"""

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import BUILD_DIR, CATALOGUE_DIR, load_sectors  # noqa: E402

SPOT_DIR = CATALOGUE_DIR / "spotcheck"
STAGE_DIR = BUILD_DIR / "stage"

COLUMNS = [
    "id", "title", "url", "source", "kind", "primary_sector", "sector_tags", "sort_reason",
    "sort_confidence", "verdict_sector", "verdict_relevant", "note",
]
SECTOR_VERDICTS = {"ok", "tag", "wrong", "unsure"}
RELEVANT_VERDICTS = {"yes", "no", "unsure"}
CHECKED_BY_LABELS = ("agent, owner skim pending", "agent, owner-skimmed")

SCOPE_RULE = (
    "In scope = a design, material, process or system that learns from or copies a living thing "
    "(bio-inspired), or that uses nature itself to solve a societal problem (nature-based solution). "
    "Out of scope = generic green tech, plain ecology without an application, and computational "
    "metaheuristics named after animals."
)

# Same guard as app/routers/nature.py (_CSV_FORMULA_START / _csv_cell). Copied rather than imported,
# because importing the router pulls in the whole web app.
_CSV_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_START):
        return "'" + value  # stop spreadsheets reading the cell as a formula
    return str(value)


class SpotError(Exception):
    pass


# -- helpers -----------------------------------------------------------------


def stage_file(stage_dir: Path) -> Path:
    for name in ("grouped.jsonl", "sorted.jsonl"):
        p = stage_dir / name
        if p.exists():
            return p
    raise SpotError(f"no grouped.jsonl or sorted.jsonl in {stage_dir}")


def read_stage(path: Path, want_ids: Optional[set] = None) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            if want_ids is None or rec["id"] in want_ids:
                out.append(rec)
    return out


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLUMNS})


def has_verdicts(path: Path) -> bool:
    if not path.exists():
        return False
    return any(
        (r.get("verdict_sector") or "").strip() or (r.get("verdict_relevant") or "").strip()
        for r in read_csv(path)
    )


def _check_values(rows: list[dict]) -> None:
    for r in rows:
        vs = (r.get("verdict_sector") or "").strip()
        vr = (r.get("verdict_relevant") or "").strip()
        if vs and vs not in SECTOR_VERDICTS:
            raise SpotError(f"id {r.get('id')}: invalid verdict_sector {vs!r} (allowed: ok, tag, wrong, unsure)")
        if vr and vr not in RELEVANT_VERDICTS:
            raise SpotError(f"id {r.get('id')}: invalid verdict_relevant {vr!r} (allowed: yes, no, unsure)")


# -- sample ------------------------------------------------------------------


def allocate(sizes: dict[str, int], n: int) -> dict[str, int]:
    """Per-sector counts: max(5, round(n*share)) capped by size, then trimmed or topped up so the
    total is exactly n, moving the sector furthest from its proportional ideal first (largest
    remainder). Never goes below min(5, size) when trimming. Every record if fewer than n exist."""
    total = sum(sizes.values())
    if total <= n:
        return dict(sizes)
    ideal = {s: n * sz / total for s, sz in sizes.items()}
    counts = {s: min(sz, max(5, round(ideal[s]))) for s, sz in sizes.items()}
    floor = {s: min(5, sz) for s, sz in sizes.items()}
    while sum(counts.values()) > n:
        cands = [s for s in counts if counts[s] > floor[s]]
        if not cands:
            break  # the per-sector minimums alone exceed n
        s = max(cands, key=lambda k: (counts[k] - ideal[k], k))
        counts[s] -= 1
    while sum(counts.values()) < n:
        cands = [s for s in counts if counts[s] < sizes[s]]
        s = max(cands, key=lambda k: (ideal[k] - counts[k], k))
        counts[s] += 1
    return counts


def draw_sample(records: list[dict], n: int, seed: int) -> list[dict]:
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_sector[r["primary_sector"]].append(r)
    counts = allocate({s: len(v) for s, v in by_sector.items()}, n)
    rng = random.Random(seed)
    picked: list[dict] = []
    for s in sorted(by_sector):
        pool = sorted(by_sector[s], key=lambda r: r["id"])
        picked.extend(rng.sample(pool, counts[s]) if counts[s] < len(pool) else pool)
    return picked


def to_row(r: dict) -> dict:
    conf = r.get("sort_confidence")
    return {
        "id": r["id"],
        "title": _csv_cell(r.get("title")),
        "url": r.get("url") or "",
        "source": r.get("source") or "",
        "kind": r.get("kind") or "",
        "primary_sector": r["primary_sector"],
        "sector_tags": "|".join(r.get("sector_tags") or []),
        "sort_reason": _csv_cell(r.get("sort_reason")),
        "sort_confidence": "" if conf is None else conf,
        "verdict_sector": "",
        "verdict_relevant": "",
        "note": "",
    }


def cmd_sample(args) -> int:
    out = args.dir / "spotcheck.csv"
    if has_verdicts(out) and not args.force:
        raise SpotError(f"{out} already has verdicts filled; pass --force to overwrite")
    src = stage_file(args.stage_dir)
    records = read_stage(src)
    picked = draw_sample(records, args.n, args.seed)
    write_csv(out, [to_row(r) for r in picked])
    sizes = Counter(r["primary_sector"] for r in records)
    got = Counter(r["primary_sector"] for r in picked)
    print(f"read {len(records)} records from {src.name}; wrote {len(picked)} rows to {out}")
    for s in sorted(sizes):
        print(f"  {s:34s} {got[s]:4d} of {sizes[s]}")
    return 0


# -- packets -----------------------------------------------------------------


def candidate_sectors(rec: dict, all_ids: list[str], seed: int) -> list[str]:
    own = [rec["primary_sector"]] + [t for t in (rec.get("sector_tags") or []) if t != rec["primary_sector"]]
    rng = random.Random(f"{seed}:{rec['id']}")
    others = [s for s in all_ids if s not in own]
    cands = own + rng.sample(others, min(2, len(others)))
    rng.shuffle(cands)
    return cands


def sector_definitions(sectors_dir: Optional[Path] = None) -> list[tuple[str, str, str]]:
    out = []
    for s in load_sectors(sectors_dir).sectors:
        desc = getattr(s, "description", None) or ("keywords: " + ", ".join(s.keywords_en[:8]))
        out.append((s.id, s.label_en, desc))
    return out


def _clip(text: str, limit: int = 1200) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " ..."


def cmd_packets(args) -> int:
    csv_path = args.dir / "spotcheck.csv"
    if not csv_path.exists():
        raise SpotError(f"{csv_path} not found; run sample first")
    rows = read_csv(csv_path)
    ids = [r["id"] for r in rows]
    recs = {r["id"]: r for r in read_stage(stage_file(args.stage_dir), set(ids))}
    missing = [i for i in ids if i not in recs]
    if missing:
        raise SpotError(f"{len(missing)} sample ids are not in the stage file, e.g. {missing[0]}")
    defs = sector_definitions(args.sectors_dir)
    all_ids = [d[0] for d in defs]
    order = list(ids)
    random.Random(f"{args.seed}:packets").shuffle(order)  # the CSV is grouped by sector; do not leak that
    pdir = args.dir / "packets"
    pdir.mkdir(parents=True, exist_ok=True)
    for old in pdir.glob("packet-*.md"):
        old.unlink()
    header = [
        "# Blind review packet", "", "## Scope rule", "", SCOPE_RULE, "", "## How to answer", "",
        "For each record give `chosen_sector` (ANY sector id from the definitions below, not only the "
        "candidates; `unsure` if you cannot tell) and `verdict_relevant` (`yes`, `no` or `unsure`, "
        "judged against the scope rule). Reply as a CSV with columns "
        "`id,chosen_sector,verdict_relevant,note`.", "", "## Sector definitions", "",
    ]
    header += [f"- `{sid}` - {label}: {desc}" for sid, label, desc in defs]
    paths = []
    for k, start in enumerate(range(0, len(order), args.size), 1):
        chunk = order[start:start + args.size]
        lines = list(header) + ["", f"## Records ({len(chunk)})", ""]
        for rid in chunk:
            rec = recs[rid]
            org = rec["organism"].get("name") if isinstance(rec.get("organism"), dict) else None
            cands = candidate_sectors(rec, all_ids, args.seed)
            lines += [
                f"### {rid}",
                f"- title: {' '.join((rec.get('title') or '').split())}",
                f"- url: {rec.get('url') or '(no url)'}",
                f"- summary: {_clip(rec['summary']) if rec.get('summary') else '(no summary)'}",
                f"- organism: {org or '(none)'}",
                f"- candidate sectors: {', '.join(cands)}",
                "",
            ]
        p = pdir / f"packet-{k}.md"
        p.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        paths.append(p)
    print(f"wrote {len(paths)} packets:")
    for p in paths:
        print(f"  {p}")
    return 0


# -- merge-verdicts ----------------------------------------------------------


def map_choice(chosen: str, primary: str, tags: list[str]) -> str:
    c = (chosen or "").strip()
    if not c or c.lower() == "unsure":
        return "unsure"
    if c == primary:
        return "ok"
    if c in tags:
        return "tag"
    return "wrong"


def cmd_merge(args) -> int:
    csv_path = args.dir / "spotcheck.csv"
    rows = read_csv(csv_path)
    by_id = {r["id"]: r for r in rows}
    rev = read_csv(Path(args.file))
    unknown = [r.get("id") for r in rev if r.get("id") not in by_id]
    if unknown:
        raise SpotError(f"unknown ids in reviewer file: {', '.join(map(str, unknown[:10]))}")
    for r in rev:
        vr = (r.get("verdict_relevant") or "").strip()
        if vr and vr not in RELEVANT_VERDICTS:
            raise SpotError(f"id {r['id']}: invalid verdict_relevant {vr!r} (allowed: yes, no, unsure)")
    for r in rev:
        row = by_id[r["id"]]
        tags = [t for t in (row.get("sector_tags") or "").split("|") if t]
        row["verdict_sector"] = map_choice(r.get("chosen_sector"), row["primary_sector"], tags)
        row["verdict_relevant"] = (r.get("verdict_relevant") or "").strip()
        row["note"] = _csv_cell(r.get("note") or "")
    write_csv(csv_path, rows)
    print(f"merged {len(rev)} verdicts into {csv_path}")
    return 0


# -- score -------------------------------------------------------------------


def _ratio(num: int, den: int) -> Optional[float]:
    return round(num / den, 4) if den else None


def _stats(c: Counter) -> dict:
    sec = c["ok"] + c["tag"] + c["wrong"]
    rel = c["yes"] + c["no"]
    return {
        "n": sec,
        "precision": _ratio(c["ok"], sec),
        "lenient_precision": _ratio(c["ok"] + c["tag"], sec),
        "relevance": _ratio(c["yes"], rel),
        "n_relevance": rel,
    }


def compute_scores(rows: list[dict]) -> dict:
    _check_values(rows)
    per: dict[str, Counter] = defaultdict(Counter)
    total = Counter()
    scored = 0
    for r in rows:
        vs = (r.get("verdict_sector") or "").strip()
        if not vs:
            continue
        scored += 1
        vr = (r.get("verdict_relevant") or "").strip()
        for c in (per[r["primary_sector"]], total):
            if vs != "unsure":
                c[vs] += 1
            if vr and vr != "unsure":
                c[vr] += 1
    sectors = {s: _stats(c) for s, c in sorted(per.items())}
    below = [s for s, st in sectors.items() if st["n"] >= 5 and st["precision"] is not None and st["precision"] < 0.70]
    return {"scored": scored, "unscored": len(rows) - scored, "overall": _stats(total),
            "sectors": sectors, "below_70": below}


def _pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{x * 100:5.1f}%"


def cmd_score(args) -> int:
    if args.checked_by not in CHECKED_BY_LABELS:
        raise SpotError(f"--checked-by must be one of {CHECKED_BY_LABELS}")
    rows = read_csv(args.dir / "spotcheck.csv")
    res = compute_scores(rows)
    out = {
        "checked_by": args.checked_by,
        "sample_size": len(rows),
        "seed": args.seed,
        "scored_on": date.today().isoformat(),
        "overall": res["overall"],
        "sectors": res["sectors"],
        "below_70": res["below_70"],
    }
    (args.dir / "results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{'sector':34s} {'n':>4s} {'prec':>7s} {'lenient':>7s} {'relev':>7s}")
    for s, st in list(res["sectors"].items()) + [("OVERALL", res["overall"])]:
        print(f"{s:34s} {st['n']:4d} {_pct(st['precision']):>7s} {_pct(st['lenient_precision']):>7s} "
              f"{_pct(st['relevance']):>7s}")
    print(f"scored {res['scored']}, unscored {res['unscored']}; below 70%: {', '.join(res['below_70']) or 'none'}")
    return 0


# -- cli ---------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=SPOT_DIR, help="spotcheck directory")
    ap.add_argument("--stage-dir", type=Path, default=STAGE_DIR)
    ap.add_argument("--sectors-dir", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--n", type=int, default=200)
    s.add_argument("--seed", type=int, default=11)
    s.add_argument("--force", action="store_true")
    p = sub.add_parser("packets")
    p.add_argument("--size", type=int, default=50)
    p.add_argument("--seed", type=int, default=11)
    m = sub.add_parser("merge-verdicts")
    m.add_argument("file")
    sc = sub.add_parser("score")
    sc.add_argument("--checked-by", default=CHECKED_BY_LABELS[0])
    sc.add_argument("--seed", type=int, default=11)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    fn = {"sample": cmd_sample, "packets": cmd_packets, "merge-verdicts": cmd_merge, "score": cmd_score}[args.cmd]
    try:
        return fn(args)
    except SpotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
