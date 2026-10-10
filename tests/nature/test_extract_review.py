import asyncio
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "nature"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ex = _load("extract_mechanisms")
rv = _load("review")

TEXT = "Intro words. The leaf surface repels water droplets very effectively. Outro."
SENTENCE = "The leaf surface repels water droplets very effectively."


def _model_output(**over):
    out = {
        "kind": "mechanism",
        "title": "Leaf water repellence",
        "summary": "Leaf microstructure makes water roll off.",
        "areas": ["form"],
        "functions": ["shed-water"],
        "sector_tags": ["textiles"],
        "organism": None,
        "trait": "leaf surface",
        "structure": "micro bumps",
        "mechanism": "rough surface keeps droplets round",
        "trait_type": "morphological",
        "performance": [],
        "known_products": [],
        "popular_claim_note": None,
        "confidence": "medium",
        "caveat": "One paper; not reproduced.",
        "supporting_sentence": SENTENCE,
    }
    out.update(over)
    return out


def _work(licence="cc-by"):
    loc = {"license": licence, "landing_page_url": "https://example.org/paper"}
    return {
        "title": "A leaf paper",
        "publication_year": 2020,
        "topics": [{"display_name": "Plant surfaces"}],
        "open_access": {"is_oa": True},
        "best_oa_location": loc,
        "primary_location": loc,
    }


@pytest.fixture
def data_dir(tmp_path):
    shutil.copy(ROOT / "data" / "nature" / "taxonomy.json", tmp_path / "taxonomy.json")
    return tmp_path


def _taxonomy(d):
    return json.loads((d / "taxonomy.json").read_text(encoding="utf-8"))


def _run(data_dir, dois, outputs, work=None, monkeypatch=None, with_text=True, calls=None):
    work = work or _work()
    prompts = [] if calls is None else calls

    async def fake_gemini(api_key, prompt):
        prompts.append(prompt)
        out = outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out, "fake-model"

    monkeypatch.setattr(ex, "_call_gemini", fake_gemini)
    return asyncio.run(
        ex.extract_all(
            dois,
            data_dir,
            "key",
            _taxonomy(data_dir),
            fetch=lambda url, params=None: work,
            fetch_text=lambda url: TEXT,
            with_text=with_text,
        )
    )


def _staged(d):
    return json.loads((d / "library_staging.json").read_text(encoding="utf-8"))


# ── extraction ────────────────────────────────────────────────────────────────


def test_sentence_kept_when_substring_and_open_licence(data_dir, monkeypatch):
    res = _run(data_dir, ["10.1/a"], [_model_output()], monkeypatch=monkeypatch)
    assert res["staged"] == 1
    rec = _staged(data_dir)[0]
    assert rec["id"] == "stg-0001"
    ev = rec["evidence"][0]
    assert ev["supporting_sentence"] == SENTENCE
    assert ev["licence"] == "CC-BY" and ev["doi"] == "10.1/a"
    assert rec["provenance"]["status"] == "ai_extracted"


def test_sentence_not_in_text_becomes_null(data_dir, monkeypatch):
    out = _model_output(supporting_sentence="A sentence the paper never contains.")
    _run(data_dir, ["10.1/a"], [out], monkeypatch=monkeypatch)
    assert _staged(data_dir)[0]["evidence"][0]["supporting_sentence"] is None


@pytest.mark.parametrize("licence", ["cc-by-sa", "cc-by-nc", "cc-by-nd", "publisher-specific-oa", None])
def test_disallowed_licence_no_text_no_sentence(data_dir, monkeypatch, licence):
    prompts = []
    _run(data_dir, ["10.1/a"], [_model_output()], work=_work(licence), monkeypatch=monkeypatch, calls=prompts)
    ev = _staged(data_dir)[0]["evidence"][0]
    assert ev["supporting_sentence"] is None and ev["licence"] is None
    assert "The leaf surface repels" not in prompts[0]
    assert "Title: A leaf paper" in prompts[0] and "Plant surfaces" in prompts[0]


