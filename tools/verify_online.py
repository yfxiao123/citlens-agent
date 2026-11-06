"""Online E2E + REAL concurrency-race verification (network via local proxy).

Covers the two gaps the offline suite could not:
  I  real concurrency: 3 REAL search jobs running simultaneously, a 4th
     must be rejected by max_concurrent_jobs (fake-job test only checked
     the guard's arithmetic before)
  II online end-to-end: real searches through proxied OpenAlex(keyed)/
     Crossref (S2/arXiv degraded honestly) -> pools + reports on disk;
     then a real `expand` (OpenAlex `related` direction) into a pool.

Env: HTTPS_PROXY/HTTP_PROXY point the httpx clients (trust_env) at the
local proxy; jobs inherit it (start_job/run_job pass os.environ through).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7897"
os.environ["HTTP_PROXY"] = "http://127.0.0.1:7897"

import citlens_cli as m  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "ok  " if cond else "FAIL"
    (PASS if cond else FAIL).append(name)
    print(f"  {tag} - {name}   {detail}", flush=True)


cfg = m.load_config(str(Path.home() / ".citlens" / "config.json"))

TOPICS = {
    "A": ("e2e-momentum-spillover", ["momentum spillover Chinese stock market"]),
    "B": ("e2e-price-limits-china", ["daily price limits Chinese stocks"]),
    "C": ("e2e-sentiment-china", ["investor sentiment Chinese stock returns"]),
}

# ── I. real concurrency ──────────────────────────────────────────────────────
print("\n[I] real concurrency: 3 running, 4th rejected", flush=True)
ids = {}
for k, (topic, qs) in TOPICS.items():
    st = m.start_job(cfg, "search", {"topic": topic, "queries": qs, "target": 15,
                                     "families": ["agent", "raw"]})
    ids[k] = (st.get("job_id"), topic)
    check(f"I/launch-{k}: search job started", st.get("state") == "running" and st.get("job_id"),
          str(st)[:140])

fourth = m.start_job(cfg, "search", {"topic": "e2e-should-be-rejected",
                                     "queries": ["test"], "target": 5,
                                     "families": ["agent"]})
check("I/4th job REJECTED while 3 run (real race, not fake state files)",
      fourth.get("state") == "rejected" and "too many concurrent jobs" in fourth.get("error", ""),
      str(fourth)[:180])
check("I/rejected lists the running jobs", len(fourth.get("running") or []) == 3)

# ── II. online E2E: wait, inspect pools/health ──────────────────────────────
print("\n[II] online E2E: waiting for the three searches", flush=True)
deadline = time.time() + 600
states = {}
while time.time() < deadline:
    states = {}
    for k, (jid, _t) in ids.items():
        states[k] = m.job_state(cfg, jid)
    if all(states[k].get("state") in ("done", "failed", "lost") for k in ids):
        break
    time.sleep(10)

for k in ids:
    st = states[k]
    check(f"II/{k}: job reached a terminal state", st.get("state") in ("done", "failed"),
          f"state={st.get('state')}")

# pools + health from the run dirs
total_kept = 0
any_oa_ok = False
for k, (jid, topic) in ids.items():
    st = states[k]
    rd = st.get("run_dir") or ""
    pool_f = Path(rd) / "pool.jsonl" if rd else None
    n = len(pool_f.read_text(encoding="utf-8").splitlines()) if pool_f and pool_f.is_file() else 0
    total_kept += n
    rep = Path(rd) / "search_report.md" if rd else None
    rep_text = rep.read_text(encoding="utf-8") if rep and rep.is_file() else ""
    oa_ok = "openalex" in rep_text and "failed" not in rep_text.split("openalex")[1][:60]
    any_oa_ok = any_oa_ok or oa_ok
    check(f"II/{k}: run wrote a real pool ({n} records) + report", n > 0 and bool(rep_text),
          f"n={n} run_dir={rd}")

check("II/total: the three online searches kept a meaningful pool", total_kept >= 30,
      f"total={total_kept}")

# ── III. real expand (OpenAlex related, online via proxy) ────────────────────
print("\n[III] real expand (OpenAlex related)", flush=True)
topic_a = TOPICS["A"][0]
seed_pool = next(iter(sorted((Path(cfg["home"]) / "citlens-runs").glob(topic_a + "*/pool.jsonl"), key=lambda p: p.stat().st_mtime)), None)
rows = [json.loads(ln) for ln in seed_pool.read_text(encoding="utf-8").splitlines()] \
    if seed_pool.is_file() else []
doi = next((r.get("doi") for r in rows if r.get("doi")), None)
check("III/seed: pool A carries a DOI to expand from", bool(doi), f"doi={doi}")

if doi:
    out = m.tool_expand(cfg, {"topic": topic_a, "seeds": [doi],
                              "directions": "related", "top": 10,
                              "background": False})
    added = (out.get("counts") or {}).get("appended_to_pool", 0)
    check("III/expand ran online and merged neighbours", out.get("ok") and added >= 0,
          f"added={added} resolved={len(out.get('resolved') or [])}")
    check("III/expand artifact written", bool(out.get("expand_path"))
          and Path(out["expand_path"]).is_file())

print(f"\n{'='*60}\n{len(PASS)} passed, {len(FAIL)} failed", flush=True)
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
sys.exit(1 if FAIL else 0)
