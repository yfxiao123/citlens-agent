"""Offline tests for pool-level signals (`citens/signals.py`).

Chao1 hand-checked against the textbook estimator; saturation verdicts and
expand advice checked on synthetic capture histories / screening rows.
Script style: .venv/Scripts/python tests/test_signals.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from citens.config import settings  # noqa: E402
from citens.signals import chao_coverage, expand_advice, saturation, saturation_note  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    if cond:
        PASS.append(name)
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name}")


# ── chao_coverage ────────────────────────────────────────────────────────────

# hand case: S=60, f1=12 (single-family), f2=30 (two-family), rest 18 in ≥3
hist = [["agent"]] * 12 + [["agent", "raw"]] * 15 + [["snowball", "agent"]] * 15 \
    + [["agent", "raw", "snowball"]] * 10 + [["s2_rec", "web", "survey"]] * 8
ch = chao_coverage(hist)
check("chao: counts S/f1/f2/families",
      ch["observed"] == 60 and ch["f1"] == 12 and ch["f2"] == 30 and ch["families"] == 6)
check("chao: N̂ = S + f1²/2f2 = 60 + 144/60",
      abs(ch["n_hat"] - (60 + 144 / 60.0)) < 0.05)
check("chao: coverage = S/N̂ capped at 1",
      abs(ch["coverage"] - min(60 / (60 + 2.4), 1.0)) < 0.001)

check("chao: no recaptures (f2=0) -> None, never a guess",
      chao_coverage([["a"]] * 10)["coverage"] is None)
check("chao: single family -> None (nothing to estimate)",
      chao_coverage([["a"], ["a", "a"]])["coverage"] is None)
check("chao: empty input -> None with zero observed",
      chao_coverage([])["coverage"] is None and chao_coverage([])["observed"] == 0)
check("chao: blank found_by entries are skipped",
      chao_coverage([None, [], {"agent"}] )["observed"] == 1)

# ── saturation verdicts ──────────────────────────────────────────────────────

saturated = saturation(hist, new_records=5, kept=60, weak_queries=0, total_queries=8)
check("sat: healthy pool -> near_saturation with Chao reason",
      saturated["verdict"] == "near_saturation"
      and any("估计覆盖" in r for r in saturated["reasons"]))
check("sat: note carries the caveat and the verdict in Chinese",
      "接近饱和" in saturation_note(saturated) and "Chao1" in saturation_note(saturated))

thin = saturation([["a"]] * 5, new_records=1, kept=5, weak_queries=0, total_queries=1)
check("sat: below sat_min_records with quiet signals -> unknown",
      thin["verdict"] == "unknown" and settings.sat_min_records > 5)
check("sat: thin pool with everything new -> growth says keep_going",
      saturation([["a"]] * 5, new_records=5, kept=5, weak_queries=0,
                 total_queries=1)["verdict"] == "keep_going")

# low coverage: all singletons (f2=0), no growth signal -> unknown
low = saturation([["agent"]] * 20 + [["raw"]] * 20,
                 new_records=2, kept=40, weak_queries=0, total_queries=4)
check("sat: coverage None (f2=0) and quiet signals -> unknown",
      low["verdict"] == "unknown")

# measured case (2026-11-05 real run): f2=0 coverage=None but 86% new records
# -> the growth signal alone decides keep_going, coverage honestly None
real = saturation([["agent"]] * 20 + [["raw"]] * 20,
                  new_records=34, kept=40, weak_queries=0, total_queries=4)
check("sat: coverage None + high growth -> keep_going citing growth",
      real["verdict"] == "keep_going" and real["chao"]["coverage"] is None
      and any("池仍在显著生长" in r for r in real["reasons"]))

# genuinely low but estimable coverage: f1 dominates, f2 small -> keep_going
low2 = saturation([["agent", "raw"]] * 2 + [["agent"]] * 20 + [["raw"]] * 20,
                  new_records=10, kept=40, weak_queries=0, total_queries=4)
check("sat: estimable low coverage -> keep_going citing missing recall",
      low2["verdict"] == "keep_going"
      and any("未召回" in r for r in low2["reasons"]))

# growth reason: coverage fine but the pool is still growing fast
growing = saturation(
    [["agent", "raw"]] * 25 + [["agent"]] * 5,  # S=30, f1=5, f2=25 -> N̂=30.5, cov 98%
    new_records=30, kept=30, weak_queries=0, total_queries=4)
check("sat: high new_share -> keep_going citing pool growth",
      growing["verdict"] == "keep_going"
      and any("池仍在显著生长" in r for r in growing["reasons"]))

# weak-query reason: vocabulary mismatch dominates
weak = saturation(
    [["agent", "raw"]] * 25 + [["agent"]] * 5,
    new_records=2, kept=30, weak_queries=4, total_queries=6)
check("sat: weak queries -> keep_going citing rephrasing",
      weak["verdict"] == "keep_going"
      and any("词汇错配" in r for r in weak["reasons"]))

check("sat: missing new_records (first run, no litdb) still verdicts on coverage",
      saturation([["a", "b"]] * 25 + [["a"]] * 5,
                 new_records=None, kept=30, weak_queries=0, total_queries=4)["verdict"]
      in ("near_saturation", "keep_going"))

# ── expand advice ────────────────────────────────────────────────────────────

check("advice: empty pool -> not considering, says so",
      expand_advice([])["consider"] is False)

healthy_rows = (
    [{"band": "core", "found_by": ["agent", "raw", "snowball"]}] * 14
    + [{"band": "uncertain", "found_by": ["agent", "s2_rec"]}] * 4
    + [{"band": "likely_off", "found_by": ["web"]}] * 2
)
adv = expand_advice(healthy_rows)
check("advice: healthy pool -> no suggestion",
      adv["consider"] is False and adv["command"] == ""
      and "健康" in adv["reasons"][0])

uncertain_heavy = [{"band": "uncertain", "found_by": ["agent", "raw"]}] * 10
adv2 = expand_advice(uncertain_heavy)
check("advice: uncertain band >= threshold fires with the command named",
      adv2["consider"] is True
      and any("悬而未决" in r for r in adv2["reasons"])
      and "expand --from-notes core" in adv2["command"])

single_heavy = [{"band": "core", "found_by": ["agent"]}] * 12
adv3 = expand_advice(single_heavy)
check("advice: single-family core fires the corroboration reason",
      adv3["consider"] is True and any("佐证" in r for r in adv3["reasons"]))

thin_core = [{"band": "core", "found_by": ["agent", "raw", "snowball"]}] * 4
adv4 = expand_advice(thin_core)
check("advice: core below min fires the too-thin reason",
      adv4["consider"] is True and any("太薄" in r for r in adv4["reasons"]))

# decide-refined rows work as-is: escalated rows ARE uncertain rows
escalated_rows = [{"band": "uncertain", "found_by": ["agent", "raw"],
                   "decided_by": "escalated:low_confidence"}] * 10
check("advice: decide-escalated rows count toward uncertainty",
      expand_advice(escalated_rows)["consider"] is True)

# ── summary ──────────────────────────────────────────────────────────────────

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
