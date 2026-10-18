#!/usr/bin/env python
"""bench_screen.py — measure the `screen` triage lever on the LitSearch bench.

The question this answers: on a FIXED candidate pool, does the screen scoring
(semantic / lexical / consensus channels) move gold papers UP compared with
the pool builder's own order (family seat / global RRF)?

Arms and their pools (read this before quoting a number)
--------------------------------------------------------
The recall phase is cached per question in ``bench_results/cells.json``:
the engine's FROZEN planned keyword queries (gen_cache.json — zero LLM at
bench time) plus the raw question, 4 sources × depth 20.

    arm            candidate set                    what it measures
    ------------   ------------------------------   ------------------------------
    firstwins      agent+raw seat-quota pool        the 2-family baseline shape
                   (30 seats, 19–60 papers)         (NOT the package's 7-family
                                                    `search`; see caveat C1)
    screen_lex     same quota pool                  BM25 + votes re-ordering
    screen_full    same quota pool                  full screen re-ordering
    sem_only       same quota pool                  semantic channel attribution
    rrf_global     union of all cells (19–195)      global RRF over the union
    screen_union   same union                       screen over the same union
    driver7        the repo's actual recall leg     7-family end-to-end arm
                   (opt-in --driver-arm, live)     (needs network/API keys)

So ``firstwins`` vs ``screen_full`` is a same-pool comparison; ``rrf_global``
vs ``screen_union`` is a same-union comparison. The headline in the 0.2.0
release compared ``firstwins`` (2-family pool) against ``screen_union`` (a
larger union): different candidate sets, so it is NOT "only ordering differs".
Both same-pool pairs are reported below, with paired tests.

Sample: the frozen gen-cache questions are the engine's seed-42 stratified
15-question sample (2/6/4/3 over the four query sets) — the sample behind the
engine's published recall@20=33.3% adaptive-leg number. It is a reused
development sample, not held out. ``--all-questions`` runs every LitSearch
question with the raw family only (the planner cache only exists for the 15),
which is the full-set capability this repo can offer offline-cached.

Statistics: n is tiny (15 questions, ~1 gold each). Every summary carries a
Wilson 95% interval; paired comparisons carry an exact McNemar p (binary
hit@k) and a paired-bootstrap 95% interval for the mean difference. Do not
call a delta "significant" when the interval crosses 0.

Data: bench_data/litsearch/ + bench_results/gen_cache.json — gitignored;
point --data/--gen at the engine repo's copies. pyarrow is needed for the
parquet read (not a runtime dependency of the package).

Run from the repo root:
  .venv/Scripts/python bench/bench_screen.py \
      --data <engine>/bench_data/litsearch --gen <engine>/bench_results/gen_cache.json \
      [--env <citlens home>/.env] [--driver-arm] [--all-questions]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import random
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from citens.eval.litsearch import fuse_multi_query, search_one_query  # noqa: E402
from citens.models import Paper  # noqa: E402
from citens.search.base import paper_arxiv_id  # noqa: E402
from citens.screening import screen_papers  # noqa: E402

SOURCES = ["arxiv", "semantic_scholar", "openalex", "crossref"]
PER_SOURCE = 20
FAMILY_QUOTA = 30
MODEL_DEFAULT = "BAAI/bge-base-en-v1.5"
CELL_ARMS = ["firstwins", "rrf_global", "screen_lex", "screen_full", "sem_only",
             "screen_union"]


def _log(msg: str) -> None:
    print(f"[bench] {msg}", flush=True)


# --- gold matching (ported verbatim from the engine's eval/litsearch.py) ------


def _norm_doi(doi: str | None) -> str:
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", (doi or "").strip().lower())


def _title_tokens(title: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (title or "").lower()) if len(t) > 2}


def match_gold(paper: Paper, golds: list[dict]) -> bool:
    pdoi = _norm_doi(paper.doi)
    parx = paper_arxiv_id(paper)
    ptok = _title_tokens(paper.title)
    for g in golds:
        if pdoi and g.get("doi") and pdoi == _norm_doi(g["doi"]):
            return True
        if parx and g.get("arxiv") and g["arxiv"] == parx:
            return True
        gtok = _title_tokens(g.get("title", ""))
        if len(ptok) >= 3 and len(gtok) >= 3 and ptok == gtok:
            return True
    return False


def first_gold_rank(ordered: list[Paper], golds: list[dict]) -> int | None:
    for i, p in enumerate(ordered, 1):
        if match_gold(p, golds):
            return i
    return None


def gold_hits_at(ordered: list[Paper], golds: list[dict], k: int) -> float:
    """Recall@k over the question's golds (each gold counted once)."""
    if not golds:
        return 0.0
    matched = 0
    for g in golds:
        if any(match_gold(p, [g]) for p in ordered[:k]):
            matched += 1
    return matched / len(golds)


