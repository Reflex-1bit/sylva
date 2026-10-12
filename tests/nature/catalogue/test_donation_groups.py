"""Phase 7: donation groups (assignment, groups step, validator, link checker, wording guard)."""

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.models.catalogue import CatalogueRecord, Group

ROOT = Path(__file__).resolve().parents[3]
CATDIR = ROOT / "scripts" / "nature" / "catalogue"
DATA = ROOT / "data" / "nature" / "catalogue"
VALIDATE = CATDIR / "validate.py"
sys.path.insert(0, str(CATDIR))


def _load(name, alias=None):
    spec = importlib.util.spec_from_file_location(alias or name, CATDIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias or name] = mod
    spec.loader.exec_module(mod)
    return mod


dg = _load("donation_groups")
links = _load("check_links")
build = _load("build", "catalogue_build_p7")


def grp(id, country, habitats=(), taxa=()):
    return Group(id=id, name=id, country=country, habitats=list(habitats), flagship_taxa=list(taxa),
                 donate_url=f"https://{id}.example/donate", source_url=f"https://{id}.example/",
                 checked_on="2026-10-11")


GROUPS = [
    grp("z-intl", "INT", ["marine"]),
    grp("a-gb", "GB", ["marine"]),
    grp("m-es", "ES", ["marine"]),
    grp("k-pt", "PT", ["marine"]),
    grp("b-fr", "FR", ["marine"]),
    grp("shark-trust", "INT", ["marine"], ["sharks", "shark", "rays"]),
    grp("lynx-es", "ES", ["forest"], ["iberian lynx", "lynx"]),
    grp("lynx-pt", "PT", ["forest"], ["iberian lynx", "lynx"]),
    grp("bird-gr", "GR", ["birds"], ["birds"]),
    grp("forest-only", "ES", ["forest"]),
]
A = dg.GroupAssigner(GROUPS)


# ── assignment ────────────────────────────────────────────────────────────────


def tiers_of(ids, countries, groups=GROUPS):
    by = {g.id: g for g in groups}
    return [dg.tier(by[i], countries) for i in ids]


def test_one_group_per_tier_in_tier_order():
    for countries, expected in ((["GB"], [0, 1, 2]), (["FR"], [0, 1, 2]), ([], [1, 2, 3])):
        ids = A.assign("rec-1", None, "marine", countries)
        assert tiers_of(ids, countries) == expected, (countries, ids)
    # the record's own country always leads
    assert A.assign("rec-9", None, "marine", ["GB"])[0] == "a-gb"


def test_tier_values():
    g = {x.id: x for x in GROUPS}
    assert dg.tier(g["a-gb"], ["GB"]) == 0
    assert dg.tier(g["m-es"], ["GB"]) == 1 and dg.tier(g["k-pt"], []) == 1
    assert dg.tier(g["z-intl"], ["GB"]) == 2
    assert dg.tier(g["b-fr"], ["GB"]) == 3


def test_remaining_slots_filled_from_tiers_in_order():
    groups = [grp(f"es{i}", "ES", ["marine"]) for i in range(3)] + [grp("int1", "INT", ["marine"])]
    asg = dg.GroupAssigner(groups)
    ids = asg.assign("rec-1", None, "marine", [])
    assert len(ids) == 3 and len(set(ids)) == 3
    assert sorted(tiers_of(ids, [], groups)) == [1, 1, 2]
    assert tiers_of(ids, [], groups)[:2] == [1, 2]  # one per tier first, then the fill


def test_within_a_tier_the_rank_is_the_sha1_of_record_and_group():
    groups = [grp(f"es{i}", "ES", ["marine"]) for i in range(4)]
    asg = dg.GroupAssigner(groups)
    for rid in ("oa-W1", "oa-W2", "cd-77"):
        want = sorted((g.id for g in groups), key=lambda gid: dg.rank_hash(rid, gid))[:3]
        assert asg.assign(rid, None, "marine", []) == want
    assert dg.rank_hash("a", "b") == __import__("hashlib").sha1(b"a|b").hexdigest()


def test_load_spreads_over_all_groups():
    groups = [grp(f"es{i}", "ES", ["wetland"]) for i in range(3)] + [grp(f"int{i}", "INT", ["wetland"]) for i in range(3)]
    asg = dg.GroupAssigner(groups)
    n = 1000
    counts = {g.id: 0 for g in groups}
    for i in range(n):
        for gid in asg.assign(f"oa-W{i}", None, "wetland", []):
            counts[gid] += 1
    assert all(c > 0 for c in counts.values())
    assert max(counts.values()) / n < 0.8  # no group is a near-monopoly
    assert min(counts.values()) / n > 0.2


