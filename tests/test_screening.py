#!/usr/bin/env python
"""test_screening.py — offline unit tests for the relevance-triage half.

Covers the deterministic channels of `screen` (BM25 lexical, consensus
renormalization, banding, screening.jsonl artifact) and the snowball
admission-order fix (BM25 + IDF + CJK terms) — all offline, no model
download: the semantic channel is exercised only through its OFF path.

Run:  python tests/test_screening.py        (standalone, no pytest needed)
      python -m pytest tests/test_screening.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from citens.models import Paper
from citens.screening import bm25_scores, screen_papers
from citens.search.snowball import _query_terms, _rank_by_query_overlap

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))


def _p(title: str, abstract: str = "", **kw) -> Paper:
    return Paper(title=title, abstract=abstract, **kw)


# ── lexical channel ──────────────────────────────────────────────────────────


def test_bm25_scores() -> None:
    print("\n== BM25 lexical channel ==")
    texts = [
        "Order flow imbalance and the limit order book queue dynamics",  # on-topic
        "A general method for the analysis of empirical studies",        # generic words only
        "Deep learning for image classification with transformers",      # off-topic
    ]
    q = "order flow imbalance limit order book"
    s = bm25_scores(texts, q)
    check("scores have the same length", len(s) == 3)
    check("exact-terminology record scores highest", s[0] > s[1] and s[0] > s[2],
          str(s))
    # IDF: a term present in EVERY doc must not separate them
    s2 = bm25_scores(["alpha beta common", "gamma delta common", "common common"], "common")
    check("a term common to all docs adds ~nothing (IDF≈0)",
          max(s2) - min(s2) < 1.0, str(s2))


# ── triage + bands + renormalization ─────────────────────────────────────────


def test_screen_bands_offline() -> None:
    print("\n== screen triage (semantic off, offline) ==")
    papers = [
        _p("Order flow imbalance estimation from limit order books",
           "We estimate order flow imbalance signals from the limit order book.",
           found_by=["agent", "raw", "snowball"], citation_count=40),
        _p("Deep residual networks for image recognition",
           "We introduce residual learning for image classification.",
           found_by=["web"], citation_count=5000),
        _p("A survey of limit order book models",  # review, mid overlap
           "Survey of market microstructure and limit order book modeling.",
           found_by=["agent", "survey"], is_review=True),
    ]
    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "screening.jsonl"
        res = screen_papers(
            papers, ["limit order book order flow imbalance"],
            model="",  # semantic channel OFF -> deterministic offline run
            out_path=out_path, limit=10,
        )
        check("screening.jsonl written with all records + bands",
              res["screening_path"] is not None and out_path.is_file())
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        check("artifact holds every paper row", len(payload["papers"]) == 3
              and {"band", "score", "channels"} <= set(payload["papers"][0]))
    rows = {r["title"]: r for r in res["papers"]}
    check("result carries the three bands",
          set(res["bands"]) == {"core", "uncertain", "likely_off"})
    check("bands count every record", sum(res["bands"].values()) == 3)
    check("on-topic record outranks the off-topic famous one",
          rows["Order flow imbalance estimation from limit order books"]["score"]
          > rows["Deep residual networks for image recognition"]["score"])
    check("semantic channel reported off", res["channels"]["semantic"] == "off")
    check("consensus channel fired for records with found_by",
          "consensus" in rows["Order flow imbalance estimation from limit order books"]["channels"]
          and rows["Order flow imbalance estimation from limit order books"]["channels"]["consensus"] == 0.75)
    # renormalization: a record WITHOUT found_by must lose the channel, not
    # score 0 on it (absence of metadata must not punish — ranking.py rule)
    papers_no_fam = [
        _p("Order flow imbalance estimation from limit order books",
           "We estimate order flow imbalance signals from the limit order book."),
        _p("Deep residual networks for image recognition",
           "We introduce residual learning for image classification.",
           found_by=["web"]),
    ]
    res2 = screen_papers(papers_no_fam, ["limit order book order flow imbalance"],
                         model="", limit=10)
    r0, r1 = res2["papers"]
    check("legacy record without found_by drops the channel, not the score",
          "consensus" not in r0["channels"] and "consensus" in r1["channels"])
    check("note states triage-not-judgment and uncalibrated thresholds",
          "PRISMA" in res["note"] and "阈值" in res["note"])


def test_screen_cjk_query() -> None:
    print("\n== screen with a Chinese query (CJK bigram tokenizer) ==")
    papers = [
        _p("限价订单簿中的订单流失衡与价格发现", "基于限价订单簿测度订单流失衡。", found_by=["agent"]),
        _p("Deep learning for image classification", "Residual networks.", found_by=[]),
    ]
    res = screen_papers(papers, ["限价订单簿 订单流失衡"], model="", limit=10)
    check("CJK query separates on-topic from off-topic",
          res["papers"][0]["score"] > res["papers"][1]["score"],
          str([r["score"] for r in res["papers"]]))


# ── snowball admission order ──────────────────────────────────────────────────


def test_snowball_query_terms() -> None:
    print("\n== snowball term extraction (CJK-aware) ==")
    terms = _query_terms(["order flow imbalance", "限价订单簿", "the of and"])
    check("latin terms of length >= 4 kept",
          "order" in terms and "flow" in terms and "imbalance" in terms)
    check("CJK bigrams extracted (previously ZERO)",
          any(t for t in terms if any("\u4e00" <= c <= "\u9fff" for c in t)))
    check("short latin stopwords dropped", "the" not in terms and "and" not in terms)
    check("None when no terms", _query_terms(None) is None and _query_terms([]) is None)


def test_snowball_ranking() -> None:
    print("\n== snowball admission order (BM25 + IDF) ==")
    niche = _p("OFI: order flow imbalance as a limit order book signal",
               "order flow imbalance predicts short-term price moves", citation_count=12)
    famous = _p("A general framework for the analysis of high-dimensional data",
                "a method for the analysis of large-scale empirical studies",
                citation_count=4000)
    off = _p("Polynomial-time algorithms for graph coloring heuristics",
             "coloring heuristics", citation_count=30)
    ranked = _rank_by_query_overlap(
        [famous, off, niche], _query_terms(["order flow imbalance limit order book"])
    )
    check("exact-match niche paper beats famous generic-methods paper",
          ranked[0] is niche, " -> ".join(p.title[:30] for p in ranked))
    # citations as tiebreaker: two equal-overlap papers, higher cited first
    a = _p("order flow imbalance study one", "order flow imbalance", citation_count=10)
    b = _p("order flow imbalance study two", "order flow imbalance", citation_count=99)
    ranked2 = _rank_by_query_overlap([a, b], _query_terms(["order flow imbalance"]))
    check("citation count breaks BM25 ties", ranked2[0] is b)
    check("empty input safe", _rank_by_query_overlap([], {"x"}) == [])


def main() -> int:
    test_bm25_scores()
    test_screen_bands_offline()
    test_screen_cjk_query()
    test_snowball_query_terms()
    test_snowball_ranking()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
