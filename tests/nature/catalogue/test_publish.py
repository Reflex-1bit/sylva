"""Phase 8: publish step (chunks, manifest, local full files)."""

import gzip
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "nature" / "catalogue"))

import publish as pub  # noqa: E402

CAT = ROOT / "data" / "nature" / "catalogue"


def rec(n, **kw):
    base = dict(id=f"oa-W{n}", source="openalex", source_id=f"W{n}", kind="paper", title=f"Lotus coating {n}",
                source_licence="CC0", url=f"https://openalex.org/W{n}", primary_sector="chemicals",
                sort_confidence=0.8, sort_reason="cpc:C09 -> chemicals", provenance="machine_sorted",
                licence="CC-BY-4.0")
    base.update(kw)
    return base


def stage(tmp_path, records, sources_extra=None):
    d = tmp_path / "stage"
    d.mkdir(exist_ok=True)
    (d / "grouped.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    (d / "merged.jsonl").write_text(
        json.dumps({"id": "x", "harvested_on": "2026-10-01"}) + "\n" +
        json.dumps({"id": "y", "harvested_on": "2026-10-09"}) + "\n", encoding="utf-8")
    return d


def run(tmp_path, records, **kw):
    d = stage(tmp_path, records)
    out = tmp_path / "public"
    b = tmp_path / "build"
    code, summary = pub.publish_step(d, out, b, tmp_path / "nospot", CAT, openalex_state=tmp_path / "none.json",
                                     log=lambda *_: None, **kw)
    return code, summary, out, b


def load_chunk(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def test_chunks_at_most_2000_and_zero_padded(tmp_path):
    code, summary, out, _ = run(tmp_path, [rec(i) for i in range(1, 2004)])
    assert code == 0
    files = sorted(p.name for p in (out / "chemicals").iterdir())
    assert files == ["chunk-0001.json.gz", "chunk-0002.json.gz"]
    c1, c2 = (load_chunk(out / "chemicals" / f) for f in files)
    assert len(c1["records"]) == 2000 and len(c2["records"]) == 3
    assert c1["sector"] == "chemicals" and c1["chunk"] == 1 and c2["chunk"] == 2
    keys = list(c1)
    assert keys.index("sector") < keys.index("records") and keys.index("chunk") < keys.index("records")
    assert c1["licence"] == "CC-BY-4.0" and c1["db"] == "catalogue"


def test_order_area_kind_year_id_null_last(tmp_path):
    recs = [
        rec(1, area=None, kind="project", id="cd-1", source="cordis", source_id="1", year=2020),
        rec(2, area="process", kind="paper", year=2010),
        rec(3, area="form", kind="paper", year=2010),
        rec(4, area="form", kind="paper", year=2015),
        rec(5, area="form", kind="paper", year=None),
        rec(6, area="form", kind="patent", year=2000, id="pv-US6", source="patentsview", source_id="US6"),
        rec(7, area="form", kind="project", year=1999, id="cd-7", source="cordis", source_id="7"),
        rec(8, area="form", kind="paper", year=2015),
    ]
    _, _, out, _ = run(tmp_path, recs)
    ids = [r["id"] for r in load_chunk(out / "chemicals" / "chunk-0001.json.gz")["records"]]
    # form: project, patent, then papers by year desc (2015 W4, W8 by id), 2010, null; then process; null area last
    assert ids == ["cd-7", "pv-US6", "oa-W4", "oa-W8", "oa-W3", "oa-W5", "oa-W2", "cd-1"]


def test_gzip_header_mtime_zero_and_no_name(tmp_path):
    _, _, out, _ = run(tmp_path, [rec(1)])
    raw = (out / "chemicals" / "chunk-0001.json.gz").read_bytes()
    assert raw[:2] == b"\x1f\x8b" and raw[3] == 0  # no FNAME flag
    assert raw[4:8] == b"\x00\x00\x00\x00"


def test_deterministic_twice(tmp_path):
    recs = [rec(i, area="form" if i % 2 else None) for i in range(1, 50)] + [
        rec(100, primary_sector="other", id="oa-W100", source_id="W100")]
    _, _, out, b = run(tmp_path, recs)

    def hashes():
        files = [*out.rglob("*"), b / "catalogue.json", b / "catalogue.csv", b / "manifest.json"]
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}

    first = hashes()
    run(tmp_path, recs)
    assert hashes() == first and len(first) >= 6
    assert (out / "manifest.json").read_bytes() == (b / "manifest.json").read_bytes()


def test_manifest_matches_files(tmp_path):
    _, _, out, _ = run(tmp_path, [rec(i) for i in range(1, 2004)] + [
        rec(5000, primary_sector="other", id="oa-W5000", source_id="W5000")])
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["generated_on"] == "2026-10-09" and m["totals"]["records"] == 2004
    assert [s["id"] for s in m["sectors"]] == ["chemicals", "other"]  # empty sectors skipped
    for s in m["sectors"]:
        assert s["description"] and s["count"] == sum(c["count"] for c in s["chunks"])
        for c in s["chunks"]:
            data = (out / c["path"]).read_bytes()
            assert c["bytes"] == len(data) and c["sha256"] == hashlib.sha256(data).hexdigest()
    assert m["spotcheck"] is None and m["sectors"][0]["precision"] is None
    assert m["download_note"] == "CSV files must keep the attribution line with them."
    assert len(m["groups"]) == 49 and {"id", "label"} <= set(m["areas"][0])


