"""Offline tests for citens/library.py + the new export formats.

No network: duplicate grouping over constructed papers, notes over a temp
data home, CSL-JSON / EndNote XML well-formedness.
"""

from __future__ import annotations

import json
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from citens.config import settings  # noqa: E402
from citens.grounding.citations import CitationTable  # noqa: E402
from citens.library import (  # noqa: E402
    add_note,
    dedup_pool,
    duplicate_groups,
    notes_path,
    read_notes,
)
from citens.models import Paper  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} - {name}" + (f" ({detail})" if detail and not cond else ""))


def _p(title: str, doi=None, url="", authors=("Zheng Zhao", "Wei Fan"),
       cites=10, source="OpenAlex (ACL)", pdf=None, found_by=None,
       venue="") -> Paper:
    return Paper(title=title, authors=list(authors), year=2023, doi=doi,
                 url=url or (f"https://doi.org/{doi}" if doi else ""),
                 citation_count=cites, source=source, pdf_url=pdf,
                 found_by=list(found_by or []), venue=venue)


# ── duplicate groups ──────────────────────────────────────────────────────────

preprint = _p("Structured Attention Networks", url="https://arxiv.org/abs/1709.04579",
              source="arXiv", pdf="https://arxiv.org/pdf/1709.04579", cites=0,
              found_by=["agent"])
published = _p("Structured attention networks", doi="10.48550/arxiv.1709.04579",
               cites=500, found_by=["snowball"])
same_doi_a = _p("Copy A of One Study", doi="10.1000/xyz", cites=10)
same_doi_b = _p("Copy B of One Study", doi="10.1000/xyz", cites=90,
                authors=("Other Person",))
lookalike = _p("Structured attention networks", doi="10.9999/different",
               authors=("Someone Else",), cites=1)  # same title, NO shared author
lone = _p("A Completely Unrelated Paper", doi="10.1000/solo", cites=3)

papers = [preprint, published, same_doi_a, same_doi_b, lookalike, lone]
groups = duplicate_groups(papers)
flat = [m["title"] for g in groups for m in g["members"]]

check("exact-doi pair groups", {"Copy A of One Study", "Copy B of One Study"} <= set(flat))
g_doi = next(g for g in groups if "doi" in g["reasons"])
check("doi reason reported", "doi" in g_doi["reasons"], str(g_doi["reasons"]))
version_pair = next(
    (g for g in groups
     if "10.48550/arxiv.1709.04579" in {m["doi"] for m in g["members"]}), None)
check("preprint+published version pair groups (arxiv signal)",
      version_pair is not None
      and len(version_pair["members"]) == 2
      and "arxiv" in version_pair["reasons"],
      str(version_pair and version_pair["reasons"]))
check("same title without shared author does NOT join the pair",
      version_pair is not None
      and all(m.get("doi") != "10.9999/different" for m in version_pair["members"]))
check("lone paper not in any group",
      not any("A Completely Unrelated Paper" == m["title"] for g in groups for m in g["members"]))

# ── dedup_pool ────────────────────────────────────────────────────────────────

kept, removed = dedup_pool(papers)
check("removed count = collapsed records", removed == 2, str(removed))
check("pool keeps first-occurrence order and shrinks to 4",
      len(kept) == 4 and kept[0].doi == "10.48550/arxiv.1709.04579",
      f"{len(kept)} kept, kept0 doi={kept[0].doi}")
survivor = kept[0]
check("survivor carries the DOI", survivor.doi == "10.48550/arxiv.1709.04579")
check("survivor carries the preprint pdf_url", survivor.pdf_url == "https://arxiv.org/pdf/1709.04579")
check("survivor unions found_by", set(survivor.found_by) == {"agent", "snowball"})
check("survivor takes max citations", survivor.citation_count == 500)
kept_doi = [p for p in kept if p.title in ("Copy A of One Study", "Copy B of One Study")]
check("doi pair collapses to one, max citations kept",
      len(kept_doi) == 1 and kept_doi[0].citation_count == 90)

# ── reading notes (temp home) ─────────────────────────────────────────────────