def test_flagship_matches_organism_name_only_with_singular_plural():
    assert A.assign("r", "shark", "marine", [])[0] == "shark-trust"
    assert A.assign("r", "Sharks", "marine", [])[0] == "shark-trust"
    bird = dg.GroupAssigner([grp("b1", "ES", ["birds"], ["birds"]), grp("b2", "PT", ["birds"])])
    assert bird.assign("r", "bird", "birds", [])[0] == "b1"  # bird <-> birds
    bf = dg.GroupAssigner([grp("bf", "INT", ["pollinators"], ["butterflies"])])
    assert bf.flagship_hits("butterfly") and bf.flagship_hits("butterflies")
    assert not A.flagship_hits("manta ray")  # term 'rays' is not the whole organism name
    assert not A.flagship_hits(None) and not A.flagship_hits("")


def test_flagship_phrase_must_equal_the_organism_name():
    bears = dg.GroupAssigner([grp("oso", "ES", ["forest"], ["brown bear", "cantabrian brown bear"])])
    assert bears.flagship_hits("brown bear") and not bears.flagship_hits("polar bear")
    assert not bears.flagship_hits("bear")


def test_title_never_matters():
    # assign() has no title argument: a record whose title says "lynx" but has no organism gets no flagship
    assert A.assign("r", None, None, ["ES"]) == []
    assert A.assign("r", "gecko", None, ["ES"]) == []


def test_flagship_without_habitat_still_assigns():
    assert A.assign("r", "lynx", None, ["ES"]) == ["lynx-es", "lynx-pt"]  # tier a, then b


def test_flagship_capped_and_habitat_keeps_a_slot():
    groups = [grp(f"f{i}", "INT", ["forest"], ["wolf"]) for i in range(4)] + [grp("h", "INT", ["forest"])]
    asg = dg.GroupAssigner(groups)
    ids = asg.assign("r", "wolf", "forest", [])
    assert len(ids) == 3 and len(set(ids)) == 3
    assert len([i for i in ids if i.startswith("f")]) == 3  # 2 flagship + 1 habitat group (also an f*)
    assert len(asg.assign("r", "wolf", None, [])) == 2


def test_max_three_unique_and_no_habitat_gives_empty():
    ids = A.assign("r", "lynx", "forest", ["ES"])
    assert len(ids) <= 3 and len(set(ids)) == len(ids)
    assert A.assign("r", None, None, ["ES"]) == []
    assert A.assign("r", "gecko", "desert-not-listed", ["ES"]) == []  # habitat with no group


def test_deterministic_regardless_of_group_input_order():
    shuffled = dg.GroupAssigner(list(reversed(GROUPS)))
    for args in (("r1", None, "marine", ["GB"]), ("r2", "shark", "marine", []),
                 ("r3", "lynx", "forest", ["PT", "ES"])):
        assert A.assign(*args) == shuffled.assign(*args) == A.assign(*args)


def test_assign_record():
    rec = CatalogueRecord.model_validate(_rec(organism={"name": "shark"}, habitat_id="marine"))
    assert A.assign_record(rec)[0] == "shark-trust"


def _rec(**kw):
    base = dict(id="oa-W1", source="openalex", source_id="W1", kind="paper", title="Reef study",
                source_licence="CC-BY-4.0", url="https://openalex.org/W1", primary_sector="other",
                sort_confidence=0.5, sort_reason="no-signal", provenance="machine_sorted", licence="CC-BY-4.0")
    base.update(kw)
    return base


# ── groups step ───────────────────────────────────────────────────────────────


