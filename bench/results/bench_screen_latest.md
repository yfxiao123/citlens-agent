# bench: screen triage vs. pool order (LitSearch)

- questions: 15 (the engine's frozen seed-42 stratified sample behind the published adaptive-leg recall@20=33.3%; a reused development sample, not held out)
- sources: arxiv, semantic_scholar, openalex, crossref × depth 20 · cell arms: agent(planned, frozen) + raw
- semantic model: BAAI/bge-base-en-v1.5
- driver7 arm: off

## arm → candidate pool (READ THIS BEFORE QUOTING A DELTA)

| arm | candidate set |
|---|---|
| firstwins | agent+raw seat-quota pool (30 seats, 2-family baseline — NOT the shipped 7-family search) |
| screen_lex / screen_full / sem_only | the SAME quota pool, re-ordered |
| rrf_global | union of all query×source cells |
| screen_union | the SAME union, re-ordered |
| driver7 | the repo's recall leg end-to-end (opt-in) |

So `firstwins` vs `screen_full` is same-pool; `rrf_global` vs `screen_union` is same-union; `firstwins` vs `screen_union` is a DIFFERENT-pool comparison (the union is larger). The 0.2.0 headline used that cross-pool pair.

| arm | pool | gold in pool % | R@5 | R@10 | R@20 | MRR@100 |
|---|---|---|---|---|---|---|
| firstwins | agent+raw seat-quota pool (2-family baseline; not the shipped 7-family search) | 13.3 | 0.067 | 0.067 | 0.067 | 0.02 |
| rrf_global | union of all query×source cells | 33.3 | 0.0 | 0.067 | 0.067 | 0.013 |
| screen_lex | same quota pool | 13.3 | 0.067 | 0.067 | 0.067 | 0.035 |
| screen_full | same quota pool | 13.3 | 0.067 | 0.133 | 0.133 | 0.075 |
| sem_only | same quota pool | 13.3 | 0.133 | 0.133 | 0.133 | 0.056 |
| screen_union | same union | 33.3 | 0.267 | 0.267 | 0.333 | 0.178 |

## uncertainty (95% Wilson interval; n is tiny — do not over-read)

- **firstwins**: R@5 0.067 [0.012, 0.298] · R@20 0.067 [0.012, 0.298]
- **rrf_global**: R@5 0.0 [0.0, 0.204] · R@20 0.067 [0.012, 0.298]
- **screen_lex**: R@5 0.067 [0.012, 0.298] · R@20 0.067 [0.012, 0.298]
- **screen_full**: R@5 0.067 [0.012, 0.298] · R@20 0.133 [0.037, 0.379]
- **sem_only**: R@5 0.133 [0.037, 0.379] · R@20 0.133 [0.037, 0.379]
- **screen_union**: R@5 0.267 [0.109, 0.52] · R@20 0.333 [0.152, 0.583]

## paired comparisons (exact McNemar on hits; bootstrap on deltas)

| A → B | pooling | ΔR@5 [95%] | ΔR@20 [95%] | ΔMRR [95%] | McNemar R@20 p |
|---|---|---|---|---|---|
| firstwins → screen_union | DIFFERENT pools | 0.2 [-0.067, 0.467] | 0.267 [0.067, 0.467] | 0.158 [0.006, 0.346] | b=4, c=0, p=0.125 |
| rrf_global → screen_union | same-pool | 0.267 [0.067, 0.467] | 0.267 [0.067, 0.467] | 0.164 [0.018, 0.347] | b=4, c=0, p=0.125 |
| firstwins → screen_full | same-pool | 0.0 [-0.2, 0.2] | 0.067 [0.0, 0.2] | 0.055 [-0.025, 0.191] | b=1, c=0, p=1.0 |

A bootstrap interval that crosses 0 (or a McNemar p above 0.05) means the delta is not established at this sample size. The interval is the honest statement, not the point estimate.

## caveats

1. The agent queries are the engine's FROZEN planner outputs — the bench is LLM-free at run time, but the planner quality came from the engine; it does not validate an agent as planner.
2. The cell arms use only agent+raw of the seven shipped families; the driver7 arm is the end-to-end check (and is costly).
3. 15 questions × ~1 gold = coarse recall; per-question ranks are in the table below and in the JSON so nothing is hidden.
4. The thresholds/bands are not tuned here: the lever under test is the ORDER, not the cutoffs.

## per question (gold first-rank; – = not in pool)

| set | question (60c) | pool | firstwins | rrf | lex | full | sem | union |
|---|---|---|---|---|---|---|---|---|
| inline_acl | Can you point to studies or tasks focused on detecting patro | 48 | 4 | 9 | 33 | 8 | 2 | 12 |
| inline_acl | Where can I find a detailed discussion on automating the ass | 60 | 22 | 23 | 2 | 1 | 3 | 1 |
| inline_nonacl | Are there any studies on incorporating external commonsense  | 47 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates graph-based mo | 60 | – | 69 | – | – | – | 4 |
| inline_nonacl | Could you recommend research that evaluates the performance  | 59 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that examines how syntactic con | 57 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that investigates applying conv | 51 | – | – | – | – | – | – |
| inline_nonacl | Is there a study that investigates if large language models  | 48 | – | 81 | – | – | – | 3 |
| manual_acl | Is there a paper that shows that language models' error dist | 59 | – | – | – | – | – | – |
| manual_acl | Is there a paper that uses evolutionary algorithms and neura | 60 | – | 52 | – | – | – | 1 |
| manual_acl | Which paper studies the concept of enhancing the coverage of | 30 | – | – | – | – | – | – |
| manual_acl | Which work discusses an analysis of source and target contri | 19 | – | – | – | – | – | – |
| manual_iclr | Are there any papers that study whether you can identify if  | 47 | – | – | – | – | – | – |
| manual_iclr | Are there any papers that use a world model for planning to  | 30 | – | – | – | – | – | – |
| manual_iclr | What research first proposed a new kind of cascaded diffusio | 47 | – | – | – | – | – | – |