# --- cells (network, cached) ---------------------------------------------------


def _load_cells(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


async def _cell(query: str, cells_cache: dict, path: Path) -> dict[str, list[Paper]]:
    if query in cells_cache:
        return {
            s: [Paper(**p) for p in lst]
            for s, lst in cells_cache[query].items()
        }
    _log(f"  fetch cells: {query[:70]}")
    health: dict[str, list[int]] = {}
    got = await search_one_query(query, SOURCES, per_source=PER_SOURCE, health_out=health)
    failed = [s for s, b in health.items() if b[2] > 0]
    if failed:
        # a throttled source must not bake partial results into the cache —
        # leave uncached so the next run retries the query
        _log(f"    source failures, cell NOT cached (retried next run): {failed}")
        return got
    cells_cache[query] = {s: [p.model_dump() for p in lst] for s, lst in got.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cells_cache, ensure_ascii=False), encoding="utf-8")
    return got


def _first_wins(families: list[list[Paper]]) -> list[Paper]:
    """Seat-quota merge, first family wins ties (the recall driver's shape)."""
    pool, seen = [], set()
    for fam in families:
        for p in fam[:FAMILY_QUOTA]:
            k = _fuse_key(p)
            if k not in seen:
                seen.add(k)
                pool.append(p)
    return pool


def _fuse_key(p: Paper) -> str:
    from citens.eval.litsearch import _key_of

    return _key_of(p)


def _row_key(r: dict) -> str:
    return ("d:" + _norm_doi(r.get("doi"))) if r.get("doi") else (
        "t:" + " ".join(sorted(_title_tokens(r.get("title", ""))))
    )


# --- statistics -----------------------------------------------------------------


def wilson_ci(k: int, n: int, z: float = 1.96) -> list[float]:
    """Wilson score interval for a proportion — the honest interval at n=15."""
    if n <= 0:
        return [0.0, 0.0]
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, center - half), 3), round(min(1.0, center + half), 3)]


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p over discordant pairs (binomial, p=0.5)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return round(min(1.0, 2 * tail), 4)


def paired_bootstrap(diffs: list[float], *, iters: int = 4000, seed: int = 17) -> list[float]:
    """95% percentile interval of the mean paired difference."""
    if not diffs:
        return [0.0, 0.0]
    rng = random.Random(seed)
    n = len(diffs)
    means = []
    for _ in range(iters):
        means.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return [round(means[int(0.025 * iters)], 3), round(means[int(0.975 * iters) - 1], 3)]


