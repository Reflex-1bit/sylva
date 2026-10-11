import gzip
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

CAT = Path(__file__).resolve().parents[3] / "scripts" / "nature" / "catalogue"
sys.path.insert(0, str(CAT))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, CAT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


scope = _load("scope")
cordis = _load("harvest_cordis")
ca = _load("harvest_climate_adapt")


# ── scope ─────────────────────────────────────────────────────────────────────


def test_scope_whole_word_rule():
    m = scope.ScopeMatcher(scope.load_scope_terms())
    assert m.first("A bionic hand") == "bionic"
    assert m.first("Research on bionics") in ("bionic", "bionics")
    assert m.first("The symbionic relationship") is None
    assert m.first("antibionic") is None
    assert m.first("Bio-inspired design") is not None
    assert m.first("Bio inspired design") is not None
    assert m.first("Nature-based solutions for cities") is not None
    assert m.first("CONSTRUCTED WETLANDS and Green Roofs") is not None
    assert m.first("Biomimétique") is None  # French form is not in the term list
    assert m.first("nothing relevant here") is None


def test_scope_accent_fold():
    m = scope.ScopeMatcher(["bioinspired"])
    assert m.first("BIOINSPIRÉD") == "bioinspired"
    assert m.first("Bióinspired materials") == "bioinspired"


def test_cut_summary_sentence_end():
    text = ("First sentence here. " * 100).strip()
    out = scope.cut_summary(text, 1500)
    assert len(out) <= 1500 and out.endswith(".")
    assert scope.cut_summary("a   b\n c") == "a b c"
    long_no_end = "word " * 600
    assert len(scope.cut_summary(long_no_end, 1500)) <= 1503


# ── CORDIS ────────────────────────────────────────────────────────────────────

H2020_PROJECT = (
    '"id";"acronym";"status";"title";"startDate";"endDate";"objective";"grantDoi";"keywords"\n'
    '"101";"BIO";"CLOSED";"Bionic skin";"2016-03-01";"2019-02-28";"We build bionic skin.\nSecond line with ""quotes"". '
    'contact: jane.doe@example.org";"10.3030/101";"skin, robotics;sensors"\n'
    '"102";"SYM";"CLOSED";"Symbionic study";"2017-01-01";"2018-01-01";"A symbionic relationship.";"";"x"\n'
)
H2020_ORG = (
    '"projectID";"name";"country";"role";"contactForm";"organizationURL";"street"\n'
    '"101";"Beta Ltd";"UK";"participant";"SECRET-CONTACT";"http://secret";"SECRET-STREET"\n'
    '"101";"Alpha SA";"EL";"coordinator";"SECRET-CONTACT";"http://secret";"SECRET-STREET"\n'
    '"101";"Gamma GmbH";"DE";"participant";"";"";""\n'
    '"102";"Other";"FR";"coordinator";"";"";""\n'
)
H2020_SCI = (
    '"euroSciVocCode";"euroSciVocPath";"euroSciVocTitle";"euroSciVocDescription";"projectID"\n'
    '"/1/2";"engineering and technology/materials engineering";"materials engineering";"";"101"\n'
)
# FP7: different column order, projectID first in euroSciVoc, no keywords column.
FP7_PROJECT = (
    '"id";"acronym";"status";"title";"startDate";"endDate";"totalCost";"ecMaxContribution";"legalBasis";"topics";'
    '"ecSignatureDate";"frameworkProgramme";"masterCall";"subCall";"fundingScheme";"nature";"objective";"contentUpdateDate";"rcn";"grantDoi"\n'
    '"201";"BM";"CLOSED";"Biomimetic coating";"2011-05-01";"2014-04-30";"1";"1";"FP7";"T";"";"FP7";"";"";"";"";'
    '"Biomimetic coatings.";"";"1";"https://doi.org/10.3030/201"\n'
)
FP7_SCI = (
    '"projectID";"euroSciVocCode";"euroSciVocPath";"euroSciVocTitle";"euroSciVocDescription"\n'
    '"201";"/1";"natural sciences/chemical sciences";"chemical sciences";""\n'
)
FP7_ORG = H2020_ORG.replace('"101"', '"201"').replace('"102"', '"202"')


def _zip(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content.encode("utf-8"))


def test_cordis_header_mapping_and_fields(tmp_path):
    z = tmp_path / "h.zip"
    _zip(z, {"project.csv": H2020_PROJECT, "organization.csv": H2020_ORG, "euroSciVoc.csv": H2020_SCI})
    matcher = scope.ScopeMatcher(scope.load_scope_terms())
    recs, scanned, distinct = cordis.process_zip(z, matcher, "2026-10-11")
    assert scanned == 2
    assert [r.id for r in recs] == ["cd-101"]  # symbionic is out
    r = recs[0]
    assert r.countries == ["GR", "GB", "DE"]  # coordinator first, EL->GR, UK->GB
    assert r.organisations == ["Alpha SA", "Beta Ltd", "Gamma GmbH"]
    assert r.doi == "10.3030/101" and r.year == 2016
    assert r.keywords[:3] == ["skin", "robotics", "sensors"] and "scope:bionic" in r.keywords
    assert r.source_codes.euroscivoc == ["materials engineering", "engineering and technology"]
    assert r.summary_licence == "CC-BY-4.0" and r.url == "https://cordis.europa.eu/project/id/101"
    assert "Second line" in r.summary and '"quotes"' in r.summary
    assert "jane.doe@example.org" not in r.summary and "@" not in r.summary
    assert {"materials engineering", "engineering and technology"} <= distinct


