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
import hashlib
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

CANDIDATES = 5

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


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_meta(directory: Path) -> dict:
    p = directory / "sample.json"
    if not p.exists():
        raise SpotError(f"{p} not found; run sample first")
    return json.loads(p.read_text(encoding="utf-8"))


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
    """Per-sector sample counts that sum to exactly n (or every record when fewer than n exist).

    1. Reserve a floor f_s = min(5, size_s) for every sector.
    2. Split the remainder R = n - sum(f_s) over the sectors in proportion to their full size:
       extra_s = R * size_s / sum(size), capped at size_s - f_s. A sector that hits its cap is fixed
       there and R is re-split over the rest (water-filling).
    3. Round the extras by Hamilton's method (floor, then one more to the largest fractional parts,
       ties by sector id), so count_s = f_s + extra_s and the total is exactly n.
    If the floors alone exceed n, the floors are returned (total > n).
    """
    total = sum(sizes.values())
    if total <= n:
        return dict(sizes)
    floor = {s: min(5, sz) for s, sz in sizes.items()}
    counts = dict(floor)
    left = n - sum(floor.values())
    cap = {s: sizes[s] - floor[s] for s in sizes}
    active = {s for s in sizes if cap[s] > 0}
    while left > 0 and active:
        denom = sum(sizes[s] for s in active)
        over = [s for s in active if left * sizes[s] / denom > cap[s]]
        if not over:
            break
        for s in over:
            counts[s] += cap[s]
            left -= cap[s]
            active.discard(s)
    if left > 0 and active:
        denom = sum(sizes[s] for s in active)
        share = {s: left * sizes[s] / denom for s in active}
        base = {s: int(share[s]) for s in active}
        rem = left - sum(base.values())
        order = sorted(active, key=lambda k: (-(share[k] - base[k]), k))
        for s in order:
            if rem <= 0:
                break
            if base[s] < cap[s]:
                base[s] += 1
                rem -= 1
        for s in active:
            counts[s] += base[s]
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
    meta = {"seed": args.seed, "n": args.n, "source_file": src.name, "source_sha256": file_sha256(src),
            "counts": {s: got[s] for s in sorted(got)}}
    (args.dir / "sample.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"read {len(records)} records from {src.name}; wrote {len(picked)} rows to {out}")
    for s in sorted(sizes):
        print(f"  {s:34s} {got[s]:4d} of {sizes[s]}")
    return 0


# -- packets -----------------------------------------------------------------


def candidate_sectors(rec: dict, all_ids: list[str], seed: int) -> list[str]:
    own = [rec["primary_sector"]] + [t for t in (rec.get("sector_tags") or []) if t != rec["primary_sector"]]
    rng = random.Random(f"{seed}:{rec['id']}")
    others = [s for s in all_ids if s not in own]
    # Pad to a fixed CANDIDATES so the count does not reveal how many tags the record has.
    cands = own + rng.sample(others, min(max(CANDIDATES - len(own), 0), len(others)))
    rng.shuffle(cands)
    return cands


def sector_definitions(sectors_dir: Optional[Path] = None) -> list[tuple[str, str, str]]:
    out = []
    for s in load_sectors(sectors_dir).sectors:
        desc = (s.description or "").strip()
        if not desc:
            raise SpotError(f"sector {s.id} has no description in sectors.json")
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
    if args.seed is None:
        args.seed = read_meta(args.dir)["seed"]
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
    """chosen must already be normalised to a sector id, "unsure" or ""."""
    if not chosen or chosen == "unsure":
        return "unsure"
    if chosen == primary:
        return "ok"
    if chosen in tags:
        return "tag"
    return "wrong"


def cmd_merge(args) -> int:
    csv_path = args.dir / "spotcheck.csv"
    rows = read_csv(csv_path)
    by_id = {r["id"]: r for r in rows}
    rev = read_csv(Path(args.file))
    seen, dups = set(), []
    for r in rev:
        if r.get("id") in seen:
            dups.append(r.get("id"))
        seen.add(r.get("id"))
    if dups:
        raise SpotError(f"duplicate ids in reviewer file: {', '.join(map(str, dups[:10]))}")
    unknown = [r.get("id") for r in rev if r.get("id") not in by_id]
    if unknown:
        raise SpotError(f"unknown ids in reviewer file: {', '.join(map(str, unknown[:10]))}")
    valid = {s.id for s in load_sectors(args.sectors_dir).sectors}
    norm: dict[str, str] = {}
    bad = []
    for r in rev:
        c = (r.get("chosen_sector") or "").strip().lower()
        if c and c != "unsure" and c not in valid:
            bad.append(r["id"])
        norm[r["id"]] = c
        vr = (r.get("verdict_relevant") or "").strip()
        if vr and vr not in RELEVANT_VERDICTS:
            raise SpotError(f"id {r['id']}: invalid verdict_relevant {vr!r} (allowed: yes, no, unsure)")
    if bad:
        raise SpotError(f"unknown chosen_sector for ids: {', '.join(bad[:10])}")
    if not args.force:
        filled = [r["id"] for r in rev
                  if (by_id[r["id"]].get("verdict_sector") or "").strip()
                  or (by_id[r["id"]].get("verdict_relevant") or "").strip()]
        if filled:
            raise SpotError(f"verdicts already filled for ids: {', '.join(filled[:10])}; pass --force to overwrite")
    for r in rev:
        row = by_id[r["id"]]
        tags = [t for t in (row.get("sector_tags") or "").split("|") if t]
        row["verdict_sector"] = map_choice(norm[r["id"]], row["primary_sector"], tags)
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
    if res["scored"] == 0:
        raise SpotError("no rows are scored (verdict_sector is empty everywhere); nothing written")
    meta = read_meta(args.dir)
    if args.seed is not None:
        print("warning: --seed is ignored; the seed comes from sample.json", file=sys.stderr)
    out = {
        "checked_by": args.checked_by,
        "sample_size": len(rows),
        "seed": meta["seed"],
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
    p.add_argument("--seed", type=int, default=None, help="default: the seed recorded in sample.json")
    m = sub.add_parser("merge-verdicts")
    m.add_argument("file")
    m.add_argument("--force", action="store_true", help="overwrite verdicts that are already filled")
    sc = sub.add_parser("score")
    sc.add_argument("--checked-by", default=CHECKED_BY_LABELS[0])
    sc.add_argument("--seed", type=int, default=None, help="ignored (seed is read from sample.json)")
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