def test_stale_cleanup_deletes_only_chunks_and_manifest(tmp_path):
    out = tmp_path / "public"
    (out / "oldsector").mkdir(parents=True)
    (out / "oldsector" / "chunk-0001.json.gz").write_bytes(b"x")
    (out / "chemicals").mkdir()
    (out / "chemicals" / "chunk-0009.json.gz").write_bytes(b"x")
    (out / "chemicals" / "notes.txt").write_text("keep", encoding="utf-8")
    (out / "readme.md").write_text("keep", encoding="utf-8")
    run(tmp_path, [rec(1)])
    assert not (out / "oldsector").exists()
    assert not (out / "chemicals" / "chunk-0009.json.gz").exists()
    assert (out / "chemicals" / "notes.txt").read_text(encoding="utf-8") == "keep"
    assert (out / "readme.md").exists() and (out / "chemicals" / "chunk-0001.json.gz").exists()


def test_size_budget_exit(tmp_path):
    code, summary, _, _ = run(tmp_path, [rec(1)], budget=10)
    assert code == 1 and summary["total_gz_bytes"] > 10


def test_attribution_lists_only_present_sources(tmp_path):
    _, _, out, b = run(tmp_path, [rec(1)])
    a = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["attribution"]
    assert "OpenAlex (CC0)" in a and "CORDIS" not in a and "Climate-ADAPT" not in a and "GBIF" not in a
    assert a.startswith("Sylva - ") and "—" not in a
    recs = [rec(1, organism={"name": "Apis mellifera", "gbif_key": 1341976}),
            rec(2, id="cd-2", source="cordis", source_id="2")]
    _, _, out, _ = run(tmp_path, recs)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert "CORDIS" in m["attribution"] and "GBIF Backbone Taxonomy (CC BY 4.0)" in m["attribution"]
    assert [s["id"] for s in m["sources"]] == ["openalex", "cordis", "gbif"]


def test_invalid_record_aborts_with_id(tmp_path):
    bad = rec(1)
    bad["provenance"] = "x"
    with pytest.raises(SystemExit) as e:
        run(tmp_path, [rec(2), bad])
    assert "oa-W1" in str(e.value)


def test_wrapper_validates_and_csv_written(tmp_path):
    code, _, _, b = run(tmp_path, [rec(1, area="form", title="=SUM(1)")])  # validate --build runs in the step
    assert code == 0
    w = json.loads((b / "catalogue.json").read_text(encoding="utf-8"))
    assert w["db"] == "catalogue" and len(w["records"]) == 1 and w["licence"] == "CC-BY-4.0"
    lines = (b / "catalogue.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("id,source,") and "'=SUM(1)" in lines[1]


def test_spotcheck_rounds_low_sample_and_warning(tmp_path):
    spot = tmp_path / "spot"
    spot.mkdir()
    ov = lambda p: {"n": 10, "precision": p, "lenient_precision": p, "relevance": p, "n_relevance": 5}  # noqa: E731
    sec = lambda n, p: {"n": n, "precision": p, "lenient_precision": p, "relevance": p, "n_relevance": 3}  # noqa: E731
    (spot / "results.json").write_text(json.dumps({
        "checked_by": "agent, owner skim pending", "sample_size": 200, "overall": ov(0.6),
        "sectors": {"chemicals": sec(31, 0.7), "other": sec(4, 0.5)}, "below_70": ["other"]}), encoding="utf-8")
    for n, p in ((1, 0.5), (2, 0.6)):
        (spot / f"results-round{n}.json").write_text(json.dumps({"overall": ov(p)}), encoding="utf-8")
    d = stage(tmp_path, [rec(1), rec(2, primary_sector="other", id="oa-W2", source_id="W2")])
    out = tmp_path / "public"
    code, _ = pub.publish_step(d, out, tmp_path / "build", spot, CAT, openalex_state=tmp_path / "n.json",
                               log=lambda *_: None)
    assert code == 0
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    chem, other = m["sectors"]
    assert (chem["low_sample"], chem["precision_warning"], chem["n"]) == (False, False, 31)
    assert (other["low_sample"], other["precision_warning"]) == (True, True)
    assert m["spotcheck"]["checked_by"] == "agent, owner skim pending"
    assert [r["round"] for r in m["spotcheck"]["rounds"]] == [1, 2]
    assert m["spotcheck"]["rounds"][1]["note"] == "fresh sample after tuning; published figure"
    assert m["spotcheck"]["rounds"][0]["strict"] == 0.5