def test_cordis_no_contact_columns_read(tmp_path):
    z = tmp_path / "h.zip"
    _zip(z, {"organization.csv": H2020_ORG})
    with zipfile.ZipFile(z) as zf:
        rows = list(cordis.read_csv(zf, "organization.csv", cordis.ORG_COLUMNS))
    assert set(rows[0]) == {"projectID", "name", "country", "role"}
    assert not any("SECRET" in v for row in rows for v in row.values())
    orgs = cordis.load_organisations.__defaults__  # no hidden state
    assert orgs is None
    # and the records never carry the sentinel
    zz = tmp_path / "p.zip"
    _zip(zz, {"project.csv": H2020_PROJECT, "organization.csv": H2020_ORG, "euroSciVoc.csv": H2020_SCI})
    recs, _, _ = cordis.process_zip(zz, scope.ScopeMatcher(scope.load_scope_terms()), "2026-10-11")
    assert "SECRET" not in recs[0].model_dump_json()


def test_cordis_fp7_order(tmp_path):
    z = tmp_path / "f.zip"
    _zip(z, {"project.csv": FP7_PROJECT, "organization.csv": FP7_ORG, "euroSciVoc.csv": FP7_SCI})
    recs, scanned, _ = cordis.process_zip(z, scope.ScopeMatcher(scope.load_scope_terms()), "2026-10-11")
    assert scanned == 1 and recs[0].id == "cd-201"
    assert recs[0].doi == "10.3030/201" and recs[0].year == 2011
    assert recs[0].source_codes.euroscivoc == ["chemical sciences", "natural sciences"]
    assert recs[0].keywords == ["scope:biomimetic"]


def test_cordis_normalise_writes_terms(tmp_path):
    src = tmp_path / "raw"
    src.mkdir()
    _zip(src / cordis.PROGRAMMES["h2020"], {"project.csv": H2020_PROJECT, "organization.csv": H2020_ORG, "euroSciVoc.csv": H2020_SCI})
    _zip(src / cordis.PROGRAMMES["fp7"], {"project.csv": FP7_PROJECT, "organization.csv": FP7_ORG, "euroSciVoc.csv": FP7_SCI})
    _zip(src / cordis.PROGRAMMES["horizon"], {"project.csv": H2020_PROJECT.replace('"101"', '"301"'),
                                              "organization.csv": H2020_ORG.replace('"101"', '"301"'),
                                              "euroSciVoc.csv": H2020_SCI.replace('"101"', '"301"')})
    out = tmp_path / "records.jsonl"
    terms = tmp_path / "terms.txt"
    stats = cordis.normalise(src, out, terms)
    assert stats["kept"] == {"h2020": 1, "fp7": 1, "horizon": 1} and stats["total"] == 3
    assert "chemical sciences" in terms.read_text(encoding="utf-8").splitlines()
    assert len(out.read_text(encoding="utf-8").splitlines()) == 3


def test_cordis_helpers():
    assert cordis.fix_country("EL") == "GR" and cordis.fix_country("uk") == "GB" and cordis.fix_country("") is None
    assert cordis.bare_doi("https://doi.org/10.1/x") == "10.1/x" and cordis.bare_doi("nope") is None
    assert cordis.split_keywords("a, b;c,,a") == ["a", "b", "c"]


# ── Climate-ADAPT ─────────────────────────────────────────────────────────────

CASE = {
    "title": "Moor protection in Allgäu",
    "description": "None",
    "publication_date": "2018-01-01",
    "rights": "",
    "long_description": {"content-type": "text/html", "data": "<p>Moors &amp; bogs.</p><ul><li>One</li><li>Two</li></ul>"
                         "<script>x()</script><p>Mail me: a.b@example.org</p>"},
    "solutions": {"data": "<p>Rewilding of peat.</p>"},
    "sectors": [{"title": "Biodiversity protection", "token": "B"}, {"title": "Mountain areas", "token": "M"}],
    "climate_impacts": [{"title": "Water Scarcity", "token": "W"}],
    "elements": [{"title": "Nature-based solutions", "token": "NATUREBASEDSOL"}],
    "adaptationoptions": [{"title": "Enhancing Ecological Networks"}],
    "cca_adaptation_options": ["Adaptive management of natural resources"],
    "geographic": {"countries": ["Germany", "Atlantis", "Czech Republic"]},
    "keywords": ["moor", "bog"],
}


