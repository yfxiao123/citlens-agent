"""Offline tests for the optional decision layer (`screen --decide`).

Script style like the other suites: run with the repo venv python.
Everything rides on httpx.MockTransport — no network, no key needed.

    .venv/Scripts/python tests/test_decide.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from citens.config import settings  # noqa: E402
from citens.decide import (  # noqa: E402
    Decision,
    apply_selective,
    band_distribution,
    build_messages,
    decide_papers,
)
from citens.models import Paper  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    if cond:
        PASS.append(name)
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name}")


settings.decide_min_interval_s = 0.0  # shared limiter must not stall the tests

# ── band_distribution: the logit readout ─────────────────────────────────────

def _top(token: str, logprob: float) -> dict:
    return {"token": token, "logprob": logprob}

# realistic: first token "[", second token carries the option distribution
two_token = [
    {"top_logprobs": [_top("[", 0.0), _top("Based", -9.0), _top("The", -9.5)]},
    {"top_logprobs": [_top("1]", -0.35), _top("2]", -1.8), _top("3]", -4.0),
                      _top("Based", -9.0), _top("I", -9.5)]},
]
probs, mass = band_distribution(two_token)
check("readout: two-token case matches option tokens",
      abs(mass - (pow(2.718281828, -0.35) + pow(2.718281828, -1.8) + pow(2.718281828, -4.0)) / 1.0) < 0.2
      and max(mass, 0) <= 1.0)
check("readout: core has the largest share in the two-token case", probs["core"] > probs["uncertain"] > probs["likely_off"])
check("readout: probs are normalized", abs(sum(probs.values()) - 1.0) < 1e-6)

one_token = [{"top_logprobs": [_top("[2]", -0.1), _top("[1]", -2.5), _top("[3]", -5.0)]}]
probs1, mass1 = band_distribution(one_token)
check("readout: single '[2]' token wins", probs1["uncertain"] > 0.8 and mass1 > 0.9)

probs_g, mass_g = band_distribution([{"top_logprobs": [_top("Based", -1.0), _top("I", -1.2)]}])
check("readout: off-script tokens match nothing (mass 0)", mass_g == 0.0 and probs_g["core"] == 0.0)

probs_n, mass_n = band_distribution(None)
check("readout: missing logprobs degrade to mass 0", mass_n == 0.0)

# ── selective prediction policy ──────────────────────────────────────────────

dec_core = Decision("core", {"core": 0.9, "uncertain": 0.08, "likely_off": 0.02}, 0.9, 0.97)
dec_agree = Decision("likely_off", {"core": 0.05, "uncertain": 0.3, "likely_off": 0.65}, 0.65, 0.95)
dec_amb = Decision("core", {"core": 0.5, "uncertain": 0.45, "likely_off": 0.05}, 0.5, 0.95)
dec_off = Decision("core", {"core": 0.8, "uncertain": 0.1, "likely_off": 0.1}, 0.8, 0.1)  # off-script mass

rows = [
    {"key": "a", "band": "likely_off"},   # auto, flips mechanical off -> core
    {"key": "b", "band": "likely_off"},   # agree at 0.65 -> auto likely_off
    {"key": "c", "band": "core"},         # disagree at 0.65 -> escalated uncertain
    {"key": "d", "band": "core"},         # low confidence -> escalated uncertain
    {"key": "e", "band": "uncertain"},    # no decision -> mechanical fallback
    {"key": "f", "band": "core"},         # unreliable mass -> mechanical fallback
]
rows, summary = apply_selective(
    rows,
    {"a": dec_core, "b": dec_agree, "c": Decision("uncertain", {"core": 0.3, "uncertain": 0.4, "likely_off": 0.3}, 0.65, 0.95),
     "d": dec_amb, "f": dec_off},
)
by = {r["key"]: r for r in rows}
check("policy: high confidence auto-bands and keeps provenance",
      by["a"]["band"] == "core" and by["a"]["decided_by"] == "decision_model"
      and by["a"]["mechanical_band"] == "likely_off" and by["a"]["agrees_mechanical"] is False)
check("policy: agreement auto-bands below the auto cutoff",
      by["b"]["band"] == "likely_off" and by["b"]["decided_by"] == "decision_model"
      and by["b"]["agrees_mechanical"] is True)
check("policy: mid-confidence disagreement escalates to uncertain",
      by["c"]["band"] == "uncertain" and by["c"]["decided_by"] == "escalated:low_confidence")
check("policy: low confidence escalates even when bands agree",
      by["d"]["band"] == "uncertain" and by["d"]["decided_by"] == "escalated:low_confidence")
check("policy: missing decision keeps the mechanical band",
      by["e"]["band"] == "uncertain" and by["e"]["decided_by"] == "mechanical_fallback")
check("policy: off-script readout (low mass) is escalated, never guessed",
      by["f"]["band"] == "core" and by["f"]["decided_by"] == "mechanical_fallback")
check("policy: summary counts add up",
      summary["auto"] == 2 and summary["escalated"] == 2 and summary["fallback"] == 2
      and summary["auto_agrees_mechanical"] == 1
      and summary["band_flips"].get("likely_off->core") == 1)
check("policy: auto_rate/flip_rate are rates of the whole batch",
      summary["auto_rate"] == round(2 / 6, 3) and summary["flip_rate"] == round(3 / 6, 3)
      and summary["band_flips"].get("core->uncertain") == 2)

# ── build_messages ───────────────────────────────────────────────────────────

msgs = build_messages("adaptive retrieval", "Some Title", "Some abstract about retrieval.")
joined = " ".join(m["content"] for m in msgs)
check("messages carry topic/title/abstract and the band rubric",
      "adaptive retrieval" in joined and "Some Title" in joined
      and "Some abstract" in joined and "[1]" in joined and "[3]" in joined)
long = build_messages("t", "T", "x" * 3000)
check("messages truncate a long abstract", len(long[1]["content"]) < 3000)

# ── decide_papers end-to-end on MockTransport ────────────────────────────────

settings.llm_api_base = "https://mock.local/v1"
settings.llm_api_key = "test-key"
settings.llm_model = "test-model"


def _handler(logprob_map: dict[str, float], answer: str = "[1]"):
    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        assert auth == "Bearer test-key", "auth header must carry the key"
        return httpx.Response(200, json={
            "choices": [{
                "message": {"content": answer},
                "logprobs": {"content": [
                    {"top_logprobs": [_top("[", -0.01)]},
                    {"top_logprobs": [_top(t, lp) for t, lp in logprob_map.items()]},
                ]},
            }],
        }, request=request)
    return handler


papers = [
    Paper(doi="10.1/aa", title="Adaptive retrieval when to retrieve", abstract="Uncertainty triggers retrieval."),
    Paper(doi="10.1/bb", title="Pneumonia triage at hospital", abstract="Clinical triage of febrile children."),
]
transport = httpx.MockTransport(_handler({"1]": -0.3, "2]": -2.0, "3]": -5.0, "The": -9.0}))
decisions, stats = asyncio.run(decide_papers(papers, "when to retrieve", transport=transport))
key = papers[0].doi
check("e2e: decision keyed by doi and read out of the mock",
      key in decisions and decisions[key].band == "core" and decisions[key].confidence > 0.6)
check("e2e: stats count both papers as decided", stats.decided == 2 and stats.requested == 2 and stats.failed == 0)
check("e2e: endpoint/model recorded without the key",
      "mock.local" in stats.endpoint and stats.model == "test-model"
      and "test-key" not in json.dumps(stats.__dict__))


def _failing(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"error": "boom"}, request=request)


settings.http_max_attempts = 1  # no retry storm in tests
try:
    transport = httpx.MockTransport(_failing)
    decisions, stats = asyncio.run(decide_papers(papers, "t", transport=transport))
    check("e2e: 500s degrade honestly (no decisions, failure noted)",
          decisions == {} and stats.failed == 2 and "500" in stats.last_error
          and any("保留机械分带" in n for n in stats.notes))
finally:
    settings.http_max_attempts = 4

settings.llm_api_base = ""
settings.llm_api_key = ""
settings.llm_model = ""
decisions, stats = asyncio.run(decide_papers(papers, "t", transport=transport))
check("unconfigured endpoint: zero requests, mechanical bands stand",
      decisions == {} and stats.requested == 0 and any("未配置" in n for n in stats.notes))

# ── summary ──────────────────────────────────────────────────────────────────

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
