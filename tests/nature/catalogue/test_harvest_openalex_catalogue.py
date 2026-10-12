import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "catalogue_harvest_openalex", ROOT / "scripts" / "nature" / "catalogue" / "harvest_openalex.py"
)
ho = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ho)


def _work(n=1, **kw):
    w = {
        "id": f"https://openalex.org/W{n}",
        "doi": f"https://doi.org/10.1/abc{n}",
        "title": f"Lotus-inspired surface {n}",
        "publication_year": 2021,
        "type": "article",
        "primary_topic": {"display_name": "Wetting", "subfield": {"display_name": "Materials Chemistry"}},
        "topics": [
            {"display_name": "Wetting", "subfield": {"display_name": "Materials Chemistry"}},
            {"display_name": "Robots", "subfield": {"display_name": "Control and Systems Engineering"}},
        ],
        "keywords": [{"display_name": "biomimetics"}],
        "best_oa_location": {"license": "cc-by"},
        "primary_location": {"landing_page_url": "https://example.org/p"},
        "abstract_inverted_index": {"Lotus": [0], "leaves": [1], "repel": [2], "water": [3]},
        "authorships": [
            {
                "author": {"display_name": "Jane Secret"},
                "institutions": [
                    {"display_name": "Uni A", "country_code": "ES"},
                    {"display_name": "Uni A", "country_code": "ES"},
                    {"display_name": "Acme", "country_code": "pt"},
                ],
            }
        ],
    }
    w.update(kw)
    return w


def page(works, nxt=None):
    return {"meta": {"next_cursor": nxt}, "results": works}


def headers(remaining=900, reset=1000):
    return {"X-RateLimit-Remaining": str(remaining), "X-RateLimit-Reset": str(reset)}


def test_rebuild_abstract_orders_by_position():
    assert ho.rebuild_abstract({"b": [1], "a": [0], "c": [2, 3]}) == "a b c c"
    assert ho.rebuild_abstract(None) is None
    assert ho.rebuild_abstract({}) is None


def test_summary_kept_for_cc_by_dropped_for_nc():
    keep = ho.work_to_record(_work(1), "2026-10-11")
    assert keep.summary == "Lotus leaves repel water"
    assert keep.summary_licence == "CC-BY"
    nc = ho.work_to_record(_work(2, best_oa_location={"license": "cc-by-nc"}), "2026-10-11")
    assert nc.summary is None and nc.summary_licence is None
    none = ho.work_to_record(_work(3, best_oa_location=None), "2026-10-11")
    assert none.summary is None
    cc0 = ho.work_to_record(_work(4, best_oa_location={"license": "cc0"}), "2026-10-11")
    assert cc0.summary_licence == "CC0-1.0"


def test_url_fallback_order():
    assert ho.work_to_record(_work(1), "2026-10-11").url == "https://doi.org/10.1/abc1"
    no_doi = ho.work_to_record(_work(2, doi=None), "2026-10-11")
    assert no_doi.url == "https://example.org/p" and no_doi.doi is None
    http_only = ho.work_to_record(
        _work(3, doi=None, primary_location={"landing_page_url": "http://example.org/p"}), "2026-10-11"
    )
    assert http_only.url == "https://openalex.org/W3"
    no_loc = ho.work_to_record(_work(4, doi=None, primary_location=None), "2026-10-11")
    assert no_loc.url == "https://openalex.org/W4"


def test_no_author_names_and_metadata_mapping():
    rec = ho.work_to_record(_work(1), "2026-10-11")
    assert "Jane Secret" not in rec.model_dump_json()
    assert rec.countries == ["ES", "PT"]
    assert rec.organisations == ["Uni A", "Acme"]
    assert rec.source_codes.openalex_subfields == ["Materials Chemistry", "Control and Systems Engineering"]
    assert rec.source_codes.openalex_topics == ["Wetting", "Robots"]
    assert rec.keywords == ["biomimetics"]
    assert rec.id == "oa-W1" and rec.source_licence == "CC0-1.0"


@pytest.mark.parametrize("typ", ["paratext", "erratum", "retraction", "editorial", "letter", None])
def test_excluded_types_skipped(typ):
    assert ho.work_to_record(_work(1, type=typ), "2026-10-11") is None


def test_empty_title_skipped():
    assert ho.work_to_record(_work(1, title="  "), "2026-10-11") is None


def test_api_key_not_in_cache_key():
    a = ho.cache_key("u", {"filter": "x", "api_key": "SECRET"})
    assert a == ho.cache_key("u", {"filter": "x"})
    assert a != ho.cache_key("u", {"filter": "y"})


def test_api_key_sent_but_not_cached(tmp_path):
    seen = []

    def fetch(url, params):
        seen.append(params)
        return page([]), headers()

    c = ho.Client(tmp_path, fetch, api_key="SECRET")
    c.get("u", {"filter": "x"})
    assert seen[0]["api_key"] == "SECRET"
    assert "SECRET" not in "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("*.json"))
    c2 = ho.Client(tmp_path, fetch)
    assert c2.get("u", {"filter": "x"})[2] is True  # keyless rerun hits the keyed cache


KW = [
    {"id": "https://openalex.org/keywords/biomimetics", "display_name": "biomimetics", "works_count": 10, "include": True, "reason": ""},
    {"id": "https://openalex.org/keywords/bioinspired-design", "display_name": "bioinspired design", "works_count": 5, "include": True, "reason": ""},
    {"id": "https://openalex.org/keywords/biology", "display_name": "biology", "works_count": 99, "include": False, "reason": ""},
]
BIO = ["biomimetic", "bioinspired"]


