"""Offline tests for citens/search/policy.py — the policy corpus family.

No network: the Crossref prefix routes and the OpenAlex enrichment views are
served by httpx.MockTransport.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from citens.models import Paper

spec = importlib.util.spec_from_file_location(
    "policy_mod", ROOT / "citens" / "search" / "policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} - {name}" + (f" ({detail})" if detail and not cond else ""))


# ── classify_doc_type: DOI prefixes, containers, venue heuristics ────────────

cases = [
    # (paper, expected (doc_type, policy_org))
    (Paper(title="x", doi="10.3386/w33190"), ("working_paper", "NBER")),
    (Paper(title="x", doi="10.17016/2380-7172.2405", venue="FEDS Notes"),
     ("policy_note", "Federal Reserve Board")),
    (Paper(title="x", doi="10.17016/2380-7172.9999", venue="IFDP Notes"),
     ("policy_note", "Federal Reserve Board")),
    (Paper(title="x", doi="10.17016/feds.2016.011",
           venue="Finance and Economics Discussion Series"),
     ("working_paper", "Federal Reserve Board")),
    (Paper(title="x", doi="10.17016/feds.2001.56",
           venue="Finanace and Economics Discussion Series"),  # real deposited typo
     ("working_paper", "Federal Reserve Board")),
    (Paper(title="x", doi="10.17016/x.1", venue="Federal Reserve Bulletin"),
     ("report", "Federal Reserve Board")),
    (Paper(title="x", doi="10.5089/9798400221123.001", venue="IMF Working Papers"),
     ("working_paper", "IMF")),
    (Paper(title="x", doi="10.5089/0891274", venue="World Economic Outlook"),
     ("report", "IMF")),
    (Paper(title="x", doi="10.48550/arxiv.2401.12345"), ("preprint", "")),
    (Paper(title="x", url="https://arxiv.org/abs/2401.12345"), ("preprint", "")),
    (Paper(title="x", venue="SSRN Electronic Journal"), ("working_paper", "")),
    (Paper(title="x", venue="American Economic Review"), ("journal", "")),
    (Paper(title="x"), ("", "")),
]
print("== classify_doc_type ==")
for p, want in cases:
    got = policy.classify_doc_type(p)
    check(f"{(p.doi or p.venue or 'bare')[:36]} -> {want[0] or 'untagged'}",
          got == want, f"got {got}")

# ── stamp_doc_types: fills blanks, never overwrites ──────────────────────────

print("\n== stamp_doc_types ==")
batch = [
    Paper(title="a", doi="10.3386/w1"),
    Paper(title="b", venue="Quarterly Journal of Economics"),
    Paper(title="c", doi="10.48550/arxiv.2401.1"),
    Paper(title="preset", venue="FEDS Notes", doi="10.17016/2380-7172.1",
          doc_type="policy_note", policy_org="Federal Reserve Board"),
]
policy.stamp_doc_types(batch)
check("NBER record stamped working_paper/NBER",
      (batch[0].doc_type, batch[0].policy_org) == ("working_paper", "NBER"))
check("journal venue stamped journal", batch[1].doc_type == "journal")
check("arXiv DOI stamped preprint", batch[2].doc_type == "preprint")
check("existing tags preserved",
      (batch[3].doc_type, batch[3].policy_org) == ("policy_note", "Federal Reserve Board"))

# ── Crossref fixtures ────────────────────────────────────────────────────────

NBER_ITEM = {
    "DOI": "10.3386/w33190",
    "title": ["Sticky Inflation: Monetary Policy when Debt Drags Inflation Expectations"],
    "author": [{"family": "Bigio", "given": "Saroj"}, {"family": "Caramp", "given": "Nicolas"}],
    "issued": {"date-parts": [[2024, 5]]},
    "type": "report",
    "is-referenced-by-count": 12,
}
FEDS_NOTE_ITEM = {
    "DOI": "10.17016/2380-7172.2405",
    "title": ["Federal Funds Rate Control with Voluntary Reserve Targets"],
    "container-title": ["FEDS Notes"],
    "issued": {"date-parts": [[2024]]},
    "type": "journal-article",
    "is-referenced-by-count": 3,
}
FEDS_WP_ITEM = {
    "DOI": "10.17016/feds.2016.011",
    "title": ["Measuring the Natural Rate of Interest Redux"],
    "container-title": ["Finance and Economics Discussion Series"],
    "issued": {"date-parts": [[2016]]},
    "type": "journal-article",
    "is-referenced-by-count": 300,
}
OA_VIEW = {
    "abstract_inverted_index": {"natural": [0], "rate": [1], "of": [2], "interest": [3]},
    "best_oa_location": {"pdf_url": "https://www.nber.org/system/files/working_papers/w33190/w33190.pdf"},
}
_control = {"fed_status": 200}
SEEN: list[tuple[str, str]] = []


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    SEEN.append((url, str(request.url.params.get("query", ""))))
    if "api.openalex.org/works/doi:" in url:
        return httpx.Response(200, json=OA_VIEW)
    if "/prefixes/10.3386/works" in url:
        return httpx.Response(200, json={"message": {"items": [NBER_ITEM]}})
    if "/prefixes/10.17016/works" in url:
        if _control["fed_status"] != 200:
            return httpx.Response(_control["fed_status"], json={})
        return httpx.Response(
            200, json={"message": {"items": [FEDS_NOTE_ITEM, FEDS_WP_ITEM]}})
    if "/prefixes/10.5089/works" in url:
        return httpx.Response(200, json={"message": {"items": []}})
    return httpx.Response(404, json={})


# ── PolicySearchSource.search: parsing, health buckets, provenance ──────────

print("\n== PolicySearchSource.search ==")
Q = "natural rate of interest"


async def _run(constraints=None):
    src = policy.PolicySearchSource(transport=httpx.MockTransport(handler))
    if constraints is not None:
        src.set_constraints(constraints)
    return src, await src.search([Q], 10)


src, papers = asyncio.run(_run())
by_org = {}
for p in papers:
    by_org.setdefault(p.policy_org, []).append(p)
check("three papers from two orgs (IMF cell empty)", len(papers) == 3, str(len(papers)))
nber = by_org.get("NBER", [None])[0]
check("NBER venue synthesized from the series",
      nber.venue == "NBER Working Papers", str(nber.venue))
check("NBER landing url synthesized from the DOI",
      nber.url == "https://www.nber.org/papers/w33190", str(nber.url))
check("NBER tagged working_paper/NBER",
      (nber.doc_type, nber.policy_org) == ("working_paper", "NBER"))
check("NBER source names the family and org",
      nber.source == "policy (NBER)", str(nber.source))
check("NBER abstract enriched from OpenAlex (free view)",
      nber.abstract == "natural rate of interest", str(nber.abstract[:40]))
check("NBER pdf_url carried over from OpenAlex",
      nber.pdf_url and nber.pdf_url.endswith("w33190.pdf"))
check("NBER authors parsed family-first",
      nber.authors[:2] == ["Saroj Bigio", "Nicolas Caramp"], str(nber.authors))
fed_note = next(p for p in by_org.get("Federal Reserve Board", [])
                if p.doi.endswith(".2405"))
fed_wp = next(p for p in by_org.get("Federal Reserve Board", [])
              if p.doi.startswith("10.17016/feds"))
check("FEDS Note typed policy_note (container rule)", fed_note.doc_type == "policy_note")
check("FEDS working paper typed working_paper", fed_wp.doc_type == "working_paper")
check("matched_queries record the policy query",
      all(Q in p.matched_queries for p in papers))
check("health buckets: NBER ok, Fed ok, IMF empty",
      src.health == {"NBER": [1, 0, 0], "Federal Reserve Board": [1, 0, 0],
                     "IMF": [0, 1, 0]}, str(src.health))
check("query_stats count responding orgs only",
      src.query_stats == {Q: 3}, str(src.query_stats))
crossref_qs = [u for u, _ in SEEN if "api.crossref.org" in u]
check("one prefix call per org per query", len(crossref_qs) == 3, str(len(crossref_qs)))

# year window rides native Crossref filters
SEEN.clear()
src2, _ = asyncio.run(_run(types.SimpleNamespace(year_from=2022, year_to=None)))
filtered = [u for u, _ in SEEN if "api.crossref.org" in u]
check("year_from compiled into from-pub-date",
      all("from-pub-date" in u and "2022-01-01" in u for u in filtered), str(filtered[:1]))

# a failing org is failed, never a fake zero-hit
SEEN.clear()
_control["fed_status"] = 500
src3, papers3 = asyncio.run(_run())
_control["fed_status"] = 200
check("500 org buckets failed, not empty",
      src3.health.get("Federal Reserve Board") == [0, 0, 1], str(src3.health))
check("other orgs still return their papers",
      any(p.policy_org == "NBER" for p in papers3))

# ── enrich_abstracts: non-fatal, fills what it can ───────────────────────────

print("\n== enrich_abstracts ==")


def _oa_404(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404, json={})


bare = [Paper(title="not indexed", doi="10.3386/w9", citation_count=5),
        Paper(title="has one", doi="10.3386/w8", abstract="already", citation_count=5)]
filled = asyncio.run(policy.enrich_abstracts(bare, transport=httpx.MockTransport(_oa_404)))
check("unindexed records pass through untouched (0 enriched)", filled == 0)
check("no crash, abstract stays empty", bare[0].abstract == "")

# ── driver wiring: the family list carries policy ────────────────────────────

print("\n== driver wiring ==")
rspec = importlib.util.spec_from_file_location(
    "recall_mod", ROOT / "drivers" / "citlens_recall.py")
recall = importlib.util.module_from_spec(rspec)
rspec.loader.exec_module(recall)
check("ALL_FAMILIES includes policy",
      recall.ALL_FAMILIES[-1] == "policy" and len(recall.ALL_FAMILIES) == 8)
check("policy seats reserved through the target cut",
      recall.POLICY_SEATS == 8)
check("policy family default-on (CLI default = all families)",
      recall.build_args(["--topic", "x"]).families == ",".join(recall.ALL_FAMILIES))
check("--policy-queries accepted",
      recall.build_args([
          "--topic", "x", "--policy-queries", "natural rate of interest",
      ]).policy_queries == ["natural rate of interest"])

print(f"\n{'ALL PASS' if not FAIL else 'FAILURES: ' + str(FAIL)} ({len(PASS)} checks)")
sys.exit(1 if FAIL else 0)