def test_groups_step_writes_grouped_and_report(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    recs = [_rec(id="oa-W1", organism={"name": "shark"}, habitat_id="marine", countries=["GB"]),
            _rec(id="oa-W2", title="Plain title"),
            _rec(id="oa-W3", habitat_id="arid")]
    (stage / "sorted.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    (stage / "report.json").write_text(json.dumps({"keep": 1}), encoding="utf-8")
    habitats = [type("H", (), {"id": i}) for i in ("marine", "forest", "birds", "arid")]
    block = build.groups_step(stage, groups=GROUPS, habitats=habitats, log=lambda *a: None)
    out = [json.loads(l) for l in (stage / "grouped.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in out] == ["oa-W1", "oa-W2", "oa-W3"]
    assert out[0]["group_ids"][0] == "shark-trust" and len(out[0]["group_ids"]) == 3
    assert out[0]["group_ids"][1] == "a-gb"  # then the record country tier
    assert out[1]["group_ids"] == [] and out[2]["group_ids"] == []
    assert block["records_with_group"] == 1 and block["per_group"]["shark-trust"] == 1
    assert block["flagship_hits_per_group"] == {"shark-trust": 1} and block["flagship_examples"][0]["id"] == "oa-W1"
    assert block["habitats_with_0_groups"] == ["arid"]
    assert block["records_with_habitat_but_no_group"] == {"arid": 1}
    assert json.loads((stage / "report.json").read_text(encoding="utf-8"))["keep"] == 1
    first = (stage / "grouped.jsonl").read_bytes()
    build.groups_step(stage, groups=GROUPS, habitats=habitats, log=lambda *a: None)
    assert (stage / "grouped.jsonl").read_bytes() == first


def test_groups_step_needs_sorted(tmp_path):
    with pytest.raises(SystemExit):
        build.groups_step(tmp_path, groups=GROUPS, habitats=[], log=lambda *a: None)


def test_real_groups_cover_every_habitat_with_two():
    groups = json.loads((DATA / "groups.json").read_text(encoding="utf-8"))["groups"]
    habitats = [h["id"] for h in json.loads((DATA / "habitats.json").read_text(encoding="utf-8"))["habitats"]]
    for h in habitats:
        assert sum(h in g["habitats"] for g in groups) >= 2, h
    assert all(g["every_org_slug"] is None for g in groups)
    assert not {"vulture-conservation-foundation", "oceana", "soil-association", "african-parks"} & {g["id"] for g in groups}


# ── validator ─────────────────────────────────────────────────────────────────


def run_validate(*args):
    return subprocess.run([sys.executable, str(VALIDATE), *args], cwd=ROOT, capture_output=True, text=True)


def _copy(tmp_path):
    d = tmp_path / "cat"
    shutil.copytree(DATA, d, ignore=shutil.ignore_patterns("raw", "build", "spotcheck"))
    return d


def _edit_groups(d, fn):
    p = d / "groups.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    fn(data)
    p.write_text(json.dumps(data), encoding="utf-8")


def test_validate_passes_on_real_groups():
    r = run_validate()
    assert r.returncode == 0, r.stderr


def test_validate_fails_when_a_habitat_has_one_group(tmp_path):
    d = _copy(tmp_path)

    def drop(data):
        data["groups"] = [g for g in data["groups"] if g["id"] not in ("sahara-conservation",)]
    _edit_groups(d, drop)
    r = run_validate("--data-dir", str(d))
    assert r.returncode == 1 and "habitat 'arid' has 1 group" in r.stderr


def test_validate_fails_on_http_url(tmp_path):
    d = _copy(tmp_path)
    _edit_groups(d, lambda data: data["groups"][0].update(donate_url="http://insecure.example/donate"))
    r = run_validate("--data-dir", str(d))
    assert r.returncode == 1 and "donate_url" in r.stderr


def test_validate_fails_on_bad_checked_on(tmp_path):
    d = _copy(tmp_path)
    _edit_groups(d, lambda data: data["groups"][0].update(checked_on="yesterday"))
    assert run_validate("--data-dir", str(d)).returncode == 1


def test_validate_fails_on_duplicate_group_id_and_unknown_habitat(tmp_path):
    d = _copy(tmp_path)
    _edit_groups(d, lambda data: data["groups"].append(dict(data["groups"][0])))
    r = run_validate("--data-dir", str(d))
    assert r.returncode == 1 and "duplicate group id" in r.stderr
    d2 = tmp_path / "cat2"
    shutil.copytree(d, d2)
    _edit_groups(d2, lambda data: (data["groups"].pop(), data["groups"][0]["habitats"].append("nowhere")))
    r = run_validate("--data-dir", str(d2))
    assert r.returncode == 1 and "unknown habitat 'nowhere'" in r.stderr


def test_validate_build_checks_group_ids_exist(tmp_path):
    good = _rec(group_ids=["seo-birdlife"])
    bad = _rec(id="oa-W2", source_id="W2", url="https://openalex.org/W2", group_ids=["no-such-group"])
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "grouped.jsonl").write_text(json.dumps(good) + "\n", encoding="utf-8")
    assert run_validate("--build", str(stage)).returncode == 0
    (stage / "grouped.jsonl").write_text(json.dumps(good) + "\n" + json.dumps(bad) + "\n", encoding="utf-8")
    r = run_validate("--build", str(stage))
    assert r.returncode == 1 and "unknown group 'no-such-group'" in r.stderr


# ── link checker ──────────────────────────────────────────────────────────────


def test_check_url_head_then_get_fallback_and_classes():
    calls = []

    def fetcher(url, method):
        calls.append((url, method))
        if "head405" in url:
            return (405, url, None) if method == "HEAD" else (200, url + "/final", None)
        if "blocked" in url:
            return 403, url, None
        if "dead" in url:
            return 404, url, None
        if "down" in url:
            return None, None, "URLError: boom"
        return 200, url, None

    nosleep = lambda s: None  # noqa: E731
    r = links.check_url("https://head405.example/", fetcher, nosleep)
    assert r["method"] == "GET" and r["status"] == 200 and r["result"] == "ok" and r["redirected"]
    assert calls == [("https://head405.example/", "HEAD"), ("https://head405.example/", "GET")]
    assert links.check_url("https://blocked.example/", fetcher, nosleep)["result"] == "blocked"
    assert links.check_url("https://dead.example/", fetcher, nosleep)["result"] == "dead"
    assert links.check_url("https://down.example/", fetcher, nosleep)["result"] == "error"
    ok = links.check_url("https://fine.example/", fetcher, nosleep)
    assert ok["method"] == "HEAD" and ok["result"] == "ok" and not ok["redirected"]


def test_run_paces_one_request_per_second_and_never_raises():
    sleeps = []
    rep = links.run(GROUPS[:2], fetcher=lambda u, m: (200, u, None), sleep=sleeps.append, log=lambda *a: None)
    assert rep["checked"] == 4 and rep["summary"] == {"ok": 4}
    assert sleeps == [1.0, 1.0, 1.0]  # between the 4 requests


def test_link_checker_identity_has_no_contact_address():
    assert links.USER_AGENT == "SylvaNatureCatalogue/0.1"
    assert links.TIMEOUT == 20 and links.DELAY == 1.0


def test_no_email_or_mailto_in_catalogue_scripts():
    email = re.compile(r"[\w.+%-]+@(?:[\w-]+\.)+[A-Za-z]{2,}")
    for p in CATDIR.glob("*.py"):
        text = p.read_text(encoding="utf-8")
        assert "mailto:" not in text.lower(), p.name
        for m in email.finditer(text):
            raise AssertionError(f"{p.name}: {m.group(0)}")


# ── wording guard ─────────────────────────────────────────────────────────────

BANNED = re.compile(r"benefit[\s-]+sharing|pays\s+the\s+reserve", re.I)


def _guard_files():
    roots = [CATDIR, DATA, ROOT / "tests" / "nature" / "catalogue", ROOT / "docs"]
    skip_dirs = {"raw", "build", ".cache", "spotcheck", "__pycache__", "plans"}
    me = Path(__file__).resolve()
    files = [ROOT / "app" / "models" / "catalogue.py"]
    for root in roots:
        for p in root.rglob("*"):
            if not p.is_file() or p.resolve() == me or (set(p.relative_to(root).parts) & skip_dirs):
                continue
            if p.suffix.lower() in {".py", ".json", ".md", ".txt", ".html", ".jsonl", ".csv"}:
                files.append(p)
    return files


def test_wording_guard_no_banned_phrases():
    files = _guard_files()
    assert any(f.name == "groups.json" for f in files)
    hits = [f"{f.relative_to(ROOT)}: {m.group(0)}" for f in files
            for m in BANNED.finditer(f.read_text(encoding="utf-8", errors="ignore"))]
    assert not hits, hits


# ── merge hygiene (L1 follow-up) ──────────────────────────────────────────────


def test_merge_deletes_stale_merged_and_cleans_tmp_on_exception(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "merged.jsonl").write_text("stale\n", encoding="utf-8")
    (stage / "merged.jsonl.tmp").write_text("junk\n", encoding="utf-8")
    with pytest.raises(SystemExit):  # no raw sources: the merge fails right away
        build.merge(tmp_path / "no-raw", stage, log=lambda *a: None)
    assert not (stage / "merged.jsonl").exists() and not (stage / "merged.jsonl.tmp").exists()
