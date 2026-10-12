import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "catalogue_spotcheck", ROOT / "scripts" / "nature" / "catalogue" / "spotcheck.py"
)
sc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sc)

SECTOR_IDS = [s.id for s in sc.load_sectors().sectors]
SIZES = {SECTOR_IDS[0]: 600, SECTOR_IDS[1]: 300, SECTOR_IDS[2]: 90, SECTOR_IDS[3]: 9, SECTOR_IDS[4]: 3}


def _rec(i, sector, tags=(), **kw):
    r = {
        "id": f"t-{i}", "source": "cordis", "kind": "project", "title": f"Title {i}",
        "summary": f"Summary {i}", "url": f"https://example.org/{i}", "organism": None,
        "primary_sector": sector, "sector_tags": list(tags), "sort_confidence": 0.5,
        "sort_reason": f"secret-reason-{i}",
    }
    r.update(kw)
    return r


@pytest.fixture
def env(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    recs, i = [], 0
    for sec, size in SIZES.items():
        for _ in range(size):
            tags = [SECTOR_IDS[5]] if i % 3 == 0 else []
            recs.append(_rec(i, sec, tags))
            i += 1
    (stage / "sorted.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return tmp_path, recs


def run(tmp, *argv):
    return sc.main(["--dir", str(tmp / "spot"), "--stage-dir", str(tmp / "stage"), *argv])


def rows_of(tmp):
    return sc.read_csv(tmp / "spot" / "spotcheck.csv")


def test_allocate_exact_total_and_minimums():
    for n in (50, 200, 500):
        counts = sc.allocate(SIZES, n)
        assert sum(counts.values()) == n
        for s, sz in SIZES.items():
            assert min(5, sz) <= counts[s] <= sz


def test_allocate_fewer_records_than_n():
    assert sc.allocate({"a": 3, "b": 4}, 200) == {"a": 3, "b": 4}


def test_sample_deterministic_and_columns(env):
    tmp, _ = env
    assert run(tmp, "sample", "--n", "100") == 0
    first = (tmp / "spot" / "spotcheck.csv").read_bytes()
    assert not first.startswith(b"\xef\xbb\xbf")
    assert run(tmp, "sample", "--n", "100") == 0
    assert (tmp / "spot" / "spotcheck.csv").read_bytes() == first
    rows = rows_of(tmp)
    assert len(rows) == 100
    assert list(rows[0].keys()) == sc.COLUMNS
    per = {}
    for r in rows:
        per[r["primary_sector"]] = per.get(r["primary_sector"], 0) + 1
    assert per[SECTOR_IDS[4]] == 3 and per[SECTOR_IDS[3]] >= 5
    assert all(r["verdict_sector"] == "" and r["note"] == "" for r in rows)
    assert any("|" in r["sector_tags"] or r["sector_tags"] for r in rows)


def test_title_formula_guard(env):
    tmp, recs = env
    p = tmp / "stage" / "sorted.jsonl"
    recs[0]["title"] = "=HYPERLINK(1)"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    run(tmp, "sample", "--n", "5000")
    t = {r["id"]: r["title"] for r in rows_of(tmp)}
    assert t["t-0"] == "'=HYPERLINK(1)"


def test_overwrite_refusal(env):
    tmp, _ = env
    run(tmp, "sample", "--n", "50")
    rows = rows_of(tmp)
    rows[0]["verdict_sector"] = "ok"
    sc.write_csv(tmp / "spot" / "spotcheck.csv", rows)
    assert run(tmp, "sample", "--n", "50") == 1
    assert rows_of(tmp)[0]["verdict_sector"] == "ok"
    assert run(tmp, "sample", "--n", "50", "--force") == 0
    assert rows_of(tmp)[0]["verdict_sector"] == ""


def _hand_csv(tmp, spec):
    rows = []
    for k, (sec, vs, vr) in enumerate(spec):
        rows.append({"id": f"h-{k}", "title": "t", "primary_sector": sec, "verdict_sector": vs, "verdict_relevant": vr})
    sc.write_csv(tmp / "spot" / "spotcheck.csv", rows)


def test_score_math(env):
    tmp, _ = env
    spec = [("a", "ok", "yes")] * 3 + [("a", "tag", "no"), ("a", "wrong", "yes"), ("a", "unsure", "yes"), ("a", "", "yes")]
    spec += [("b", "wrong", "no")] * 5 + [("b", "ok", "unsure")]
    _hand_csv(tmp, spec)
    assert run(tmp, "score") == 0
    res = json.loads((tmp / "spot" / "results.json").read_text(encoding="utf-8"))
    a = res["sectors"]["a"]
    assert a["n"] == 5 and a["precision"] == 0.6 and a["lenient_precision"] == 0.8
    assert a["relevance"] == pytest.approx(5 / 6, abs=1e-3)  # unsure-sector row still counts for relevance; unscored row does not
    assert res["sectors"]["b"]["n"] == 6
    assert res["below_70"] == ["a", "b"]
    assert res["checked_by"] == "agent, owner skim pending"
    assert res["sample_size"] == len(spec)
    assert res["overall"]["n"] == 11


def test_score_below_70_needs_n5(env):
    tmp, _ = env
    _hand_csv(tmp, [("small", "wrong", "no")] * 4 + [("big", "ok", "yes")] * 7 + [("big", "wrong", "yes")] * 3)
    run(tmp, "score")
    res = json.loads((tmp / "spot" / "results.json").read_text(encoding="utf-8"))
    assert res["below_70"] == []
    assert res["sectors"]["big"]["precision"] == 0.7


def test_score_invalid_values_exit_1(env):
    tmp, _ = env
    _hand_csv(tmp, [("a", "maybe", "yes")])
    assert run(tmp, "score") == 1
    _hand_csv(tmp, [("a", "ok", "perhaps")])
    assert run(tmp, "score") == 1


def test_checked_by_labels(env):
    tmp, _ = env
    _hand_csv(tmp, [("a", "ok", "yes")])
    assert run(tmp, "score", "--checked-by", "human-verified") == 1
    assert run(tmp, "score", "--checked-by", "agent, owner-skimmed") == 0
    res = json.loads((tmp / "spot" / "results.json").read_text(encoding="utf-8"))
    assert res["checked_by"] == "agent, owner-skimmed"


def test_packets_blind(env):
    tmp, recs = env
    run(tmp, "sample", "--n", "60")
    assert run(tmp, "packets", "--size", "25") == 0
    packets = sorted((tmp / "spot" / "packets").glob("packet-*.md"))
    assert len(packets) == 3
    by_id = {r["id"]: r for r in recs}
    text_all = ""
    for p in packets:
        text = p.read_text(encoding="utf-8")
        text_all += text
        assert "primary_sector" not in text and "sort_reason" not in text
        assert "secret-reason" not in text
        assert sc.SCOPE_RULE in text
    for r in rows_of(tmp):
        rec = by_id[r["id"]]
        block = text_all.split(f"### {rec['id']}\n", 1)[1].split("###", 1)[0]
        cands = [l for l in block.splitlines() if l.startswith("- candidate sectors:")][0].split(": ", 1)[1].split(", ")
        assert rec["primary_sector"] in cands
        assert set(rec["sector_tags"]) <= set(cands)
        assert len(cands) <= 1 + len(rec["sector_tags"]) + 2


def test_packets_no_summary(env):
    tmp, recs = env
    p = tmp / "stage" / "sorted.jsonl"
    for r in recs:
        r["summary"] = None
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    run(tmp, "sample", "--n", "10")
    run(tmp, "packets")
    assert "(no summary)" in (tmp / "spot" / "packets" / "packet-1.md").read_text(encoding="utf-8")


def test_merge_verdicts(env):
    tmp, recs = env
    run(tmp, "sample", "--n", "60")
    rows = rows_of(tmp)
    tagged = next(r for r in rows[3:] if r["sector_tags"])
    plain = next(r for r in rows[3:] if not r["sector_tags"])
    other = [s for s in SECTOR_IDS if s != plain["primary_sector"] and s not in tagged["sector_tags"].split("|")][0]
    rev = tmp / "rev.csv"
    with rev.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "chosen_sector", "verdict_relevant", "note"])
        w.writerow([rows[0]["id"], rows[0]["primary_sector"], "yes", "n1"])
        w.writerow([tagged["id"], tagged["sector_tags"].split("|")[0], "no", ""])
        w.writerow([plain["id"], other, "unsure", ""])
        w.writerow([rows[1]["id"], "unsure", "", ""])
        w.writerow([rows[2]["id"], "", "yes", ""])
    assert run(tmp, "merge-verdicts", str(rev)) == 0
    by = {r["id"]: r for r in rows_of(tmp)}
    assert by[rows[0]["id"]]["verdict_sector"] == "ok" and by[rows[0]["id"]]["note"] == "n1"
    assert by[tagged["id"]]["verdict_sector"] == "tag"
    assert by[plain["id"]]["verdict_sector"] == "wrong"
    assert by[rows[1]["id"]]["verdict_sector"] == "unsure"
    assert by[rows[2]["id"]]["verdict_sector"] == "unsure"


def test_merge_unknown_id_errors(env):
    tmp, _ = env
    run(tmp, "sample", "--n", "20")
    rev = tmp / "rev.csv"
    rev.write_text("id,chosen_sector,verdict_relevant,note\nnope,x,yes,\n", encoding="utf-8")
    assert run(tmp, "merge-verdicts", str(rev)) == 1
