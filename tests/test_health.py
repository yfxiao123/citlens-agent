"""Offline tests for failure visibility: search_round health semantics, the
circuit breaker, litsearch's health buckets, the cache's empty-value guard
and the fulltext negative cache.

No network: fake sources are registered under test-only names; the arXiv
source is exercised with its sync worker monkeypatched.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import citens.search  # noqa: E402,F401 — registers the real sources
from citens import cache  # noqa: E402
from citens.config import settings  # noqa: E402
from citens.eval.litsearch import search_one_query  # noqa: E402
from citens.models import Paper  # noqa: E402
from citens.search import base  # noqa: E402
from citens.search.base import (  # noqa: E402
    REGISTRY,
    SearchSource,
    circuit_state,
    failure_reason,
    reset_circuits,
    search_round,
)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} - {name}" + (f" ({detail})" if detail and not cond else ""))


def _run(coro):
    return asyncio.run(coro)


def _paper(title: str, src: str = "test") -> Paper:
    return Paper(title=title, authors=["A Author"], year=2023, source=src)


def _http_error(status: int, attempts: int | None = None) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://api.test/x")
    resp = httpx.Response(status, request=req)
    if attempts is not None:
        resp.extensions["citens_attempts"] = attempts
    return httpx.HTTPStatusError(str(status), request=req, response=resp)


settings.source_circuit_failures = 3


# ── fake sources ──────────────────────────────────────────────────────────────


class OkSource(SearchSource):
    name = "Ok Display Name"

    async def search(self, kws, n):
        self.query_stats = {k: 1 for k in kws}
        return [_paper(f"hit for {k}") for k in kws]


class EmptySource(SearchSource):
    name = "Empty Display"

    async def search(self, kws, n):
        self.query_stats = {k: 0 for k in kws}
        return []


class Throttled(SearchSource):
    name = "Throttled Display"
    calls = 0

    async def search(self, kws, n):
        Throttled.calls += 1
        raise _http_error(429, attempts=4)


class Flaky(SearchSource):
    """fails twice, then succeeds — the breaker must NOT open."""
    name = "Flaky"
    calls = 0

    async def search(self, kws, n):
        Flaky.calls += 1
        if Flaky.calls <= 2:
            raise RuntimeError("blip")
        return [_paper("recovered")]


class Rejected(SearchSource):
    name = "Rejected"
    calls = 0

    async def search(self, kws, n):
        Rejected.calls += 1
        raise _http_error(401)


class PartialSource(SearchSource):
    name = "Partial"

    async def search(self, kws, n):
        results = []
        for k in kws:
            if k.startswith("bad"):
                results.append(RuntimeError("s2 500"))
            else:
                self.query_stats[k] = 1
                results.append([_paper(f"hit {k}")])
        return self._collect_cells(kws, results)


REGISTRY.update({
    "t_ok": OkSource, "t_empty": EmptySource, "t_throttled": Throttled,
    "t_flaky": Flaky, "t_auth": Rejected, "t_partial": PartialSource,
})
base._KEY_ENV["t_auth"] = "T_AUTH_KEY"

# ── health keyed by registry name, three plain states ─────────────────────────

reset_circuits()
papers, health, stats = _run(search_round(["q"], sources=["t_ok", "t_empty", "t_throttled"]))
check("health keyed by REGISTRY name, not display name",
      set(health) == {"t_ok", "t_empty", "t_throttled"}, str(health))
check("ok source reads ok", health["t_ok"] == "ok")
check("empty source reads empty", health["t_empty"] == "empty")
check("failed source reads failed with HTTP status and attempts",
      health["t_throttled"] == "failed: HTTP 429 after 4 attempts", health["t_throttled"])
check("papers come only from responding sources", len(papers) == 1)
check("query_stats sums responders only", stats == {"q": 1}, str(stats))

# ── partial: some queries failed ─────────────────────────────────────────────

reset_circuits()
papers, health, stats = _run(search_round(["good1", "bad1", "good2"], sources=["t_partial"]))
check("partial health names the ratio and the reason",
      health["t_partial"] == "partial: 1/3 queries failed (RuntimeError: s2 500)", health["t_partial"])
check("partial returns the successful cells", len(papers) == 2)
check("failed query is ABSENT from query_stats, not zero",
      "bad1" not in stats and stats == {"good1": 1, "good2": 1}, str(stats))

reset_circuits()
papers, health, _ = _run(search_round(["bad1", "bad2"], sources=["t_partial"]))
check("all queries failed -> source failed (last error re-raised)",
      health["t_partial"].startswith("failed: RuntimeError: s2 500"), health["t_partial"])

# ── _collect_cells contract directly ─────────────────────────────────────────

src = PartialSource()
out = src._collect_cells(["a", "b"], [[_paper("x")], ValueError("boom")])
check("_collect_cells keeps successes", len(out) == 1)
check("_collect_cells records failed query with reason",
      src.failed_queries == {"b": "ValueError: boom"}, str(src.failed_queries))
try:
    src._collect_cells(["a"], [ValueError("only")])
    raised = False
except ValueError:
    raised = True
check("_collect_cells raises when every query failed", raised)
out = src._collect_cells([], [])
check("_collect_cells with no keywords returns []", out == [] and src.failed_queries == {})

# ── circuit breaker: consecutive failures open, skip, success closes ──────────

reset_circuits()
Throttled.calls = 0
for i in range(settings.source_circuit_failures):
    _, health, _ = _run(search_round(["q"], sources=["t_throttled"]))
calls_before_open = Throttled.calls
_, health, _ = _run(search_round(["q"], sources=["t_throttled"]))
check("source called exactly threshold times before the circuit opens",
      calls_before_open == 3 and Throttled.calls == 3, f"{calls_before_open}/{Throttled.calls}")
check("open circuit reports why and the last reason",
      health["t_throttled"] == "failed: circuit open after 3 consecutive failures (last: HTTP 429 after 4 attempts)",
      health["t_throttled"])
state = circuit_state()
check("circuit_state lists the open source", "t_throttled" in state and state["t_throttled"]["failures"] == 3, str(state))

reset_circuits()
Flaky.calls = 0
for _ in range(3):
    _, health, _ = _run(search_round(["q"], sources=["t_flaky"]))
check("two failures then a success never opens the breaker",
      health["t_flaky"] == "ok" and "t_flaky" not in circuit_state(), str(health))

reset_circuits()
Throttled.calls = 0
settings.source_circuit_failures = 0
for _ in range(5):
    _run(search_round(["q"], sources=["t_throttled"]))
check("threshold 0 disables the breaker", Throttled.calls == 5 and circuit_state() == {})
settings.source_circuit_failures = 3

# ── auth rejection opens at once with the env-var hint ───────────────────────

reset_circuits()
Rejected.calls = 0
_, health, _ = _run(search_round(["q"], sources=["t_auth"]))
check("401 reported as auth rejected with the key to check",
      health["t_auth"] == "failed: auth rejected (401) — check T_AUTH_KEY", health["t_auth"])
_, health, _ = _run(search_round(["q"], sources=["t_auth"]))
check("401 opens the circuit immediately (second call skipped)",
      Rejected.calls == 1 and "circuit" not in health["t_auth"] and "auth rejected" in health["t_auth"],
      f"calls={Rejected.calls} {health}")

# ── litsearch buckets: failed lands in failed, not empty ─────────────────────

reset_circuits()
buckets: dict[str, list[int]] = {}
cells = _run(search_one_query("q", ["t_ok", "t_empty", "t_throttled"], health_out=buckets))
check("search_one_query returns a cell per source", set(cells) == {"t_ok", "t_empty", "t_throttled"})
check("ok cell -> [1,0,0]", buckets["t_ok"] == [1, 0, 0], str(buckets))
check("empty cell -> [0,1,0]", buckets["t_empty"] == [0, 1, 0], str(buckets))
check("FAILED cell -> [0,0,1] (was counted as empty before the key fix)",
      buckets["t_throttled"] == [0, 0, 1], str(buckets))

# ── failure_reason ───────────────────────────────────────────────────────────

check("failure_reason: status + attempts", failure_reason(_http_error(503, 4)) == "HTTP 503 after 4 attempts")
check("failure_reason: single attempt omits the suffix", failure_reason(_http_error(500, 1)) == "HTTP 500")
check("failure_reason: braces sanitised for the stdout-JSON contract",
      "{" not in failure_reason(RuntimeError('body {"error": 1}')))
check("failure_reason: class only when message empty", failure_reason(TimeoutError()) == "TimeoutError")

# ── arXiv: timeout is raised (failed), not returned as [] (empty) ─────────────

from citens.search.arxiv import ArxivSearcher  # noqa: E402

arx = ArxivSearcher()
arx.SOURCE_TIMEOUT_S = 0.05


def _slow(_kws, _n):
    import time

    time.sleep(0.5)
    return []


arx._search_sync = _slow  # type: ignore[method-assign]
try:
    _run(arx.search(["q"], 5))
    arx_outcome = "returned"
except TimeoutError as e:
    arx_outcome = f"raised: {e}"
check("arXiv timeout raises TimeoutError naming the budget",
      arx_outcome.startswith("raised") and "0.05s" in arx_outcome, arx_outcome)

# ── cache: empty values are not stored unless allowed ────────────────────────

tmp = tempfile.mkdtemp(prefix="citens-cache-test-")
settings.cache_enabled = True
settings.cache_dir = tmp
cache.put("t", {"k": 1}, [])
check("empty list not cached", cache.get("t", {"k": 1}) is None)
cache.put("t", {"k": 2}, {})
check("empty dict not cached", cache.get("t", {"k": 2}) is None)
cache.put("t", {"k": 3}, "")
check("empty string not cached", cache.get("t", {"k": 3}) is None)
cache.put("t", {"k": 4}, None)
check("None not cached", cache.get("t", {"k": 4}) is None)
cache.put("t", {"k": 5}, [], allow_empty=True)
check("allow_empty stores the empty list", cache.get("t", {"k": 5}) == [])
cache.put("t", {"k": 6}, 0)
check("zero is a value, cached", cache.get("t", {"k": 6}) == 0)
cache.put("t", {"k": 7}, {"paper": None, "note": "not found"})
check("non-empty negative dict still cached", cache.get("t", {"k": 7}) == {"paper": None, "note": "not found"})
check("is_empty_value helper", cache.is_empty_value(()) and not cache.is_empty_value(False))

# ── fulltext: a failed fetch is a short-TTL miss, never a permanent "" ───────

from citens.grounding import fulltext as ft  # noqa: E402

settings.papers_dir = str(Path(tmp) / "papers")
settings.fulltext_miss_ttl_days = 1
p = Paper(title="No open access anywhere", authors=["X"], year=2020, source="test")
text1 = ft.fetch_fulltext(p)
report1 = ft.fetch_report(p.id)
check("no-candidate paper returns None", text1 is None)
check("miss recorded under fulltext.miss, not fulltext",
      cache.get("fulltext", p.id) is None and cache.get("fulltext.miss", p.id) is not None)
text2 = ft.fetch_fulltext(p)
report2 = ft.fetch_report(p.id)
check("second call short-circuits on the miss with an explanatory report",
      text2 is None and "不重试" in report2, report2)
check("first report explains the legs tried", report1 == "无OA候选", report1)

# legacy poison: "" stored under fulltext must fall through to a new attempt
cache.put("fulltext", p.id, "", allow_empty=True)
ft._FETCH_REPORTS.pop(p.id, None)
# wipe the miss so only the legacy "" remains
miss_key = cache._path(cache._key("fulltext.miss", p.id))
Path(miss_key).unlink(missing_ok=True)
text3 = ft.fetch_fulltext(p)
check("legacy cached '' is ignored and refetch attempted (miss re-recorded)",
      text3 is None and cache.get("fulltext.miss", p.id) is not None)

settings.fulltext_miss_ttl_days = 0
Path(miss_key).unlink(missing_ok=True)
ft.fetch_fulltext(p)
check("miss TTL 0 -> nothing recorded, retried every run", cache.get("fulltext.miss", p.id) is None)
settings.fulltext_miss_ttl_days = 1

# ── summary ──────────────────────────────────────────────────────────────────

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