def test_cc0_allowed_and_text_in_prompt_truncated(data_dir, monkeypatch):
    prompts = []
    long_text = "x " * 30000
    monkeypatch.setattr(ex, "MAX_TEXT_CHARS", 100)
    work = _work("cc0")

    async def fake(api_key, prompt):
        prompts.append(prompt)
        return _model_output(supporting_sentence=None), "m"

    monkeypatch.setattr(ex, "_call_gemini", fake)
    asyncio.run(
        ex.extract_all(["10.1/a"], data_dir, "k", _taxonomy(data_dir),
                       fetch=lambda u, p=None: work, fetch_text=lambda u: long_text, with_text=True)
    )
    assert _staged(data_dir)[0]["evidence"][0]["licence"] == "CC0"
    assert "x " * 50 in prompts[0] and "x " * 51 not in prompts[0]


def test_abstract_never_requested_or_stored(data_dir, monkeypatch):
    work = _work()
    work["abstract_inverted_index"] = {"secretabstractword": [0]}
    prompts = []
    _run(data_dir, ["10.1/a"], [_model_output()], work=work, monkeypatch=monkeypatch, calls=prompts)
    assert "abstract" not in ex.SELECT
    assert "secretabstractword" not in prompts[0]
    assert "secretabstractword" not in (data_dir / "library_staging.json").read_text(encoding="utf-8")


def test_invalid_output_dropped(data_dir, monkeypatch):
    outputs = [
        _model_output(kind="banana"),  # invalid enum
        _model_output(functions=["not-a-function"]),  # unknown taxonomy id
        _model_output(mechanism=None),  # mechanism required
        {"extra_field": 1},  # junk
    ]
    res = _run(data_dir, ["10.1/a", "10.1/b", "10.1/c", "10.1/d"], outputs, monkeypatch=monkeypatch)
    assert res["staged"] == 0 and len(res["dropped"]) == 4
    assert not (data_dir / "library_staging.json").exists()


def test_biochemical_gets_legal_review_pending(data_dir, monkeypatch):
    _run(data_dir, ["10.1/a"], [_model_output(trait_type="biochemical")], monkeypatch=monkeypatch)
    assert _staged(data_dir)[0]["legal_review"] == "pending"


def test_ids_increment_and_existing_doi_skipped(data_dir, monkeypatch):
    _run(data_dir, ["10.1/a"], [_model_output()], monkeypatch=monkeypatch)
    res = _run(data_dir, ["10.1/a", "10.1/b"], [_model_output()], monkeypatch=monkeypatch)
    assert res["skipped_existing"] == 1 and res["staged"] == 1
    assert [r["id"] for r in _staged(data_dir)] == ["stg-0001", "stg-0002"]


def test_rate_limit_retried(data_dir, monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(ex.asyncio, "sleep", fake_sleep)
    res = _run(data_dir, ["10.1/a"], [RuntimeError("m: HTTP 429 quota"), _model_output()], monkeypatch=monkeypatch)
    assert res["staged"] == 1 and sleeps


def test_main_without_key_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ex, "_api_key", lambda: None)
    dois = tmp_path / "d.txt"
    dois.write_text("10.1/a\n", encoding="utf-8")
    assert ex.main(["--dois", str(dois), "--data-dir", str(tmp_path)]) == 0
    assert "not set" in capsys.readouterr().out
    assert not (tmp_path / "library_staging.json").exists()


def test_licence_and_html_helpers():
    assert ex.allowed_licence("CC-BY") == "CC-BY"
    assert ex.allowed_licence("cc-by-sa") is None
    assert ex.html_to_text("<p>Hi <script>bad()</script><b>there</b></p>") == "Hi there"


# ── review ────────────────────────────────────────────────────────────────────


def _lib_record(rid, **over):
    rec = json.loads((ROOT / "data" / "nature" / "library.json").read_text(encoding="utf-8"))[0]
    rec["id"] = rid
    rec.update(over)
    return rec


def _stage_record(data_dir, monkeypatch, **over):
    _run(data_dir, ["10.1/a"], [_model_output(**over)], monkeypatch=monkeypatch)


def _write_library(d, records):
    (d / "library.json").write_text(json.dumps(records), encoding="utf-8")


def _log(d):
    return [json.loads(x) for x in (d / "review_log.jsonl").read_text(encoding="utf-8").splitlines()]


