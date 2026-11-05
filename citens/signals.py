"""Pool-level decision signals — mechanical, LLM-free.

Two signals, one file, both consumed where the pool already lives:

**Saturation (the "when to stop searching" answer)** — capture–recapture
over ``found_by``: the recall families are independent-ish trapping
occasions, a paper surfacing in ≥2 of them is a recapture. Chao1
(N̂ = S + f1²/2f2) turns the singleton/two-family counts into an
estimated population, and S/N̂ into an estimated coverage. When coverage
is high, this run added mostly known records, and the queries were
answered, the search report says 近饱和 — the mechanical version of the
skill's stage-F saturation check.

**Expand advice (the "when to widen" answer)** — pool-level uncertainty
after ``screen``: a large uncertain band, a large single-family share
(uncorroborated recall — the vocabulary-mismatch signature), or a core
too thin to ground a review each suggest expansion around the judged-core
notes (``expand --from-notes core``, the judgment feedback loop).

Honesty rules: both signals are heuristics with explicit thresholds
(settings, awaiting calibration), both degrade to ``unknown`` rather than
guessing when the inputs are too thin, and saturation always carries the
Chao1 caveat — families share queries (agent/raw are both query-driven),
dependence underestimates N̂ and therefore OVERESTIMATES coverage. The
verdict is a signal, never a conclusion.
"""

from __future__ import annotations

from collections import Counter

from citens.config import settings

# ── saturation: capture–recapture over found_by ──────────────────────────────

def chao_coverage(found_by_lists) -> dict:
    """Chao1 over family capture histories.

    ``found_by_lists``: iterable of the records' found_by collections.
    Returns ``{"observed": S, "f1": ..., "f2": ..., "n_hat": ...,
    "coverage": ...}``; ``coverage``/``n_hat`` are ``None`` when the
    estimator is undefined (no recaptures at all — nothing to estimate
    from; or fewer than 2 contributing families).
    """
    histories = [set(f or []) for f in found_by_lists]
    histories = [h for h in histories if h]
    s = len(histories)
    fams = set().union(*histories) if histories else set()
    counts = Counter(len(h) for h in histories)
    f1, f2 = counts.get(1, 0), counts.get(2, 0)
    out = {"observed": s, "f1": f1, "f2": f2, "families": len(fams)}
    if s == 0 or len(fams) < 2 or f2 == 0:
        out["n_hat"] = None
        out["coverage"] = None
        return out
    n_hat = s + (f1 * f1) / (2.0 * f2)
    out["n_hat"] = round(n_hat, 1)
    out["coverage"] = round(min(s / n_hat, 1.0), 3)
    return out


