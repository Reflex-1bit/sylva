"""Fix round 1 for the OpenAlex harvester: scrubbing, overrides, resume/404/atomic/http_fetch."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "nature" / "catalogue"))

_SPEC = importlib.util.spec_from_file_location(
    "catalogue_harvest_openalex_fixes", ROOT / "scripts" / "nature" / "catalogue" / "harvest_openalex.py"
)
ho = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ho)

from scrub import scrub_contacts  # noqa: E402

from app.models.catalogue import RawRecord  # noqa: E402


def _work(n=1, **kw):
    w = {
        "id": f"https://openalex.org/W{n}",
        "doi": f"https://doi.org/10.1/abc{n}",
        "title": f"Lotus-inspired surface {n}",
        "publication_year": 2021,
        "type": "article",
        "keywords": [{"display_name": "biomimetics"}],
        "best_oa_location": {"license": "cc-by"},
        "abstract_inverted_index": {"Lotus": [0], "leaves": [1]},
        "authorships": [],
    }
    w.update(kw)
    return w


def _page(works, nxt=None):
    return {"meta": {"next_cursor": nxt}, "results": works}


def _headers(remaining=900):
    return {"X-RateLimit-Remaining": str(remaining), "X-RateLimit-Reset": "1000"}


KW = [{"id": "https://openalex.org/keywords/biomimetics", "display_name": "biomimetics", "works_count": 10, "include": True}]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Contact a.b@uni.org for data.", "Contact for data."),
        ("Write to jane [at] example [dot] com today", "Write to today"),
        ("Mail jane(at)example.co.uk now", "Mail now"),
        ("See mailto:x@y.org for info", "See for info"),
        ("Plain text stays", "Plain text stays"),
        ("mAP@0.5 improved", "mAP@0.5 improved"),
    ],
)
def test_scrub_contacts(text, expected):
    assert scrub_contacts(text) == expected


def test_work_to_record_scrubs_summary_emails():
    w = _work(1, abstract_inverted_index={"Contact": [0], "a@b.org": [1], "now": [2]})
    rec = ho.work_to_record(w, "2026-10-11")
    assert "@" not in rec.summary and rec.summary == "Contact now"
    only = ho.work_to_record(_work(2, abstract_inverted_index={"a@b.org": [0]}), "2026-10-11")
    assert only.summary is None and only.summary_licence is None


def test_model_rejects_summary_with_email():
    base = ho.work_to_record(_work(1), "2026-10-11").model_dump()
    for bad in ("mail me at a@b.org", "x [at] y [dot] org", "mailto:q"):
        with pytest.raises(ValueError):
            RawRecord(**{**base, "summary": bad})
    RawRecord(**{**base, "summary": "mAP@0.5 is fine"})


def test_overrides_and_deny_stems_survive_rediscover(tmp_path):
    rules = {
        "deny_stems": ["algorithm"],
        "overrides": {
            "bio-inspired-models": {"include": False, "reason": "S4-a"},
            "learning-from-nature": {"include": True, "reason": "in scope"},
        },
    }
    base = "https://openalex.org/keywords/"
    results = [
        {"id": base + "bio-inspired-algorithms", "display_name": "bio-inspired algorithms", "works_count": 5},
        {"id": base + "bio-inspired-models", "display_name": "bio-inspired models", "works_count": 4},
        {"id": base + "learning-from-nature", "display_name": "learning from nature", "works_count": 3},
        {"id": base + "biomimetics", "display_name": "biomimetics", "works_count": 2},
    ]
    scope = {"biomimicry": ["biomimetic", "bio-inspired"], "nbs": []}
    for _ in range(2):  # a rerun gives the same decisions
        client = ho.Client(tmp_path, lambda u, p: ({"results": results}, _headers()))
        kws = {k["id"].rsplit("/", 1)[1]: k for k in ho.discover(client, scope, rules=rules)}
        assert kws["bio-inspired-algorithms"]["include"] is False
        assert "deny stem" in kws["bio-inspired-algorithms"]["reason"]
        assert kws["bio-inspired-models"]["include"] is False
        assert kws["learning-from-nature"]["include"] is True
        assert kws["biomimetics"]["include"] is True


def test_committed_overrides_flip_the_ruled_keywords():
    rules = ho.load_overrides()
    for kid in ("bio-inspired-optimization", "nature-inspired-art", "advanced-bionics"):
        assert rules["overrides"][kid]["include"] is False
    assert rules["overrides"]["learning-from-nature"]["include"] is True
    assert ho.decide_include("bio-inspired algorithms", ["bio-inspired"], "x", rules)[0] is False


def test_normalise_drops_works_only_in_excluded_keywords(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    out_only = _work(1, keywords=[{"display_name": "bio-inspired algorithms"}])
    both = _work(2, keywords=[{"display_name": "bio-inspired algorithms"}, {"display_name": "biomimetics"}])
    (pages / "p.json").write_text(json.dumps(_page([out_only, both])), encoding="utf-8")
    terms = [
        {"display_name": "bio-inspired algorithms", "include": False},
        {"display_name": "biomimetics", "include": True},
    ]
    res = ho.normalise(pages, tmp_path / "s.json", tmp_path / "r.jsonl", terms)
    assert res["written"] == 1 and res["skipped"]["out_of_scope"] == 1


def test_resume_seeds_reserve_from_saved_rate(tmp_path):
    sp = tmp_path / "state.json"
    ho.save_state({"jobs": {}, "pages": {}, "rate": {"remaining": 20, "reset": 5, "seen_on": ho.today()}}, sp)
    calls = []
    client = ho.Client(tmp_path / "pages", lambda u, p: calls.append(1) or (_page([]), _headers()), reserve=20)
    assert ho.run_harvest(client, KW, sp, bio_terms=["biomimetic"]) == 0
    assert calls == []  # 20 - 1 < reserve 20: no call made


def test_404_leaves_job_pending_not_done(tmp_path):
    sp = tmp_path / "state.json"
    client = ho.Client(tmp_path / "pages", lambda u, p: (None, _headers()))
    with pytest.raises(RuntimeError):
        ho.run_harvest(client, KW, sp, bio_terms=["biomimetic"])
    job = json.loads(sp.read_text(encoding="utf-8"))["jobs"]["kw:biomimetics"]
    assert job["status"] == "pending" and job["error"] == "404"


def test_cache_write_is_atomic(tmp_path):
    client = ho.Client(tmp_path, lambda u, p: (_page([]), _headers()))
    client.get("u", {"a": 1})
    assert list(tmp_path.glob("*.tmp")) == []
    assert len(list(tmp_path.glob("*.json"))) == 1


class _Resp:
    def __init__(self, status, headers=None, body=None):
        self.status_code = status
        self.headers = headers or {}
        self._body = body if body is not None else {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_http_fetch_429_raises_ratelimited(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(429, {"X-RateLimit-Reset": "99"}))
    with pytest.raises(ho.RateLimited) as exc:
        ho.http_fetch("https://x", {})
    assert exc.value.reset == 99


def test_http_fetch_retries_5xx_then_succeeds(monkeypatch):
    import httpx

    seq = [_Resp(500), _Resp(500), _Resp(200, {"X-RateLimit-Remaining": "5"}, {"ok": True})]
    monkeypatch.setattr(httpx, "get", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(ho.time, "sleep", lambda s: None)
    data, headers = ho.http_fetch("https://x", {})
    assert data == {"ok": True} and headers["X-RateLimit-Remaining"] == "5" and seq == []