def _routes():
    """Two keywords; 'biomimetics' has two pages; work W2 appears under both keywords."""
    return {
        ("biomimetics", "*"): page([_work(1), _work(2)], "c2"),
        ("biomimetics", "c2"): page([_work(3)], None),
        ("bioinspired-design", "*"): page([_work(2), _work(4)], None),
    }


def _fetcher(routes, log, remaining=900):
    state = {"remaining": remaining}

    def fetch(url, params):
        kid = params["filter"].split(",")[0].split(":")[1]
        log.append((kid, params["cursor"]))
        state["remaining"] -= 1
        return routes[(kid, params["cursor"])], headers(state["remaining"])

    return fetch


def test_harvest_normalise_dedupes_across_keywords(tmp_path):
    log = []
    client = ho.Client(tmp_path / "pages", _fetcher(_routes(), log))
    sp = tmp_path / "state.json"
    assert ho.run_harvest(client, KW, sp, bio_terms=BIO) == 0
    assert len(log) == 3  # excluded 'biology' never fetched
    out = tmp_path / "records.jsonl"
    res = ho.normalise(tmp_path / "pages", sp, out)
    assert res["written"] == 4 and res["skipped"]["duplicate"] == 1
    ids = [json.loads(line)["id"] for line in out.read_text(encoding="utf-8").splitlines()]
    assert sorted(ids) == ["oa-W1", "oa-W2", "oa-W3", "oa-W4"]


def test_resume_from_state_uses_saved_cursor(tmp_path):
    sp = tmp_path / "state.json"
    log1 = []
    c1 = ho.Client(tmp_path / "pages", _fetcher(_routes(), log1), max_calls=1)
    assert ho.run_harvest(c1, KW, sp, bio_terms=BIO) == 0
    state = json.loads(sp.read_text(encoding="utf-8"))
    assert state["jobs"]["kw:biomimetics"]["next_cursor"] == "c2"
    assert state["jobs"]["kw:biomimetics"]["status"] == "pending"
    log2 = []
    c2 = ho.Client(tmp_path / "pages", _fetcher(_routes(), log2))
    assert ho.run_harvest(c2, KW, sp, bio_terms=BIO) == 0
    assert ("biomimetics", "*") not in log2  # first page not refetched
    assert log2[0] == ("biomimetics", "c2")
    state = json.loads(sp.read_text(encoding="utf-8"))
    assert all(j["status"] == "done" for j in state["jobs"].values())


def test_budget_stops_at_reserve(tmp_path):
    log = []
    # remaining: 24 after call 1, 23 after call 2; call 3 would leave 22 < reserve 23, so stop
    client = ho.Client(tmp_path / "pages", _fetcher(_routes(), log, remaining=25), reserve=23)
    sp = tmp_path / "state.json"
    assert ho.run_harvest(client, KW, sp, bio_terms=BIO) == 0
    assert client.remaining >= 23  # never dipped under the reserve
    assert len(log) == 2
    assert json.loads(sp.read_text(encoding="utf-8"))["jobs"]


def test_search_cost_respects_reserve(tmp_path):
    client = ho.Client(tmp_path, lambda u, p: (page([]), headers(30)), reserve=20)
    client.get("u", {"a": 1}, cost=1)  # remaining now 30
    with pytest.raises(ho.BudgetStop):
        client.get("u", {"a": 2}, cost=11)  # would leave 19 < 20


def test_429_saves_state_and_exits_3(tmp_path, capsys):
    calls = {"n": 0}

    def fetch(url, params):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ho.RateLimited(4242)
        return _routes()[("biomimetics", "*")], headers(500)

    client = ho.Client(tmp_path / "pages", fetch)
    sp = tmp_path / "state.json"
    assert ho.run_harvest(client, KW, sp, bio_terms=BIO) == ho.EXIT_BUDGET == 3
    err = capsys.readouterr().err
    assert "OpenAlex daily budget used; rerun after 4242 s or set OPENALEX_API_KEY" in err
    state = json.loads(sp.read_text(encoding="utf-8"))
    assert state["jobs"]["kw:biomimetics"]["next_cursor"] == "c2"


def test_decide_include_rule():
    terms = ho.load_scope_terms()
    allt = terms["biomimicry"] + terms["nbs"]
    assert ho.decide_include("Biomimetic materials", allt)[0]
    assert ho.decide_include("bio-inspired robotics", allt)[0]
    assert ho.decide_include("green roofs", allt)[0]
    for generic in ("biology", "bioinformatics", "bioenergy"):
        assert not ho.decide_include(generic, allt)[0]


def test_job_order_biomimicry_first_biggest_first():
    kws = [
        {"id": "x/a", "display_name": "green roofs", "works_count": 900, "include": True},
        {"id": "x/b", "display_name": "biomimetics", "works_count": 10, "include": True},
        {"id": "x/c", "display_name": "bionic design", "works_count": 50, "include": True},
        {"id": "x/d", "display_name": "biology", "works_count": 9999, "include": False},
    ]
    names = [k["display_name"] for k in ho.job_order(kws, ["biomimetic", "bionic"])]
    assert names == ["bionic design", "biomimetics", "green roofs"]