def saturation(
    found_by_lists,
    *,
    new_records: int | None = None,
    kept: int = 0,
    weak_queries: int = 0,
    total_queries: int = 0,
) -> dict:
    """Compose the stop/continue signals into a verdict.

    ``new_records``/``kept``: how many of this run's kept records were new
    to the topic pool (the driver computes the overlap). ``weak_queries``/
    ``total_queries``: the query-feedback table's empty/thin counts.
    Verdict: ``near_saturation`` | ``keep_going`` | ``unknown``, with the
    fired reasons listed — the caller prints them verbatim.
    """
    chao = chao_coverage(found_by_lists)
    cov = chao["coverage"]
    new_share = (new_records / kept) if kept and new_records is not None else None
    weak_share = (weak_queries / total_queries) if total_queries else None
    signals = {
        "chao": chao,
        "new_share": round(new_share, 3) if new_share is not None else None,
        "weak_query_share": round(weak_share, 3) if weak_share is not None else None,
    }
    cov_unknown = chao["observed"] < settings.sat_min_records or cov is None
    # Coverage-independent signals first: a fast-growing pool or unresolved
    # vocabulary mismatch says keep_going even when Chao1 has nothing to
    # estimate from (measured: a 2-family rephrase run had f2=0 coverage=None
    # while 86% of its records were new — the growth signal alone decides).
    reasons: list[str] = []
    if new_share is not None and new_share > settings.sat_new_share_stop:
        reasons.append(
            f"本轮 {new_share:.0%} 记录对主题池是新的（> {settings.sat_new_share_stop:.0%}"
            "）——池仍在显著生长"
        )
    if weak_share is not None and weak_share >= settings.sat_weak_query_stop:
        reasons.append(
            f"{weak_share:.0%} 查询 empty/thin（≥ {settings.sat_weak_query_stop:.0%}"
            "）——词汇错配未消除，先换论文侧词汇重拟"
        )
    if cov_unknown:
        if reasons:
            return {**signals, "verdict": "keep_going", "reasons": reasons}
        return {
            **signals,
            "verdict": "unknown",
            "reasons": [
                (f"记录过少或无跨家族重捕（S={chao['observed']}, f2={chao['f2']}）"
                 "——无法估计覆盖")
            ],
        }
    if cov < settings.sat_coverage_stop:
        reasons.append(
            f"估计覆盖 {cov:.0%} < {settings.sat_coverage_stop:.0%}"
            f"（N̂≈{chao['n_hat']:.0f}，还有约 {chao['n_hat'] - chao['observed']:.0f} 篇未召回）"
        )
    if reasons:
        return {**signals, "verdict": "keep_going", "reasons": reasons}
    return {
        **signals,
        "verdict": "near_saturation",
        "reasons": [
            f"估计覆盖 {cov:.0%}（Chao1，S={chao['observed']} f1={chao['f1']} "
            f"f2={chao['f2']} → N̂≈{chao['n_hat']:.0f}）"
            + (f"，本轮新增仅 {new_share:.0%}" if new_share is not None else "")
            + ("，查询全部有效命中" if weak_share == 0 else "")
        ],
    }


def saturation_note(sat: dict) -> str:
    """The one-line caveat every saturation verdict must carry."""
    verdict = sat.get("verdict")
    zh = {"near_saturation": "接近饱和", "keep_going": "建议继续", "unknown": "无法判定"}.get(verdict, verdict)
    return (
        f"{zh}——" + "；".join(sat.get("reasons") or [])
        + "。Chao1 假定家族独立：agent/raw 同源查询会高估覆盖，"
        "判定是信号不是结论；收工仍需 `audit` 锚点核验。"
    )


# ── expand advice: pool-level uncertainty after screen ───────────────────────

def expand_advice(rows) -> dict:
    """Should the pool be widened (expand around judged-core notes)?

    ``rows``: screening rows (``band`` + ``found_by`` per record; decide-
    refined rows work as-is — an escalated share IS uncertainty). Fires
    when any signal crosses its threshold; never auto-triggers anything —
    the advice names the command, the agent decides.
    """
    rows = list(rows or [])
    n = len(rows)
    if n == 0:
        return {"consider": False, "signals": {}, "reasons": ["空池"], "command": ""}
    bands = Counter(r.get("band") for r in rows)
    uncertain_share = bands.get("uncertain", 0) / n
    single = sum(1 for r in rows if len(set(r.get("found_by") or [])) <= 1)
    single_share = single / n
    core_n = bands.get("core", 0)
    signals = {
        "n": n,
        "core": core_n,
        "uncertain_share": round(uncertain_share, 3),
        "single_family_share": round(single_share, 3),
    }
    reasons: list[str] = []
    if uncertain_share >= settings.expand_uncertain_share:
        reasons.append(
            f"uncertain 带 {uncertain_share:.0%} ≥ {settings.expand_uncertain_share:.0%}"
            "——分带后仍大片悬而未决"
        )
    if single_share >= settings.expand_single_family_share:
        reasons.append(
            f"单家族命中 {single_share:.0%} ≥ {settings.expand_single_family_share:.0%}"
            "——召回未经跨家族佐证（词汇错配的典型信号）"
        )
    if core_n < settings.expand_min_core:
        reasons.append(
            f"core 仅 {core_n} 篇 < {settings.expand_min_core}——太薄，撑不起综述的地基"
        )
    return {
        "consider": bool(reasons),
        "signals": signals,
        "reasons": reasons or ["三分带健康：uncertain/单家族占比低，core 充足"],
        "command": (
            "expand --from-notes core（把逐篇判定的 core 笔记当种子做引文链+相似推荐扩展）"
            if reasons else ""
        ),
    }