def test_promote_uses_max_plus_one_and_logs(data_dir, monkeypatch):
    _write_library(data_dir, [_lib_record("lib-0001"), _lib_record("lib-0007")])  # gap: max+1, not len+1
    _stage_record(data_dir, monkeypatch)
    assert rv.main(["--data-dir", str(data_dir), "promote", "stg-0001", "--by", "Ana"]) == 0
    lib = json.loads((data_dir / "library.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in lib] == ["lib-0001", "lib-0007", "lib-0008"]
    assert lib[-1]["provenance"]["status"] == "ai_extracted"
    assert _staged(data_dir) == []
    assert _log(data_dir)[-1]["action"] == "promote" and _log(data_dir)[-1]["by"] == "Ana"
    assert not list(data_dir.glob("*.tmp"))


def test_promote_biochemical_is_pending(data_dir, monkeypatch):
    _write_library(data_dir, [_lib_record("lib-0001")])
    _stage_record(data_dir, monkeypatch, trait_type="genetic")
    staged = _staged(data_dir)
    staged[0]["legal_review"] = "cleared"  # a hand-edited staging file must not bypass the gate
    (data_dir / "library_staging.json").write_text(json.dumps(staged), encoding="utf-8")
    assert rv.main(["--data-dir", str(data_dir), "promote", "stg-0001", "--by", "Ana"]) == 0
    lib = json.loads((data_dir / "library.json").read_text(encoding="utf-8"))
    assert lib[-1]["legal_review"] == "pending"


def test_promote_invalid_staged_record_fails_and_keeps_files(data_dir, monkeypatch, capsys):
    _write_library(data_dir, [_lib_record("lib-0001")])
    _stage_record(data_dir, monkeypatch)
    staged = _staged(data_dir)
    staged[0]["kind"] = "banana"
    (data_dir / "library_staging.json").write_text(json.dumps(staged), encoding="utf-8")
    assert rv.main(["--data-dir", str(data_dir), "promote", "stg-0001", "--by", "Ana"]) == 1
    assert len(json.loads((data_dir / "library.json").read_text(encoding="utf-8"))) == 1
    assert len(_staged(data_dir)) == 1


def test_promoted_library_passes_validator(data_dir, monkeypatch):
    shutil.copy(ROOT / "data" / "nature" / "library.json", data_dir / "library.json")
    shutil.copy(ROOT / "data" / "nature" / "industry_map.json", data_dir / "industry_map.json")
    _stage_record(data_dir, monkeypatch)
    assert rv.main(["--data-dir", str(data_dir), "promote", "stg-0001", "--by", "Ana"]) == 0
    validator = _load("validate_db")
    assert validator.main(["--data-dir", str(data_dir)]) == 0
    lib = json.loads((data_dir / "library.json").read_text(encoding="utf-8"))
    assert lib[-1]["id"] == "lib-0067"


def test_validate_and_dispute_mutate_and_log(data_dir):
    _write_library(data_dir, [_lib_record("lib-0001"), _lib_record("lib-0002")])
    assert rv.main(["--data-dir", str(data_dir), "validate", "lib-0001", "--by", "Dr Ruiz"]) == 0
    assert rv.main(["--data-dir", str(data_dir), "dispute", "lib-0002", "--by", "Dr Ruiz", "--reason", "claim not replicated"]) == 0
    lib = json.loads((data_dir / "library.json").read_text(encoding="utf-8"))
    prov = lib[0]["provenance"]
    assert prov["status"] == "expert_validated" and prov["validated_by"] == "Dr Ruiz" and prov["validated_on"]
    assert lib[1]["provenance"]["status"] == "disputed"
    assert lib[1]["caveat"].endswith("Disputed by Dr Ruiz: claim not replicated")
    assert [e["action"] for e in _log(data_dir)] == ["validate", "dispute"]


def test_unknown_ids_fail_clearly(data_dir, capsys):
    _write_library(data_dir, [_lib_record("lib-0001")])
    assert rv.main(["--data-dir", str(data_dir), "validate", "lib-0099", "--by", "x"]) == 1
    assert "unknown library id lib-0099" in capsys.readouterr().err
    assert rv.main(["--data-dir", str(data_dir), "dispute", "stg-0001", "--by", "x", "--reason", "r"]) == 1
    assert rv.main(["--data-dir", str(data_dir), "promote", "stg-0009", "--by", "x"]) == 1
    assert rv.main(["--data-dir", str(data_dir), "show", "lib-0099"]) == 1


def test_list_and_show_log_open_time(data_dir, monkeypatch, capsys):
    _write_library(data_dir, [_lib_record("lib-0001")])
    _stage_record(data_dir, monkeypatch)
    assert rv.main(["--data-dir", str(data_dir), "list"]) == 0
    assert "stg-0001" in capsys.readouterr().out
    assert rv.main(["--data-dir", str(data_dir), "show", "stg-0001"]) == 0
    assert '"id": "stg-0001"' in capsys.readouterr().out
    assert _log(data_dir)[-1]["action"] == "show"


def test_missing_required_args_exit_nonzero():
    with pytest.raises(SystemExit) as e:
        rv.main(["promote", "stg-0001"])
    assert e.value.code != 0


# ── timing ────────────────────────────────────────────────────────────────────


def _entry(t0, minutes, action, rec_id):
    return {"ts": (t0 + timedelta(minutes=minutes)).isoformat(), "action": action, "id": rec_id, "by": "x"}


def test_timing_median_uses_latest_show_and_skips_unshown():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    entries = [
        _entry(t0, 0, "show", "lib-0001"),
        _entry(t0, 50, "show", "lib-0001"),  # latest show before the decision wins
        _entry(t0, 60, "validate", "lib-0001"),  # 10 min
        _entry(t0, 0, "show", "lib-0002"),
        _entry(t0, 30, "dispute", "lib-0002"),  # 30 min
        _entry(t0, 0, "show", "lib-0003"),
        _entry(t0, 20, "validate", "lib-0003"),  # 20 min
        _entry(t0, 5, "validate", "lib-0004"),  # no show: skipped
        _entry(t0, 90, "show", "lib-0005"),  # show only: ignored
    ]
    res = rv.compute_timing(entries)
    assert res["median_minutes"] == 20
    assert res["records_measured"] == 3
    assert res["records_skipped_no_show"] == 1 and res["skipped_ids"] == ["lib-0004"]
    assert res["per_record_minutes"]["lib-0001"] == 10


def test_timing_cli_text_and_json(data_dir, capsys):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    lines = [_entry(t0, 0, "show", "lib-0001"), _entry(t0, 12, "validate", "lib-0001")]
    (data_dir / "review_log.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    assert rv.main(["--data-dir", str(data_dir), "timing"]) == 0
    assert "Median minutes" in capsys.readouterr().out
    assert rv.main(["--data-dir", str(data_dir), "timing", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["median_minutes"] == 12


def test_timing_empty_log(data_dir, capsys):
    assert rv.main(["--data-dir", str(data_dir), "timing", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["median_minutes"] is None


# â”€â”€ fix round 1 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_promote_is_idempotent_after_crash_between_writes(data_dir, monkeypatch):
    _write_library(data_dir, [_lib_record("lib-0001")])
    _stage_record(data_dir, monkeypatch)
    staging_before = (data_dir / "library_staging.json").read_text(encoding="utf-8")
    assert rv.main(["--data-dir", str(data_dir), "promote", "stg-0001", "--by", "Ana"]) == 0
    # simulate the crash: library written, staging not cleaned
    (data_dir / "library_staging.json").write_text(staging_before, encoding="utf-8")
    assert rv.main(["--data-dir", str(data_dir), "promote", "stg-0001", "--by", "Ana"]) == 0
    lib = json.loads((data_dir / "library.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in lib] == ["lib-0001", "lib-0002"]
    assert _staged(data_dir) == []
    assert _log(data_dir)[-1]["action"] == "promote_dedup"


def test_promote_dedup_by_title_when_no_doi(data_dir):
    lib_rec = _lib_record("lib-0001")
    stg = json.loads(json.dumps(lib_rec))
    stg["id"] = "stg-0001"
    for rec in (lib_rec, stg):
        for e in rec["evidence"]:
            e["doi"] = None
    _write_library(data_dir, [lib_rec])
    (data_dir / "library_staging.json").write_text(json.dumps([stg]), encoding="utf-8")
    assert rv.main(["--data-dir", str(data_dir), "promote", "stg-0001", "--by", "Ana"]) == 0
    assert len(json.loads((data_dir / "library.json").read_text(encoding="utf-8"))) == 1
    assert _staged(data_dir) == []


def test_promote_forces_ai_extracted(data_dir, monkeypatch):
    _write_library(data_dir, [_lib_record("lib-0001")])
    _stage_record(data_dir, monkeypatch)
    staged = _staged(data_dir)
    staged[0]["provenance"].update(status="expert_validated", validated_by="Fake", validated_on="2026-01-01")
    (data_dir / "library_staging.json").write_text(json.dumps(staged), encoding="utf-8")
    assert rv.main(["--data-dir", str(data_dir), "promote", "stg-0001", "--by", "Ana"]) == 0
    prov = json.loads((data_dir / "library.json").read_text(encoding="utf-8"))[-1]["provenance"]
    assert prov["status"] == "ai_extracted" and prov["validated_by"] is None and prov["validated_on"] is None


def test_fetch_oa_text_rejects_non_http_scheme(capsys):
    assert ex.fetch_oa_text("file:///etc/passwd") == ""
    assert ex.fetch_oa_text("ftp://example.org/x") == ""
    assert "only http/https" in capsys.readouterr().err


def test_fetch_oa_text_ok_and_size_cap(monkeypatch, capsys):
    import httpx

    ok = httpx.MockTransport(lambda r: httpx.Response(200, html="<p>Hello <b>world</b></p>"))
    assert ex.fetch_oa_text("https://example.org/a", transport=ok) == "Hello world"

    monkeypatch.setattr(ex, "MAX_DOWNLOAD_BYTES", 1000)
    big = httpx.MockTransport(lambda r: httpx.Response(200, content=b"a" * 5000, headers={"content-type": "text/html"}))
    assert ex.fetch_oa_text("https://example.org/big", transport=big) == ""
    assert "over 1000 bytes" in capsys.readouterr().err


def test_fetch_oa_text_logs_http_error(capsys):
    import httpx

    bad = httpx.MockTransport(lambda r: httpx.Response(500))
    assert ex.fetch_oa_text("https://example.org/e", transport=bad) == ""
    assert "HTTPStatusError" in capsys.readouterr().err


def test_untrusted_model_fields_are_stripped(data_dir, monkeypatch):
    out = _model_output(
        organism={"scientific_name": "Nelumbo nucifera", "common_names": [], "gbif_usage_key": 123, "gbif_match_type": "EXACT"},
        performance=[{"metric": "angle", "value": 150, "units": "deg", "measured_in": "field"}],
        see_also=["https://asknature.org/x"],
        contributors=[{"name": "Fake", "role": "expert"}],
        source_region={"region": "Mars"},
    )
    _run(data_dir, ["10.1/a"], [out], monkeypatch=monkeypatch)
    rec = _staged(data_dir)[0]
    assert rec["organism"]["gbif_usage_key"] is None and rec["organism"]["gbif_match_type"] is None
    assert rec["performance"][0]["measured_in"] == "literature"
    assert rec["see_also"] == [] and rec["contributors"] == [] and rec["source_region"] is None


def test_timing_even_count_median():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    entries = [
        _entry(t0, 0, "show", "lib-0001"), _entry(t0, 10, "validate", "lib-0001"),
        _entry(t0, 0, "show", "lib-0002"), _entry(t0, 30, "validate", "lib-0002"),
    ]
    assert rv.compute_timing(entries)["median_minutes"] == 20


def test_same_doi_different_mechanism_is_promoted_not_deduped(data_dir):
    lib_rec = _lib_record("lib-0001")
    stg = json.loads(json.dumps(lib_rec))
    stg["id"] = "stg-0001"
    stg["title"] = "A different mechanism from the same paper"
    stg["mechanism"] = "a different mechanism described in the same paper"
    stg["provenance"]["status"] = "ai_extracted"
    _write_library(data_dir, [lib_rec])
    (data_dir / "library_staging.json").write_text(json.dumps([stg]), encoding="utf-8")
    assert rv.main(["--data-dir", str(data_dir), "promote", "stg-0001", "--by", "Ana"]) == 0
    lib = json.loads((data_dir / "library.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in lib] == ["lib-0001", "lib-0002"]
    assert lib[1]["title"] == stg["title"]
    assert _staged(data_dir) == []
    assert _log(data_dir)[-1]["action"] == "promote"