def paired_compare(per_q: list[dict], arm_a: str, arm_b: str) -> dict:
    """Paired comparison of arm_b against arm_a over the same questions.

    Binary hit@k feeds the McNemar test; the fractional recall/MRR deltas get
    a paired-bootstrap interval. ``pooling`` is derived from the arm names so
    a cross-pool comparison is never presented as a pure ordering effect.
    """
    union_arms = {"rrf_global", "screen_union"}
    a_union, b_union = arm_a in union_arms, arm_b in union_arms
    pooling = "same-pool" if a_union == b_union else "DIFFERENT pools"
    out: dict = {"arms": [arm_a, arm_b], "n": len(per_q), "pooling": pooling}
    for metric in ("r5", "r20", "mrr100"):
        diffs = [q[arm_b][metric] - q[arm_a][metric] for q in per_q
                 if arm_a in q and arm_b in q]
        out[metric] = {
            "mean_delta": round(sum(diffs) / len(diffs), 3) if diffs else 0.0,
            "bootstrap_95": paired_bootstrap(diffs),
        }
    for metric in ("r5", "r20"):
        b = sum(1 for q in per_q
                if q[arm_a][metric] <= 0 < q[arm_b][metric])
        c = sum(1 for q in per_q
                if q[arm_b][metric] <= 0 < q[arm_a][metric])
        out[f"mcnemar_{metric}"] = {"b": b, "c": c, "p_exact": mcnemar_exact(b, c)}
    return out


# --- optional live 7-family arm --------------------------------------------------


