# bench/ — measurement artifacts

## bench_screen.py — the screen triage lever on LitSearch

Reproduce (data lives in the engine repo, gitignored here):

```
.venv/Scripts/python bench/bench_screen.py \
  --data <engine>/bench_data/litsearch \
  --gen  <engine>/bench_results/gen_cache.json \
  --env  <citlens home>/.env        # optional, only raises rate limits
```

- Questions: the engine's frozen-planner set (15, stratified over the four
  LitSearch query sets) — the same sample behind the published
  recall@20 = 33.3% adaptive-leg number, so the anchor is comparable.
- Recall phase (shared by every arm): agent family = the FROZEN planned
  keyword queries (zero LLM at bench time) + raw family = question verbatim;
  4 sources x depth 20. Cells cached in `bench_results/cells.json` — reruns
  are deterministic and offline.
- Arms order the SAME candidates; only the ranking differs.

### Results (bench/results/bench_screen_latest.md, 2026-10-18)

| arm | gold in pool % | R@5 | R@10 | R@20 | MRR@100 |
|---|---|---|---|---|---|
| firstwins (what `search` returns) | 13.3 | 0.067 | 0.067 | 0.067 | 0.020 |
| rrf_global | 33.3 | 0.000 | 0.067 | 0.067 | 0.013 |
| screen_lex (BM25+votes) | 13.3 | 0.067 | 0.067 | 0.067 | 0.035 |
| screen_full (pool, +embeddings) | 13.3 | 0.067 | 0.133 | 0.133 | 0.075 |
| sem_only (embeddings alone) | 13.3 | 0.133 | 0.133 | 0.133 | 0.056 |
| **screen_union (full union + embeddings)** | **33.3** | **0.267** | **0.267** | **0.333** | **0.178** |

Findings:

1. **The semantic channel is the lever.** Lexical+votes barely moves the
   baseline; embeddings alone already double R@5. On identical pools the
   full screen moves rank-22 golds to rank 1, and deep golds (RRF ranks
   52/69/81) to 1/4/3.
2. **screen over the full candidate union reaches R@20 = 33.3%** — the
   engine's full adaptive leg (nine families + LLM cascade rerank) measured
   the same number on this sample; this chain has no LLM anywhere.
3. **The seat/target cut destroys recall screening would rescue.** Golds
   visible to rrf_global (33.3% in-pool) but cut by family quotas fall to
   13.3% in the production pool shape. Practical rule: for review workflows,
   search with `target: 0` (or screen the accumulated litdb pool) rather
   than letting the truncation decide.

Caveats, stated plainly: n=15 with ~1 gold per question — each R@20 point is
a 1/15 step; the union arm scores a larger pool than the production quota
shape; thresholds/bands are not tuned (the lever under test is the ORDER,
not the cutoffs).