with tempfile.TemporaryDirectory() as tmp:
    litdb = Path(tmp) / "litdb"
    settings.litdb_dir = str(litdb)
    from citens.collect import append_pool

    append_pool("note-topic", [_p("A Judged Paper", doi="10.1000/j1", cites=7)])

    try:
        add_note("note-topic", verdict="core", note="x")
        check("add_note without doi/title raises", False)
    except ValueError:
        check("add_note without doi/title raises", True)
    try:
        add_note("note-topic", doi="10.1000/j1", verdict="great", note="x")
        check("bad verdict rejected", False)
    except ValueError:
        check("bad verdict rejected", True)

    rec = add_note("note-topic", doi="10.1000/j1", verdict="core",
                   note="正是要找的引文扩展基线")
    check("note enriched from pool (in_pool, title)",
          rec["in_pool"] and rec["title"] == "A Judged Paper", str(rec))
    rec2 = add_note("note-topic", title="Some Fetched-only Paper",
                    verdict="off", note="方法不合")
    check("fetch-only paper note accepted", rec2["in_pool"] is False and rec2["verdict"] == "off")
    check("notes file lives in data/notes/",
          notes_path("note-topic") == litdb.parent / "notes" / "note-topic.jsonl",
          str(notes_path("note-topic")))

    all_notes = read_notes("note-topic")
    check("read_notes returns both", len(all_notes) == 2)
    core = read_notes("note-topic", verdict="core")
    check("verdict filter works", len(core) == 1 and core[0]["doi"] == "10.1000/j1")

settings.litdb_dir = "data/litdb"  # restore the default

# ── export formats ────────────────────────────────────────────────────────────

table = CitationTable([
    _p("Attention & Gravity in Transformers", doi="10.1000/att",
       url="https://arxiv.org/abs/2401.00001", cites=99),
    _p("A Proceedings Paper", doi="10.1000/proc", source="ACL", cites=5,
       venue="Proceedings of the 61st Annual Meeting of the ACL"),
])

csl = json.loads(table.to_csl_json())
check("csl-json parses, two items", len(csl) == 2)
first = csl[0]
check("csl-json author family/given split",
      first["author"] == [{"family": "Zhao", "given": "Zheng"},
                          {"family": "Fan", "given": "Wei"}], str(first["author"]))
check("csl-json doi/url/year carried",
      first["DOI"] == "10.1000/att" and first["URL"].startswith("https://arxiv.org")
      and first["issued"] == {"date-parts": [[2023]]})
check("csl-json escaping survives round-trip",
      first["title"] == "Attention & Gravity in Transformers")

root = ET.fromstring(table.to_endnote_xml())
records = root.findall("./records/record")
check("endnote xml well-formed, two records", len(records) == 2)
ref_types = [r.find("ref-type").text for r in records]
check("journal vs proceedings ref-type", ref_types == ["17", "3"], str(ref_types))
dois = [r.find("electronic-resource-num/style").text for r in records]
check("endnote dois present", dois == ["10.1000/att", "10.1000/proc"])
amp = records[0].find("titles/title/style").text
check("endnote escaping (& as text)", amp == "Attention & Gravity in Transformers")
check("endnote has no bare <authors> outside contributors",
      all(r.find("authors") is None for r in records))

# ── expand --from-notes seed collection (driver, network legs patched) ──────

import importlib.util  # noqa: E402
import types  # noqa: E402

spec2 = importlib.util.spec_from_file_location(
    "ctools", ROOT / "drivers" / "citlens_tools.py")
ctools = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(ctools)
from citens import library as lib_mod  # noqa: E402
from citens.search import expand as expand_mod  # noqa: E402

captured: dict = {}


async def fake_expand(seeds, existing, **kw):
    captured["seeds"] = list(seeds)
    return {"anchors": [], "unresolved": [], "papers": [],
            "counts": {"seeds": len(seeds)}}


expand_mod.expand_from_seeds = fake_expand
lib_mod.read_notes = lambda topic, verdict=None, **kw: [
    {"doi": "10.1000/j1", "title": "A Judged Paper", "verdict": "core"},
    {"doi": None, "title": "Title Only Paper", "verdict": "core"},
]
args = types.SimpleNamespace(topic="t", seeds=["10.9/manual"], from_notes="core",
                             directions="recs", limit_per_paper=5, top=10,
                             no_write=True)
out = ctools.cmd_expand(args)
check("from-notes seeds merged with manual seeds (deduped, order kept)",
      captured["seeds"] == ["10.9/manual", "10.1000/j1", "Title Only Paper"],
      str(captured["seeds"]))
check("cmd_expand reports seeds_from_notes", out.get("seeds_from_notes") == 2,
      str(out.get("seeds_from_notes")))

# ── summary ──────────────────────────────────────────────────────────────────

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