def _driver_pool(question: str, planned: list[str], cache_root: Path) -> list[Paper]:
    """Run the repo's actual recall leg for one question (cached on disk).

    This is the end-to-end arm: it exercises the seven families the package
    ships (agent/raw/s2_rec/snowball/survey; title/web need their own inputs
    and are therefore skipped unless the caller supplies them). Costly — it
    hits the live sources — so results are cached per question and reused.
    """
    key = hashlib.sha1((question + "\x1f" + "\x1f".join(planned)).encode("utf-8")).hexdigest()[:16]
    cache = cache_root / f"{key}.json"
    if cache.is_file():
        try:
            return [Paper(**p) for p in json.loads(cache.read_text(encoding="utf-8"))]
        except Exception:  # noqa: BLE001
            pass
    cwd = cache_root / f"run-{key}"
    cwd.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(ROOT / "drivers" / "citlens_recall.py"),
           "--topic", question, "--target", "0", "--out", str(cwd)]
    if planned:
        cmd += ["--queries", *planned]
    env = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    import os

    env = {**os.environ, **env}
    _log(f"  driver7 live run: {question[:60]}")
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=1800, env=env)
    except Exception as e:  # noqa: BLE001
        _log(f"    driver7 failed: {e}")
        return []
    if proc.returncode != 0:
        _log(f"    driver7 failed (exit {proc.returncode}): {(proc.stderr or '')[-300:]}")
        return []
    runs = sorted(cwd.glob("*-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        return []
    pool_file = runs[0] / "pool.jsonl"
    if not pool_file.is_file():
        return []
    papers: list[Paper] = []
    for line in pool_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            papers.append(Paper(**json.loads(line)))
        except Exception:  # noqa: BLE001
            continue
    cache.write_text(json.dumps([p.model_dump() for p in papers], ensure_ascii=False),
                     encoding="utf-8")
    return papers


# --- the bench ------------------------------------------------------------------


def run(
    data_dir: Path,
    gen_cache_path: Path,
    n: int,
    model: str,
    out_dir: Path,
    results_dir: Path,
    *,
    all_questions: bool = False,
    driver_arm: bool = False,
) -> int:
    import pyarrow.parquet as pq

    rows = pq.read_table(str(data_dir / "query.parquet")).to_pylist()
    gold_all = json.loads((data_dir / "gold_papers.json").read_text(encoding="utf-8"))
    gen = json.loads(gen_cache_path.read_text(encoding="utf-8"))
    # frozen planner generations: prefer the newest cache version per question
    planned_by_q: dict[str, list[str]] = {}
    for k, v in gen.items():
        parts = k.split(":planned:", 1)
        if len(parts) == 2 and v:
            q = parts[1]
            ver = int(parts[0]) if parts[0].isdigit() else 0
            cur = planned_by_q.get(q + "#ver")
            if q not in planned_by_q or (isinstance(cur, int) and ver > cur):
                planned_by_q[q] = v
                planned_by_q[q + "#ver"] = ver  # type: ignore[assignment]
    vers = {k: planned_by_q.pop(k) for k in list(planned_by_q) if k.endswith("#ver")}

    if all_questions:
        qs = list(rows)
        qs.sort(key=lambda r: (r["query_set"], r["query"]))
    else:
        qs = [r for r in rows if r["query"] in planned_by_q]
        qs.sort(key=lambda r: (r["query_set"], r["query"]))
        if n and n < len(qs):
            qs = qs[:n]
    if not qs:
        _log("no questions selected")
        return 1
    _log(f"{len(qs)} questions ({dict(Counter(r['query_set'] for r in qs))}), "
         f"gen versions {sorted(set(vers.values()))}, "
         f"all_questions={all_questions} driver_arm={driver_arm}")

    manifest = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "questions": [{"set": r["query_set"], "query": r["query"]} for r in qs],
        "n": len(qs),
        "all_questions": all_questions,
        "driver_arm": driver_arm,
        "model": model,
        "sources": SOURCES,
        "per_source": PER_SOURCE,
        "query_parquet_sha256": hashlib.sha256(
            (data_dir / "query.parquet").read_bytes()).hexdigest(),
        "gen_cache_sha256": hashlib.sha256(gen_cache_path.read_bytes()).hexdigest(),
        "caveats": [
            "frozen-planner sample: reused development set, not held out",
            "agent+raw cells only for the cell arms; the driver7 arm runs the shipped leg",
            "n≈15 with ~1 gold/question: each point is a 1/15 step",
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = results_dir / "manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    cells_path = out_dir / "cells.json"
    cells_cache = _load_cells(cells_path)
    driver_cache = out_dir / "driver_cache"
    driver_cache.mkdir(parents=True, exist_ok=True)

    arms = list(CELL_ARMS)
    if driver_arm:
        arms.append("driver7")
    agg: dict[str, Counter] = {a: Counter() for a in arms}
    per_q: list[dict] = []
    driver_family_counts: dict[str, int] = {}

    t0 = time.time()
    for qi, row in enumerate(qs, 1):
        question = row["query"]
        golds = [gold_all[str(c)] for c in row["corpusids"] if str(c) in gold_all]
        planned = planned_by_q.get(question, [])[:3] if not all_questions else []
        queries = [*planned, question]
        _log(f"[{qi}/{len(qs)}] ({row['query_set']}) {question[:80]}")

        cell_maps: dict[str, dict[str, list[Paper]]] = {}
        for q in queries:
            cell_maps[q] = asyncio.run(_cell(q, cells_cache, cells_path))
            time.sleep(0.3)  # polite spacing between query fan-outs

        fam_agent = fuse_multi_query({q: cell_maps[q] for q in planned}, SOURCES) if planned else []
        fam_raw = fuse_multi_query({question: cell_maps[question]}, SOURCES)
        pool = _first_wins([fam_agent, fam_raw] if fam_agent else [fam_raw])
        if not pool:
            _log("  empty pool — skipped")
            continue
        votes: dict[str, set[str]] = {}
        for name, fam in (("agent", fam_agent), ("raw", fam_raw)):
            for p in fam[:FAMILY_QUOTA]:
                votes.setdefault(_fuse_key(p), set()).add(name)
        for p in pool:
            p.found_by = sorted(votes.get(_fuse_key(p), set()))

        screen_full = screen_papers(pool, queries, model=model, limit=len(pool))
        lex_rows = screen_papers(pool, queries, model="", limit=len(pool))
        by_key = {_fuse_key(p): p for p in pool}
        # union view: every distinct paper the cells returned (target=0 shape).
        # The quota pool is the production default; the union answers "does
        # screening also RESCUE golds the seat cut removed" — rrf_global sees
        # those golds, so screening deserves the same wider stage.
        union: dict[str, Paper] = {}
        for cells in cell_maps.values():
            for lst in cells.values():
                for p in lst:
                    union.setdefault(_fuse_key(p), p)
        union_list = list(union.values())
        for name, fam in (("agent", fam_agent), ("raw", fam_raw)):
            for p in fam:
                votes.setdefault(_fuse_key(p), set()).add(name)
        for p in union_list:
            p.found_by = sorted(votes.get(_fuse_key(p), set()))
        screen_union = screen_papers(union_list, queries, model=model, limit=len(union_list))
        u_by_key = {_fuse_key(p): p for p in union_list}
        orders: dict[str, list[Paper]] = {
            "firstwins": pool,
            "rrf_global": fuse_multi_query(cell_maps, SOURCES),
            "screen_lex": [by_key[_row_key(r)] for r in lex_rows["papers"]],
            "screen_full": [by_key[_row_key(r)] for r in screen_full["papers"]],
            "sem_only": [by_key[_row_key(r)] for r in
                         sorted(screen_full["papers"],
                                key=lambda r: -(r["channels"].get("semantic") or -1))],
            "screen_union": [u_by_key[_row_key(r)] for r in screen_union["papers"]],
        }
        if driver_arm:
            d7 = _driver_pool(question, planned, driver_cache)
            if d7:
                orders["driver7"] = d7
                for p in d7:
                    for fam in (p.found_by or []):
                        driver_family_counts[fam] = driver_family_counts.get(fam, 0) + 1

        qres: dict = {"question": question, "set": row["query_set"],
                      "pool": len(pool), "union": len(union_list), "golds": len(golds)}
        for arm, ordered in orders.items():
            rank = first_gold_rank(ordered, golds)
            qres[arm] = {
                "in_pool": rank is not None,
                "first_rank": rank,
                "r5": gold_hits_at(ordered, golds, 5),
                "r10": gold_hits_at(ordered, golds, 10),
                "r20": gold_hits_at(ordered, golds, 20),
                "mrr100": (1.0 / rank) if rank and rank <= 100 else 0.0,
            }
            a = agg[arm]
            a["n"] += 1
            a["in_pool"] += int(qres[arm]["in_pool"])
            a["r5"] += qres[arm]["r5"]
            a["r10"] += qres[arm]["r10"]
            a["r20"] += qres[arm]["r20"]
            a["mrr100"] += qres[arm]["mrr100"]
        per_q.append(qres)
        b = qres["firstwins"]
        f = qres["screen_full"]
        _log(f"  pool {len(pool)} | gold in pool: {b['in_pool']} | "
             f"firstwins r20 {b['r20']:.2f} rank {b['first_rank']} -> "
             f"screen_full r20 {f['r20']:.2f} rank {f['first_rank']}")

    n_q = len(per_q)
    summary: dict = {}
    for arm, c in agg.items():
        hits5 = sum(1 for q in per_q if q[arm]["r5"] > 0)
        hits20 = sum(1 for q in per_q if q[arm]["r20"] > 0)
        summary[arm] = {
            "n": c["n"],
            "in_pool%": round(100 * c["in_pool"] / max(c["n"], 1), 1),
            "recall@5": round(c["r5"] / max(c["n"], 1), 3),
            "recall@10": round(c["r10"] / max(c["n"], 1), 3),
            "recall@20": round(c["r20"] / max(c["n"], 1), 3),
            "MRR@100": round(c["mrr100"] / max(c["n"], 1), 3),
            "recall@5_wilson95": wilson_ci(hits5, n_q),
            "recall@20_wilson95": wilson_ci(hits20, n_q),
        }

    comparisons = []
    for a, b in (("firstwins", "screen_union"), ("rrf_global", "screen_union"),
                 ("firstwins", "screen_full")):
        if a in summary and b in summary:
            comparisons.append(paired_compare(per_q, a, b))
    if driver_arm and "driver7" in summary:
        comparisons.append(paired_compare(per_q, "driver7", "screen_union"))

    summary["_comparisons"] = comparisons
    summary["_meta"] = {
        "questions": n_q,
        "all_questions": all_questions,
        "driver_arm": driver_arm,
        "driver_family_votes": driver_family_counts,
        "manifest": str(manifest_path),
        "arm_pools": {
            "firstwins": "agent+raw seat-quota pool (2-family baseline; not the shipped 7-family search)",
            "screen_lex": "same quota pool",
            "screen_full": "same quota pool",
            "sem_only": "same quota pool",
            "rrf_global": "union of all query×source cells",
            "screen_union": "same union",
            "driver7": "the repo's recall leg end-to-end (opt-in, live)",
        },
    }

    ts = time.strftime("%Y%m%d_%H%M%S")
    payload = {"summary": summary, "per_question": per_q,
               "model": model, "sources": SOURCES,
               "elapsed_s": round(time.time() - t0)}
    (results_dir / f"bench_screen_{ts}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_md(results_dir / "bench_screen_latest.md", summary, per_q, model, n_q,
              all_questions, driver_arm)
    _log(f"done in {time.time() - t0:.0f}s -> {results_dir / 'bench_screen_latest.md'}")
    return 0


def _write_md(path: Path, summary: dict, per_q: list[dict], model: str, n_q: int,
              all_questions: bool, driver_arm: bool) -> None:
    meta = summary.get("_meta", {})
    hdr = "| arm | pool | gold in pool % | R@5 | R@10 | R@20 | MRR@100 |"
    sep = "|---|---|---|---|---|---|---|"
    lines = [
        "# bench: screen triage vs. pool order (LitSearch)",
        "",
        f"- questions: {n_q}" + (" (ALL LitSearch questions; raw family only — the "
                                "frozen planner cache exists only for the engineered sample)"
                                if all_questions else
                                " (the engine's frozen seed-42 stratified sample behind the "
                                "published adaptive-leg recall@20=33.3%; a reused development "
                                "sample, not held out)"),
        f"- sources: {', '.join(SOURCES)} × depth {PER_SOURCE} · cell arms: agent(planned, "
        "frozen) + raw",
        f"- semantic model: {model}",
        f"- driver7 arm: {'on (live 7-family recall leg, cached)' if driver_arm else 'off'}",
        "",
        "## arm → candidate pool (READ THIS BEFORE QUOTING A DELTA)",
        "",
        "| arm | candidate set |",
        "|---|---|",
        "| firstwins | agent+raw seat-quota pool (30 seats, 2-family baseline — NOT the shipped 7-family search) |",
        "| screen_lex / screen_full / sem_only | the SAME quota pool, re-ordered |",
        "| rrf_global | union of all query×source cells |",
        "| screen_union | the SAME union, re-ordered |",
        "| driver7 | the repo's recall leg end-to-end (opt-in) |",
        "",
        "So `firstwins` vs `screen_full` is same-pool; `rrf_global` vs `screen_union` is "
        "same-union; `firstwins` vs `screen_union` is a DIFFERENT-pool comparison (the union "
        "is larger). The 0.2.0 headline used that cross-pool pair.",
        "",
        hdr, sep,
    ]
    pools = meta.get("arm_pools", {})
    for arm, s in summary.items():
        if arm.startswith("_"):
            continue
        lines.append(
            f"| {arm} | {pools.get(arm, '')} | {s['in_pool%']} | {s['recall@5']} "
            f"| {s['recall@10']} | {s['recall@20']} | {s['MRR@100']} |"
        )
    lines += ["", "## uncertainty (95% Wilson interval; n is tiny — do not over-read)", ""]
    for arm, s in summary.items():
        if arm.startswith("_"):
            continue
        lines.append(
            f"- **{arm}**: R@5 {s['recall@5']} {s.get('recall@5_wilson95')} · "
            f"R@20 {s['recall@20']} {s.get('recall@20_wilson95')}"
        )
    comps = summary.get("_comparisons") or []
    if comps:
        lines += ["", "## paired comparisons (exact McNemar on hits; bootstrap on deltas)", "",
                  "| A → B | pooling | ΔR@5 [95%] | ΔR@20 [95%] | ΔMRR [95%] | McNemar R@20 p |",
                  "|---|---|---|---|---|---|"]
        for c in comps:
            a, b = c["arms"]
            m = c["mcnemar_r20"]
            lines.append(
                f"| {a} → {b} | {c['pooling']} | "
                f"{c['r5']['mean_delta']} {c['r5']['bootstrap_95']} | "
                f"{c['r20']['mean_delta']} {c['r20']['bootstrap_95']} | "
                f"{c['mrr100']['mean_delta']} {c['mrr100']['bootstrap_95']} | "
                f"b={m['b']}, c={m['c']}, p={m['p_exact']} |"
            )
        lines += ["", "A bootstrap interval that crosses 0 (or a McNemar p above 0.05) "
                  "means the delta is not established at this sample size. The interval is "
                  "the honest statement, not the point estimate."]
    lines += ["", "## caveats", "",
              "1. The agent queries are the engine's FROZEN planner outputs — the bench is "
              "LLM-free at run time, but the planner quality came from the engine; it does "
              "not validate an agent as planner.",
              "2. The cell arms use only agent+raw of the seven shipped families; the "
              "driver7 arm is the end-to-end check (and is costly).",
              "3. 15 questions × ~1 gold = coarse recall; per-question ranks are in the "
              "table below and in the JSON so nothing is hidden.",
              "4. The thresholds/bands are not tuned here: the lever under test is the "
              "ORDER, not the cutoffs.",
              "",
              "## per question (gold first-rank; – = not in pool)", "",
              "| set | question (60c) | pool | firstwins | rrf | lex | full | sem | union |"
              + (" driver7 |" if driver_arm else ""),
              "|---|---|---|---|---|---|---|---|---|" + ("---|" if driver_arm else "")]
    for q in per_q:
        ranks = " | ".join(
            str(q[a]["first_rank"]) if q[a]["first_rank"] else "–"
            for a in ("firstwins", "rrf_global", "screen_lex", "screen_full",
                      "sem_only", "screen_union")
        )
        row = f"| {q['set']} | {q['question'][:60]} | {q['pool']} | {ranks} |"
        if driver_arm:
            d = q.get("driver7")
            row += f" {str(d['first_rank']) if d and d['first_rank'] else '–'} |"
        lines.append(row)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="LitSearch bench for the screen lever")
    ap.add_argument("--data", required=True, help="engine bench_data/litsearch dir (query.parquet, gold_papers.json)")
    ap.add_argument("--gen", required=True, help="engine bench_results/gen_cache.json (frozen planner queries)")
    ap.add_argument("--env", default="", help="optional .env to load (keys raise rate limits only)")
    ap.add_argument("--n", type=int, default=0, help="cap questions when using the frozen sample (0 = all of it)")
    ap.add_argument("--all-questions", action="store_true",
                    help="run every LitSearch question (raw family only: no frozen planner cache outside the sample)")
    ap.add_argument("--driver-arm", action="store_true",
                    help="also run the repo's 7-family recall leg end-to-end per question (live, cached)")
    ap.add_argument("--model", default=MODEL_DEFAULT)
    ap.add_argument("--out", default="bench_results", help="cells/driver cache dir (gitignored)")
    ap.add_argument("--results", default=str(ROOT / "bench" / "results"))
    args = ap.parse_args()

    if args.env:
        for line in Path(args.env).read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*=\s*(.+)\s*$", line)
            if m and m.group(1) not in ("LLM_API_KEY", "LLM_MODEL"):
                os_setenv_safe(m.group(1), m.group(2).strip().strip('"').strip("'"))

    return run(
        Path(args.data), Path(args.gen), args.n, args.model,
        Path(args.out), Path(args.results),
        all_questions=args.all_questions,
        driver_arm=args.driver_arm,
    )


def os_setenv_safe(k: str, v: str) -> None:
    import os

    os.environ.setdefault(k, v)


if __name__ == "__main__":
    sys.exit(main())
