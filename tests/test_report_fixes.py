"""Regression checks for the 2026-11-06 third-party test report.

Every check maps to a named P1/P2 finding (see test-report/). These are the
"declared but not wired" and "silently degraded" failures that the existing
suites could not see because they tested functions, not the user-facing path.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} - {name}" + (f"  ({detail})" if detail and not cond else ""))


# ── P1-3 dedup: title-only duplicates (missing authors) ─────────────────────
print("== dedup: exact-title signal ==")
from citens.library import dedup_pool, duplicate_groups  # noqa: E402
from citens.models import Paper  # noqa: E402

title = "Retrieval Augmented Fine Tuning With Preference Optimization"
a = Paper(title=title, doi="10.1/acl", authors=[], year=2024)
b = Paper(title=title, doi="10.2/arxiv", authors=[], year=2024)
groups = duplicate_groups([a, b])
check("exact-title duplicates reported with EMPTY authors",
      len(groups) == 1 and groups[0]["reasons"] == ["title"], str(groups))
kept, removed = dedup_pool([a, b])
check("dedup_pool collapses the title-only pair", removed == 1 and len(kept) == 1)
short = [Paper(title="A Survey", authors=[]), Paper(title="A Survey", authors=[])]
check("short/generic titles still need a shared author",
      duplicate_groups(short) == [])


# ── P1-4 audit: is_review derivation ────────────────────────────────────────
print("\n== audit: review anchors ==")
from citens.models import looks_like_review, review_title_hint  # noqa: E402

check("survey title is an anchor even when is_review is false",
      looks_like_review(Paper(title="A Comprehensive Survey of DPO")))
check("CJK review title is an anchor",
      review_title_hint("大语言模型综述"))
check("ordinary paper is not an anchor",
      not looks_like_review(Paper(title="Deep Reinforcement Learning for Recsys")))
check("indexer flag still wins",
      looks_like_review(Paper(title="Anything", is_review=True)))


# ── P1-6 verify: fail-closed without verdicts ───────────────────────────────
print("\n== verify: fail-closed ==")
from citens.grounding.verify import verify_review  # noqa: E402

paper = Paper(
    title="Direct Preference Optimization for Search Ranking Systems",
    doi="10.1/verify",
    abstract="Direct preference optimization improves ranking quality on every benchmark.",
)
review = (
    "## Findings\n\n"
    "Direct preference optimization improves ranking quality [1].\n\n"
    "## References\n"
    "[1] Smith, J. Direct Preference Optimization for Search Ranking Systems. 2024.\n"
)
out = verify_review(review, [paper])
check("no verdicts + claims -> clean=false",
      out["clean"] is False and out["honesty"]["claims_without_verdict"] == 1,
      f"clean={out['clean']} missing={out['honesty']['claims_without_verdict']}")
verdicts = [{
    "claim": "Direct preference optimization improves ranking quality [1].",
    "verdict": "supported",
    "span": "Direct preference optimization improves ranking quality on every benchmark",
    "citations": [1],
}]
out = verify_review(review, [paper], verdicts=verdicts)
check("fully judged review -> clean=true",
      out["clean"] is True, str(out["checks"]["problems"])[:200])

# legacy .txt converted by the space-dropping converter must not pose as
# full text (it manufactured 14/37 span mismatches in the third-party run)
from citens.grounding.verify import ground_text  # noqa: E402
from citens.grounding.fulltext import slugify as _slug  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    broken = Path(td) / f"{_slug(paper.title)[:80]}.txt"
    broken.write_text(" ".join(["Whilelarge" + "x" * 35] * 300), encoding="utf-8")
    tq, is_full = ground_text(paper, Path(td))
check("run-together fulltext falls back to the abstract floor",
      is_full is False and tq == paper.abstract, f"is_full={is_full} len={len(tq)}")


# ── P1-5 / P2-3: CLI/MCP argument wiring ────────────────────────────────────
print("\n== MCP tool argument wiring ==")
import citlens_cli as m  # noqa: E402

captured: dict = {}


def _fake_start(cfg, kind, payload):
    captured["kind"] = kind
    captured["payload"] = payload
    return {"ok": True, "job_id": "j1", "state": "running"}


m.start_job = _fake_start
m.wait_job = lambda cfg, jid, wait: {"job_id": jid, "state": "running",
                                      "topic": captured["payload"].get("topic"),
                                      "log_path": ""}
m._search_view = lambda cfg, st: {"state": st.get("state")}
m.tool_search({}, {"topic": "t", "policy_queries": ["natural rate", "Fed funds"],
                   "queries": ["q"]})
check("search forwards policy_queries into the job payload",
      captured["payload"].get("policy_queries") == ["natural rate", "Fed funds"],
      str(captured["payload"]))

captured.clear()


def _fake_driver(cfg, kind, argv, timeout=0):
    captured["argv"] = argv
    return {"ok": True}


m._run_driver_json = _fake_driver
m.tool_verify({}, {"review": "r.md", "run_dir": "/tmp/run", "text_dir": "/tmp/txt"})
argv = captured.get("argv") or []
# path args are resolved against the CALLER's cwd (2.0 retest): on Windows
# "/tmp/run" is not absolute, so it arrives as its resolved form
check("verify passes hyphenated --run-dir/--text-dir",
      "--run-dir" in argv and "--text-dir" in argv
      and argv[argv.index("--run-dir") + 1] == str(Path("/tmp/run").resolve())
      and argv[argv.index("--text-dir") + 1] == str(Path("/tmp/txt").resolve()), str(argv))
check("verify never sends the snake_case flags argparse rejects",
      "--run_dir" not in argv and "--text_dir" not in argv, str(argv))

captured.clear()
m.tool_screen({}, {"topic": "t", "core": 0.5, "off": 0.25, "background": False})
argv = captured.get("argv") or []
check("screen CLI aliases --core/--off are honoured",
      argv[argv.index("--core") + 1] == "0.5"
      and argv[argv.index("--off") + 1] == "0.25", str(argv))

_name, _parsed = m._parse_cli_args(
    ["search", "--topic", "t", "--families", "agent,raw", "--queries", "a,b"])
check("CLI splits comma-separated enum lists (--families) but not queries",
      _parsed.get("families") == ["agent", "raw"]
      and _parsed.get("queries") == ["a,b"], str(_parsed))


# ── P1-7 fetch: scansci success without OA candidates ──────────────────────
print("\n== fetch: scansci last leg ==")
from citens import cache  # noqa: E402
from citens.config import settings  # noqa: E402
from citens.grounding import fulltext as ft  # noqa: E402

ft._FETCH_REPORTS.clear()
ft._FETCH_OUTCOMES.clear()
ft._local_pdf = lambda paper: None
ft._arxiv_pdf_url = lambda paper: None
ft._s2_pdf_url = lambda doi: []
ft._openalex_pdf_urls = lambda doi: []
ft._unpaywall_pdf_url = lambda doi: []
ft._core_pdf_url = lambda doi: None
ft._scansci_fetch = lambda paper: ("full text " * 80, "Sci-Hub 4k字", "Sci-Hub")
cache.get = lambda ns, key: None
cache.put = lambda ns, key, value, **kw: None
old_enabled = settings.scansci_enabled
settings.scansci_enabled = True
bare = Paper(title="A Paywalled Paper", doi="10.1016/0304-405X(76)90026-X")
text = ft.fetch_fulltext(bare)
check("scansci success with ZERO OA candidates returns text (no UnboundLocalError)",
      bool(text) and len(text) > 500)
check("the delivered leg is labelled scansci, not the last failed OA leg",
      ft.fetch_report(bare.id).startswith("scansci"), ft.fetch_report(bare.id))
check("outcomes carry the scansci outcome",
      any(o.startswith("scansci:") for o in ft.fetch_outcomes(bare.id)),
      str(ft.fetch_outcomes(bare.id)))
settings.scansci_enabled = old_enabled


# ── P1-2: PDF conversion preserves inter-word spaces ───────────────────────
print("\n== PDF -> text: PyMuPDF primary ==")
try:
    import pymupdf

    with tempfile.TemporaryDirectory() as td:
        pdf = Path(td) / "sample.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        sentence = (
            "While large-scale unsupervised language models are trained on huge corpora, "
            "the natural rate of interest remains unclear under fiscal dominance. "
        )
        for i in range(8):
            page.insert_text((72, 72 + i * 16), sentence)
        doc.save(str(pdf))
        doc.close()
        text = ft._convert_pdf_file(str(pdf)) or ""
    check("converted text keeps spaces between words",
          "While large-scale" in text and "Whilelarge" not in text)
    check("converted text is long enough to ground spans", len(text) > 500)
except ImportError:
    check("pymupdf available (core dependency)", False, "pymupdf not installed")

from citens.grounding.fulltext import text_quality_ok  # noqa: E402

check("CJK fulltext is not mistaken for a space-dropped conversion",
      text_quality_ok("这是一段中文论文正文，用于检验空格密度启发式。" * 200))
check("run-together Latin text IS rejected",
      not text_quality_ok("Whilelarge" + "x" * 35 + " " + "A" * 40 + " " * 0
                          + ("Thisarticleinvestigates " + "y" * 30 + " ") * 300))


# ── P2-5: provenance is not a venue; AI-generated flag ─────────────────────
print("\n== export venue + quality flag ==")
from citens.collect import flag_low_quality  # noqa: E402
from citens.grounding.citations import _bib_venue  # noqa: E402

check("snowball provenance never renders as a journal name",
      _bib_venue("snowball-backward", "") == "")
check("old provenance with an embedded DOI is rejected too",
      _bib_venue("snowball-backward(10.1016/j.jfineco.2004.06.001)", "") == "")
check("real venue still survives", _bib_venue("OpenAlex (Journal of Finance)", "")
      == "Journal of Finance")
# Crossref supplementary/attachment records are not papers
from citens.search.crossref import _is_component  # noqa: E402

check("Crossref 'Appendix' component is dropped",
      _is_component({"title": ["Appendix"], "DOI": "10.1007/978-3-658-04473-2_7"}))
check("Crossref supplemental record is dropped",
      _is_component({"title": ["Supplemental Information 2: Gap areas"],
                     "DOI": "10.7717/peerj-cs.936/supp-2"}))
check("Crossref media attachment DOI is dropped",
      _is_component({"title": ["Some Real Title"], "DOI": "10.1109/tg.2025.3564042/mm1"}))
check("a normal Crossref work survives",
      not _is_component({"title": ["Monetary Policy and the Natural Rate"],
                         "DOI": "10.1016/j.jfineco.2004.06.001"}))
fake = Paper(title="Comparison of DPO and RL for LLMs",
             abstract="Autonomous synthesis report. Tribunal consensus score 7.5/10.")
flag_low_quality([fake])
check("machine-synthesized self-description is flagged",
      fake.quality_flag == "ai_generated", fake.quality_flag)
real = Paper(title="Monetary Policy and the Natural Rate", abstract="We estimate ...")
flag_low_quality([real])
check("ordinary paper stays unflagged", real.quality_flag == "")


# ── P2-2 / P2-5: config strictness and blank topic ─────────────────────────
print("\n== config / pool guards ==")
bad = m.load_config(str(ROOT / "does-not-exist.json"))
check("an explicitly requested missing config is an ERROR",
      bool(bad.get("config_error")) and bad.get("config_explicit") is True,
      str(bad.get("config_error")))
with tempfile.TemporaryDirectory() as td:
    cfg = {"home": td}
    path, why = m._pool_path_for(cfg, run_dir=None, topic="   ")
    check("blank topic does not match an arbitrary pool",
          path is None and "slug" in why, why)


# ── P3: fetch --title accepts a near-verbatim title ────────────────────────
print("\n== fetch title matching ==")
from drivers.citlens_tools import _match  # noqa: E402

pool_paper = Paper(title="Direct Preference Optimization for Search Ranking Systems")
check("near-verbatim title resolves (punctuation/case insensitive)",
      _match([pool_paper], None,
             "Direct preference optimization for search-ranking systems!") is pool_paper)
check("a genuinely different title does not resolve",
      _match([pool_paper], None, "Quantum error correction with surface codes") is None)


# ── robustness: a null OpenAlex title must not kill the whole source ──────
print("\n== OpenAlex null title ==")
from citens.search.openalex import OpenAlexSearcher  # noqa: E402

_bad = OpenAlexSearcher.to_paper({"title": None, "id": "https://openalex.org/W1"})
check("null title becomes an empty string (callers filter it)",
      _bad.title == "", repr(_bad.title))
_good = OpenAlexSearcher.to_paper({"title": "A Real Paper", "type": "review"})
check("OpenAlex type=review maps to is_review", _good.is_review is True)


# ── P2-4: mine_stated_gaps counts real pool matches ────────────────────────
print("\n== gaps: matched_to_pool ==")
from citens.gapfinding import mine_stated_gaps  # noqa: E402
from citens.grounding.fulltext import slugify  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    inpool = Paper(title="Natural Rate Estimates With Monetary Shocks",
                   doi="10.1/a", abstract="")
    (d / f"{slugify(inpool.title)[:80]}.txt").write_text(
        "Limitations\nFuture work should study the natural rate under fiscal dominance "
        "with monthly data.\n", encoding="utf-8")
    (d / "not-in-pool.txt").write_text(
        "Limitations\nFuture research should examine survey expectations at daily "
        "frequency for robustness.\n", encoding="utf-8")
    mg = mine_stated_gaps(d, [inpool], limit=10)
    check("matched_to_pool counts only real pool records",
          mg["matched_to_pool"] == 1 and len(mg["hits"]) == 2,
          f"matched={mg['matched_to_pool']} hits={len(mg['hits'])}")


print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