def _matchers():
    return scope.ScopeMatcher(scope.load_scope_terms()), scope.ScopeMatcher(ca.ECO_OPTION_TERMS)


def test_html_to_text():
    txt = ca.html_to_text(CASE["long_description"])
    assert txt.startswith("Moors & bogs. One Two") and "x()" not in txt and "<" not in txt
    assert ca.html_to_text("None") == "" and ca.html_to_text(None) == ""


def test_ca_record_mapping():
    m, eco = _matchers()
    reasons = ca.scope_reasons(CASE, m, eco)
    assert "scope:rewilding" in reasons and "scope:element:Nature-based solutions" in reasons
    assert "scope:option:Enhancing Ecological Networks" in reasons
    rec, dropped = ca.build_record("moor-protection", CASE, reasons, "2026-10-11")
    assert dropped == 1 and rec.countries == ["DE", "CZ"]
    assert rec.id == "ca-moor-protection" and rec.year == 2018 and rec.organisations == []
    assert rec.source_codes.climate_adapt_sectors == ["Biodiversity protection", "Mountain areas"]
    assert rec.keywords[:3] == ["moor", "bog", "Water Scarcity"]
    assert "example.org" not in rec.summary and rec.summary_licence == "CC-BY-4.0"
    assert rec.url == "https://climate-adapt.eea.europa.eu/en/metadata/case-studies/moor-protection"


def test_ca_scope_drop_and_own_copyright():
    m, eco = _matchers()
    plain = {"title": "Dike raising", "long_description": {"data": "<p>Higher dikes.</p>"},
             "adaptationoptions": [{"title": "Sea walls"}], "elements": []}
    assert ca.scope_reasons(plain, m, eco) == []
    other = dict(CASE, rights="© Some Agency, all rights reserved")
    rec, _ = ca.build_record("x", other, ["scope:x"], "2026-10-11")
    assert rec.summary is None and rec.summary_licence is None
    cc = dict(CASE, rights="CC BY 4.0")
    assert ca.build_record("x", cc, ["scope:x"], "2026-10-11")[0].summary is not None


def test_ca_pace_and_robots(tmp_path):
    clock = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        clock[0] += s

    calls = []
    robots = b"User-agent: *\nDisallow: /sandbox\nDisallow: /en/observatory/metadata/\n"
    index = b"<sitemapindex><sitemap><loc>https://climate-adapt.eea.europa.eu/sitemap1.xml.gz</loc></sitemap></sitemapindex>"
    urls = (
        b"<urlset>"
        b"<url><loc>https://climate-adapt.eea.europa.eu/en/metadata/case-studies/good-one</loc></url>"
        b"<url><loc>https://climate-adapt.eea.europa.eu/de/metadata/case-studies/good-one</loc></url>"
        b"<url><loc>https://climate-adapt.eea.europa.eu/en/metadata/case-studies/pic/@@images/x.jpg</loc></url>"
        b"</urlset>"
    )

    def fetch(url, headers):
        calls.append((url, dict(headers)))
        if url.endswith("robots.txt"):
            return robots
        if url.endswith("sitemap-index.xml"):
            return index
        if url.endswith(".xml.gz"):
            return gzip.compress(urls)
        if "++api++" in url:
            return json.dumps(CASE).encode("utf-8")
        return None

    client = ca.Client(fetch=fetch, pace=1.0, sleep=sleep, clock=lambda: clock[0])
    stats = ca.harvest(client, tmp_path / "pages", tmp_path / "urls.txt")
    assert stats["listed"] == 1 and stats["fetched"] == 1
    assert (tmp_path / "pages" / "good-one.json").exists()
    assert ca.PACE_SECONDS == 1.0 and all(s >= 0.99 for s in slept) and len(slept) == client.requests - 1
    # no email, no image fetch, JSON accepted, project user agent
    for url, headers in calls:
        blob = url + json.dumps(headers)
        assert "@" not in blob.replace("@@", "") and "mailto" not in blob and "email" not in blob.lower()
        assert not url.endswith((".jpg", ".png"))
    assert all(h["User-Agent"] == "SylvaNatureCatalogue/0.1" for _, h in calls)
    assert [h for u, h in calls if "++api++" in u][0]["Accept"] == "application/json"
    # robots rules are honoured
    assert not client.allowed("https://climate-adapt.eea.europa.eu/sandbox/x")
    assert client.allowed("https://climate-adapt.eea.europa.eu/en/metadata/case-studies/good-one")


def test_ca_normalise(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "moor.json").write_text(json.dumps(CASE), encoding="utf-8")
    (pages / "dike.json").write_text(json.dumps({"title": "Dike", "long_description": {"data": "<p>x</p>"}}), encoding="utf-8")
    stats = ca.normalise(pages, tmp_path / "records.jsonl")
    assert stats["kept"] == 1 and stats["dropped"] == 1 and stats["unknown_countries"] == 1
    assert stats["with_summary"] == 1
    assert io.StringIO(((tmp_path / "records.jsonl").read_text(encoding="utf-8"))).readline().startswith("{")
