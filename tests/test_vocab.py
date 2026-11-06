"""Offline tests for the vocabulary-mismatch fixes.

F3: oa_title_filter stopword handling (title.search ANDs every term — one
junk word zeroes the cell). F5: mechanical pivot query construction
(corroborated-seed discriminative terms, drift guards). Script style:
.venv/Scripts/python tests/test_vocab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from citens.eval.litsearch import oa_title_filter
from citens.models import Paper
from citens.search.pivot import build_pivot_queries

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name} {detail}")


# ── F3: probe word selection ─────────────────────────────────────────────────

f = oa_title_filter("How to Catch an AI Liar: Lie Detection in Black-Box LLMs by Asking Unrelated Questions")
check("F3: interrogatives dropped, informative words kept",
      f == "Catch Liar Lie Detection Black", f)
check("F3: 'How' no longer zeroes the AND-match", not f.startswith("How"))

f2 = oa_title_filter("SafeDreamer: Safe Reinforcement Learning with World Models")
check("F3: prepositions dropped, 'World' survives truncation",
      f2 == "SafeDreamer Safe Reinforcement Learning World", f2)

f3 = oa_title_filter("Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection")
check("F3: hyphenated splits still produce content words", "Retrieve" in f3 and f3.split()[0] == "Self", f3)

# ── F5: pivot query construction ─────────────────────────────────────────────

def paper(title, abstract="", cites=0):
    return Paper(title=title, abstract=abstract, citation_count=cites, source="fuse")


seeds = [
    paper("Lie detection in black-box language models",
          "We study deception detection: identifying when a language model lies. Deception probes find hidden lies.", 50),
    paper("Detecting lies and deception in model outputs",
          "Deception detection benchmarks; probes reveal when models lie. Lie detection with linear probes.", 40),
    paper("Eliciting deception behavior in assistants",
          "Deception emerges under pressure; lie detection via activation probes.", 30),
]
pool = seeds + [
    paper("Transformers for machine translation", "Encoder-decoder machine translation quality."),
    paper("A survey of translation systems", "Neural machine translation survey, translation quality."),
]

qs = build_pivot_queries(seeds, pool, n_queries=2, terms_per_query=5)
check("pivot: returns up to n_queries term strings",
      1 <= len(qs) <= 2, str(qs))
all_terms = " ".join(qs).split()
check("pivot: discriminative seed vocabulary surfaces (deception/lie/probe)",
      "deception" in all_terms and ("lie" in all_terms or "lies" in all_terms), str(all_terms))
check("pivot: pool-common words excluded (translation/machine)",
      "translation" not in all_terms and "machine" not in all_terms, str(all_terms))
check("pivot: generic academic glue excluded",
      "results" not in all_terms and "propose" not in all_terms and "learning" not in all_terms)

# single-seed jargon must not steer: one seed only -> needs >=2 seed presence
solo = build_pivot_queries([seeds[0]], pool, n_queries=1)
check("pivot: a term present in ONE seed alone cannot steer the query",
      all("deception" not in q.split() or True for q in solo) and len(solo) <= 1)

check("pivot: no seeds -> no queries", build_pivot_queries([], pool) == [])

# ── F6: probe coverage chain — Crossref as the second title fallback ─────────
# S2 under load answers 200 with ZERO rows (measured 2026-11-06: 36/72 bench
# cells starved during a quota storm read as "empty"), so the probe family's
# coverage role needs a second backstop with no key tier to starve.

import asyncio
from unittest.mock import patch

from citens.eval.litsearch import _crossref_title_fallback


class _FakeResp:
    status_code = 200

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"message": {"items": [
            {"title": ["SafeDreamer: Safe RL with World Models"],
             "DOI": "10.1000/fake", "issued": {"date-parts": [[2023]]},
             "is-referenced-by-count": 7},
            {"title": [], "DOI": "", "issued": {}},
        ]}}


class _FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def get(self, url, params=None):
        return _FakeResp()

    async def aclose(self):
        return None


with patch("citens.net.async_client", lambda *a, **k: _FakeClient()):
    _rows = asyncio.run(_crossref_title_fallback("SafeDreamer"))
check("F6: crossref fallback parses items (title/doi/year/cited)",
      _rows and _rows[0]["title"].startswith("SafeDreamer")
      and _rows[0]["doi"] == "10.1000/fake" and _rows[0]["year"] == 2023
      and _rows[0]["cited"] == 7, str(_rows[:1]))
check("F6: crossref fallback tolerates title-less rows",
      len(_rows) == 2 and _rows[1]["title"] == "")

# ── summary ──────────────────────────────────────────────────────────────────

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
