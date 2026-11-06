"""Calibrate the mechanical screen bands on LitSearch gold — offline.

Input: the engine tree's ranklab pools (per-question candidate pools with
gold ids; built once by bench_ranklab.py from on-disk caches, zero API).
Objective, honest and well-defined without labeling non-gold records:

* a question's GOLD paper(s) must land in core ∪ uncertain (a gold binned
  likely_off is a MISS — the agent would batch-review that band last);
* core should stay SMALL (core ∪ uncertain is the agent's careful-reading
  burden — that is the whole point of triage).

Sweeps (core_t, off_t) over a grid using the production channel code
(citens.screening: BM25 + local bge embedding, same weights/normalization,
consensus absent as in single-leg pools) and reports the frontier plus the
current defaults' position. Writes a JSON artifact next to itself.

Usage:
    .venv/Scripts/python tools/calibrate_screen.py --pools <ranklab_pools.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from citens.config import settings
from citens.screening import (
    _EMB_TEXT_MAX,
    _W_WITH_SEM,
    bm25_scores,
    embed_local,
)


def _gold_set(entry: dict) -> set[str]:
    """Gold identities as normalized titles (the pools carry no S2 ids)."""
    out = set()
    for g in entry.get("golds") or []:
        t = (g.get("title") if isinstance(g, dict) else g) or ""
        out.add(" ".join(t.lower().split()))
    return out


def _key(title: str) -> str:
    return " ".join((title or "").lower().split())


def score_pool(entry: dict, model_name: str) -> list[dict] | None:
    """Production-faithful composite scores for one question's pool.

    Same channels/weights as screen_papers: semantic cosine (0.6) + BM25
    pool-normalized (0.2); consensus absent (single-leg pools) so the
    composite renormalizes exactly like _W_WITH_SEM minus consensus.
    """
    pool = entry.get("pool") or []
    if not pool:
        return None
    query = entry["query"]
    texts = [
        f"{p.get('title', '')}. {(p.get('abstract') or '')[:_EMB_TEXT_MAX]}".strip()
        for p in pool
    ]
    golds = _gold_set(entry)
    raw = bm25_scores(texts, query)
    mx = max(raw) if raw else 0.0
    lex = [r / mx if mx > 0 else 0.0 for r in raw]
    sem_vecs = embed_local(texts, model_name)
    qv = embed_local([query], model_name)
    rows: list[dict] = []
    for i, p in enumerate(pool):
        sem = None
        if sem_vecs is not None and qv is not None:
            v, q = sem_vecs[i], qv[0]
            sem = max(sum(a * b for a, b in zip(v, q, strict=False)), 0.0)
        channels: dict[str, float] = {}
        if sem is not None:
            channels["semantic"] = sem
        channels["lexical"] = lex[i]
        wsum = sum(_W_WITH_SEM.get(c, 0.0) for c in channels)
        score = sum(_W_WITH_SEM.get(c, 0.0) * v for c, v in channels.items()) / wsum
        rows.append({
            "title": p.get("title", ""),
            "is_gold": _key(p.get("title", "")) in golds,
            "score": score,
            "sem": sem,
            "lex": lex[i],
        })
    return rows


def evaluate(grid_rows: list[list[dict]], core_t: float, off_t: float) -> dict:
    misses = 0
    gold_in_core = 0
    total_gold = 0
    burden_core = burden_band = 0
    total = 0
    for rows in grid_rows:
        n = len(rows)
        total += n
        golds = [r for r in rows if r["is_gold"]]
        total_gold += len(golds)
        binned = {}
        for r in rows:
            band = "core" if r["score"] >= core_t else (
                "likely_off" if r["score"] < off_t else "uncertain")
            banded = binned.setdefault(_key(r["title"]), band)
            # a gold is only safely binned if EVERY duplicate lands safe
            if r["is_gold"] and (band == "likely_off" or banded == "likely_off"):
                binned[_key(r["title"])] = "likely_off"
        for r in rows:
            if r["score"] >= core_t:
                burden_core += 1
            elif r["score"] >= off_t:
                burden_band += 1
        for g in golds:
            band = binned[_key(g["title"])]
            if band == "likely_off":
                misses += 1
            elif band == "core":
                gold_in_core += 1
    return {
        "core_t": core_t,
        "off_t": off_t,
        "gold_missed": misses,               # gold binned likely_off
        "gold_total": total_gold,
        "gold_in_core": gold_in_core,
        "core_size_avg": round(burden_core / len(grid_rows), 1),
        "uncertain_size_avg": round(burden_band / len(grid_rows), 1),
        "pool_size_avg": round(total / len(grid_rows), 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pools", required=True, help="ranklab_pools.json (engine bench artifact)")
    ap.add_argument("--model", default=settings.screen_embedding_model)
    ap.add_argument("--out", default=str(Path(__file__).parent / "results" / "calibration_screen.json"))
    args = ap.parse_args()

    entries = json.loads(Path(args.pools).read_text(encoding="utf-8"))
    print(f"questions: {len(entries)} | model: {args.model}")
    grid_rows: list[list[dict]] = []
    skipped = 0
    for e in entries:
        rows = score_pool(e, args.model)
        if rows is None or not any(r["is_gold"] for r in rows or []):
            skipped += 1
            continue
        grid_rows.append(rows)
    print(f"scored pools: {len(grid_rows)} (skipped {skipped}: empty pool or gold "
          f"absent from pool — the recall leg's own misses, not a banding question)")

    results = []
    for core_t in [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]:
        for off_t in [0.1, 0.15, 0.2, 0.25, 0.3, 0.32, 0.35, 0.4]:
            if off_t >= core_t:
                continue
            results.append(evaluate(grid_rows, core_t, off_t))

    # frontier: zero gold misses, then smallest core; ties -> smaller uncertain
    zero_miss = [r for r in results if r["gold_missed"] == 0]
    best = sorted(zero_miss or results,
                  key=lambda r: (r["core_size_avg"], r["uncertain_size_avg"]))[:8]
    current = evaluate(grid_rows, settings.screen_core_threshold,
                       settings.screen_off_threshold)
    min_miss = min(r["gold_missed"] for r in results)

    print("\n== frontier (fewest misses, smallest core) ==")
    for r in best:
        print(f"  core_t={r['core_t']:.2f} off_t={r['off_t']:.2f} | "
              f"miss {r['gold_missed']}/{r['gold_total']} | gold-in-core {r['gold_in_core']} | "
              f"core {r['core_size_avg']:.0f}/pool {r['pool_size_avg']:.0f} | "
              f"uncertain {r['uncertain_size_avg']:.0f}")
    print(f"\ncurrent defaults ({settings.screen_core_threshold}/"
          f"{settings.screen_off_threshold}): "
          f"miss {current['gold_missed']}/{current['gold_total']}, "
          f"core {current['core_size_avg']:.0f}, uncertain {current['uncertain_size_avg']:.0f}")
    print(f"minimum misses achievable on this set: {min_miss}")

    Path(args.out).write_text(json.dumps({
        "n_questions": len(grid_rows),
        "skipped": skipped,
        "model": args.model,
        "frontier": best,
        "current_defaults": current,
        "all": results,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
