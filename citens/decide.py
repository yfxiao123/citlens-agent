"""The optional decision layer for ``screen`` — System-1 relevance triage.

The retrieval core stays LLM-free by design. This module is opt-in
(``screen --decide``) and uses whatever OpenAI-compatible endpoint the user
configured (``LLM_API_BASE`` / ``LLM_API_KEY`` / ``LLM_MODEL``). A record's
relevance band is read as a categorical distribution over three bracketed
options via next-token logprobs — the training-free readout recipe of
LLM-as-Jev (arXiv:2610.02076), no fine-tuning involved.

Calibrated confidence powers **selective prediction**: a record whose top
band probability reaches ``decide_auto_band`` is auto-banded; below it the
record escalates to the agent's own review (forced ``uncertain``). The
decision model only does the cheap first pass — the agent keeps the
judgment work. Independent agreement between the decision model and the
mechanical channels (embedding + BM25 + family votes) auto-bands at a lower
cutoff, because agreement is evidence.

Honesty rules (the reason this layer can be trusted at all):

* an endpoint error never invents a band — failed records keep their
  mechanical band with ``decided_by="mechanical_fallback"``;
* an off-script readout (too little probability mass on the three option
  tokens) is escalated, never guessed;
* provenance is written per record (``decided_by``, ``decision_probs``,
  ``decision_confidence``, ``agrees_mechanical``, ``mechanical_band``);
* nothing is excluded here — triage, not judgment (PRISMA stays with the
  agent).

Evidence base for the policy defaults: Jev-class models are strong,
well-calibrated classifiers but TIE with baselines on RAG relevance gating
when fed raw text cold (arXiv:2610.02267) — so the decision is grounded in
the mechanical channels' context (topic + the agent's own concept-block
queries) rather than a bare title, thresholds stay conservative (escalate
by default), and every threshold is a setting awaiting LitSearch
calibration rather than a magic constant.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from citens.config import settings

BANDS = ("core", "uncertain", "likely_off")
_OPTION_BAND = {"1": "core", "2": "uncertain", "3": "likely_off"}

_SYSTEM_PROMPT = (
    "You are a relevance triage judge inside a literature-search tool. "
    "Classify the record given by the user into exactly one band:\n"
    "[1] core — directly about the topic's methods or subject matter; a "
    "literature review of this topic would likely cite it.\n"
    "[2] uncertain — adjacent or partially related, or you cannot tell from "
    "the title and abstract alone.\n"
    "[3] likely_off — a literal word collision or a different field; a "
    "review of this topic would almost certainly not cite it.\n"
    "Answer with exactly one bracketed number — [1], [2] or [3] — and "
    "nothing else."
)


def _paper_key(doi: str | None, title: str) -> str:
    """Same key screening.py rows use, so decisions merge by identity."""
    return doi or (title or "").lower().strip()


def build_messages(topic: str, title: str, abstract: str) -> list[dict]:
    abstract = (abstract or "").strip()
    if len(abstract) > 1200:
        abstract = abstract[:1200].rstrip() + "…"
    user = (
        f"Research topic: {topic}\n\n"
        f"Record title: {title}\n\n"
        f"Abstract: {abstract or '(no abstract available)'}\n\n"
        "Band: "
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def band_distribution(
    logprobs_content: list[dict] | None,
) -> tuple[dict[str, float], float]:
    """Read a categorical distribution over the three bracketed options.

    Walks the first few generated tokens' ``top_logprobs`` (the answer is
    typically ``"["`` then ``"2]"``, or one ``"[2]"`` token), picks the best
    probability seen per band, normalizes over the matched mass, and
    returns ``(probs, matched_mass)``. ``matched_mass`` well below 1 means
    the model went off-script — the caller should distrust the readout.
    """
    best: dict[str, float] = {b: 0.0 for b in BANDS}
    if logprobs_content:
        for entry in logprobs_content[:3]:
            for cand in entry.get("top_logprobs") or []:
                token = (cand.get("token") or "").strip()
                token = token.strip("[]()").strip().rstrip("].,;")
                band = _OPTION_BAND.get(token)
                if band:
                    p = math.exp(cand.get("logprob", -9999.0))
                    if p > best[band]:
                        best[band] = p
    mass = sum(best.values())
    if mass <= 0.0:
        return {b: 0.0 for b in BANDS}, 0.0
    return {b: best[b] / mass for b in BANDS}, min(mass, 1.0)


@dataclass
class Decision:
    band: str
    probs: dict[str, float]
    confidence: float
    matched_mass: float
    raw_answer: str = ""

    def reliable(self, *, mass_min: float | None = None) -> bool:
        floor = settings.decide_matched_mass_min if mass_min is None else mass_min
        return self.matched_mass >= floor


@dataclass
class DecideStats:
    requested: int = 0
    decided: int = 0
    unreliable: int = 0
    failed: int = 0
    last_error: str = ""
    elapsed_s: float = 0.0
    endpoint: str = ""
    model: str = ""
    notes: list[str] = field(default_factory=list)


def _configured() -> tuple[str, str, str]:
    base = (settings.llm_api_base or "").strip().rstrip("/")
    key = (settings.llm_api_key or "").strip()
    model = (settings.llm_model or "").strip()
    return base, key, model


async def decide_papers(
    papers,
    topic: str,
    *,
    limit: int = 0,
    sleep=None,
    transport=None,
) -> tuple[dict[str, Decision], DecideStats]:
    """Read a triage decision per paper. Returns ``{paper_key: Decision}``.

    Failures degrade honestly: a paper without a decision simply stays out
    of the dict (the caller keeps its mechanical band), and the stats carry
    the failure counts plus the last error.
    """
    from citens import net

    stats = DecideStats()
    base, key, model = _configured()
    if not (base and key and model):
        stats.notes.append(
            "decide: LLM 端点未配置（LLM_API_BASE / LLM_API_KEY / LLM_MODEL）——"
            "保留机械分带，未发起任何决策请求"
        )
        return {}, stats
    stats.endpoint = urlparse(base).hostname or base
    stats.model = model

    batch = list(papers)
    if limit and limit > 0:
        batch = batch[:limit]

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    client = net.async_client(
        "decide_llm",
        timeout=60.0,
        headers=headers,
        min_interval=settings.decide_min_interval_s,
        url=base,
        max_attempts=settings.http_max_attempts,
        transport=transport,
    )
    url = f"{base}/chat/completions"
    decisions: dict[str, Decision] = {}
    started = time.monotonic()
    sleep = sleep or asyncio.sleep
    try:
        for i, p in enumerate(batch, 1):
            stats.requested += 1
            try:
                resp = await client.post(
                    url,
                    json={
                        "model": model,
                        "messages": build_messages(topic, p.title, p.abstract),
                        "max_tokens": 4,
                        "temperature": 0.0,
                        "logprobs": True,
                        "top_logprobs": 10,
                    },
                )
                resp.raise_for_status()
                choice = resp.json()["choices"][0]
                content_lp = ((choice.get("logprobs") or {}).get("content")) or []
                probs, mass = band_distribution(content_lp)
                raw = ((choice.get("message") or {}).get("content") or "").strip()
                dec = Decision(
                    band=max(BANDS, key=lambda b: probs[b]),
                    probs={b: round(probs[b], 4) for b in BANDS},
                    confidence=round(max(probs.values()), 4),
                    matched_mass=round(mass, 4),
                    raw_answer=raw[:20],
                )
                if not dec.reliable():
                    stats.unreliable += 1
                else:
                    stats.decided += 1
                    decisions[_paper_key(p.doi, p.title)] = dec
            except Exception as e:  # noqa: BLE001 — one bad record must not kill the batch
                stats.failed += 1
                stats.last_error = f"{type(e).__name__}: {str(e)[:120]}"
            if i % 10 == 0 or i == len(batch):
                print(
                    f"[decide] {i}/{len(batch)} decided={stats.decided} "
                    f"unreliable={stats.unreliable} failed={stats.failed}",
                    flush=True,
                )
    finally:
        await client.aclose()
        stats.elapsed_s = round(time.monotonic() - started, 1)
    if stats.failed:
        stats.notes.append(
            f"decide: {stats.failed}/{stats.requested} 条请求失败"
            f"（{stats.last_error}）——这些记录保留机械分带"
        )
    if stats.unreliable:
        stats.notes.append(
            f"decide: {stats.unreliable} 条 readout 偏离格式"
            f"（选项概率质量 < {settings.decide_matched_mass_min}）——升级人工，不猜"
        )
    return decisions, stats


def apply_selective(
    rows: list[dict],
    decisions: dict[str, Decision],
    *,
    auto_band: float | None = None,
    agree_band: float | None = None,
) -> tuple[list[dict], dict]:
    """Merge decisions into screening rows under selective prediction.

    Band policy per row:
    * no decision -> keep the mechanical band, ``decided_by=mechanical_fallback``;
    * reliable decision with ``confidence >= auto_band`` -> the decision
      band, ``decided_by=decision_model``;
    * reliable decision with ``confidence >= agree_band`` AND the mechanical
      band agrees -> the shared band, ``decided_by=decision_model``;
    * otherwise -> ``uncertain``, ``decided_by=escalated:low_confidence``
      (the agent reads it — that is the point of the escalation band).
    """
    auto_t = settings.decide_auto_band if auto_band is None else auto_band
    agree_t = settings.decide_agree_band if agree_band is None else agree_band
    counts = {"auto": 0, "escalated": 0, "fallback": 0}
    agrees = 0
    flips: dict[str, int] = {}
    for row in rows:
        dec = decisions.get(row.get("key") or "")
        mechanical = row.get("band")
        row["mechanical_band"] = mechanical
        if dec is None or not dec.reliable():
            row["decided_by"] = "mechanical_fallback"
            counts["fallback"] += 1
            continue
        row["decision_probs"] = dec.probs
        row["decision_confidence"] = dec.confidence
        row["agrees_mechanical"] = dec.band == mechanical
        if dec.confidence >= auto_t or (dec.confidence >= agree_t and row["agrees_mechanical"]):
            row["band"] = dec.band
            row["decided_by"] = "decision_model"
            counts["auto"] += 1
            if row["agrees_mechanical"]:
                agrees += 1
            else:
                flips[f"{mechanical}->{dec.band}"] = flips.get(f"{mechanical}->{dec.band}", 0) + 1
        else:
            row["band"] = "uncertain"
            row["decided_by"] = "escalated:low_confidence"
            counts["escalated"] += 1
            if mechanical != "uncertain":
                flips[f"{mechanical}->uncertain"] = flips.get(f"{mechanical}->uncertain", 0) + 1
    auto_rows = [r for r in rows if r.get("decided_by") == "decision_model"]
    summary = {
        **counts,
        "auto_agrees_mechanical": agrees,
        "band_flips": flips,
        "auto_rate": round(counts["auto"] / len(rows), 3) if rows else 0.0,
        "flip_rate": round(sum(flips.values()) / len(rows), 3) if rows else 0.0,
        # agreement with the mechanical channels, NOT verified precision —
        # precision needs a gold set (LitSearch calibration, pending)
        "mech_agree_rate": round(agrees / len(auto_rows), 3) if auto_rows else None,
    }
    return rows, summary


def refine_screen_report(
    papers,
    report: dict,
    *,
    topic: str,
    out_path=None,
    limit: int = 0,
    auto_band: float | None = None,
    agree_band: float | None = None,
) -> dict:
    """Sync entry point for the tools driver: decide + merge into a
    ``screen`` report (and rewrite ``screening.jsonl`` when it exists)."""
    decisions, stats = asyncio.run(
        decide_papers(papers, topic, limit=limit)
    )
    rows: list[dict] = []
    if out_path is not None and out_path.exists():
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        rows = payload.get("papers") or []
    if not rows:
        rows = [
            {
                "key": _paper_key(t.get("doi"), t.get("title") or ""),
                "title": t.get("title"),
                "doi": t.get("doi"),
                "year": t.get("year"),
                "band": t.get("band"),
            }
            for t in report.get("papers", [])
        ]
    rows, summary = apply_selective(
        rows, decisions, auto_band=auto_band, agree_band=agree_band
    )

    # re-sync the report's top rows + band counts from the refined rows
    by_key = {r.get("key"): r for r in rows}
    for top in report.get("papers", []):
        refined = by_key.get(_paper_key(top.get("doi"), top.get("title") or ""))
        if refined:
            top["band"] = refined["band"]
            top["decided_by"] = refined.get("decided_by")
    bands = {"core": 0, "uncertain": 0, "likely_off": 0}
    for r in rows:
        bands[r["band"]] = bands.get(r["band"], 0) + 1
    report["bands"] = bands

    if out_path is not None and out_path.exists():
        payload["papers"] = rows
        payload["bands"] = bands
        payload["decide"] = summary
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    report["decide"] = {
        "enabled": True,
        "endpoint": stats.endpoint,
        "model": stats.model,
        "stats": {
            "requested": stats.requested,
            "decided": stats.decided,
            "unreliable": stats.unreliable,
            "failed": stats.failed,
            "elapsed_s": stats.elapsed_s,
        },
        "summary": summary,
        "thresholds": {
            "auto_band": settings.decide_auto_band if auto_band is None else auto_band,
            "agree_band": settings.decide_agree_band if agree_band is None else agree_band,
            "matched_mass_min": settings.decide_matched_mass_min,
        },
        "notes": stats.notes,
        "note": (
            "决策层只做分流：auto 条目已按校准概率定带，escalated 条目强制 uncertain "
            "等待 agent 逐篇终审，failed/unreliable 条目保留机械分带。阈值尚未在 "
            "LitSearch 金标上校准——报告时请连同 thresholds 一起给出。"
        ),
    }
    if stats.notes:
        report["note"] = (report.get("note") or "") + " | " + " | ".join(stats.notes)
    return report
