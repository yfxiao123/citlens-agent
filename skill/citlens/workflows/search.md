# 检索模块 — finding literature

The module for: *find papers on X*, *map this field*, *check what exists*,
*build me a reading list*. The deliverable is the pool, the coverage
numbers, and the evidence trail — not prose. When the numbers and the trail
are reported, this job is done (see 收工 below). Writing a survey or
answering a question are other modules ([review.md](review.md),
[answer.md](answer.md)) that start only when the user asks for them.

This file assumes the shared core in [../SKILL.md](../SKILL.md) (tools,
CLI surface, the one rule, discipline layers).

## Workflow — searching

1. **`doctor` first** when anything looks wrong (or on a new machine). It
   tells you whether a failure is the tool's environment or the retrieval.

2. **Craft the queries — you are the planner.** Before calling `search`,
   decompose the topic PRESS-style:
   - Identify 4-6 **concept blocks**: the central concept, its neighbouring
     mechanisms/method families, the task/domain, the constraint or
     evaluation dimension.
   - For each block write 2-4 **English synonyms** (the vocabulary papers
     actually use — British/US spellings, acronym/expansion pairs).
   - Build **combination queries first**: multi-block conjunctions that name
     the specific intersection ("entity-level factual consistency abstractive
     summarization"), then single-block coverage queries. Combination-first
     is the measured fix — head-first broad queries picked only coverage.
     But NEVER let the conjunction grow long: a 7-block AND-conjunction
     missed a bench gold that a 3-block query ranked #1 (measured
     2026-11-06) — each extra block ANDs away records whose titles don't
     carry that token. Two to three blocks is the sweet spot.
   - **Restate before you query** (misread guard): restate the question in
     one sentence of your own and check you did not misread it ("performance
     decline in various LANGUAGES" is not about quantization — a real bench
     misread that no retrieval could fix).
   - Climb the **register ladder** ALL the way: question words → field
     jargon → method names → task/dataset names → COMMUNITY names. The top
     rung is the one agents skip (measured 2026-11-06: a question phrased
     in NLP words whose gold lived in the HCI community — "inspiration for
     science writing", a CHI paper — was invisible to every NLP-register
     query; another gold framed as a GEN-task paper, "entity description
     generation", never matched any "error distribution for unfamiliar
     entities" synonym). When the ladder feels dry, ask WHICH community
     owns this task and what THEY would call it — then write one query and
     one title-probe in their framing words. Framing gaps are invisible to
     every in-pool mechanism (pivot only amplifies vocabulary already in
     the pool; the gold is not in the pool); only out-of-register words or
     citation-graph `expand` can cross them.
   - **Scout before you search** (vocabulary reconnaissance — mine the
     FIELD's words, don't guess from the question). Every query word
     written before seeing the corpus comes only from your own head, and
     the field's framing words may not be in it. Protocol:
     1. **Split the question into 2-3 content blocks** (noun blocks, not
        sentences): "language models" + "factual errors" + "entities".
     2. **Broad scout, SMALL target (20-30)**: pair the blocks into
        two-block queries. One guessed-ideal-title probe alongside is
        cheap.
     3. **Harvest from the papers, four buckets**: task names (the coinage
        the field uses, e.g. "entity description generation"), method /
        metric names, dataset names, and the COMMUNITY signal (venues of
        the hits: ACL-heavy vs CHI-heavy answers "which community owns
        this"). If the community looks foreign, run ONE more scout in
        their language ("creativity support" surfaced the CHI line whose
        ancestor was the gold, one citation hop away).
     4. **Craft the formal set with harvested words** — combination
        queries from task+method names, one query per detected community,
        title probes carrying the coinages — then `search` with
        `append_pool` true. `--pivot 2` adds the mechanical harvest on
        top (terms the corroborated head actually uses); your reading is
        the semantic layer it cannot do.
     Cost: one or two small searches. The last hop for
     community-coinage golds is usually `expand` off a framing sibling,
     not any query.
   - Pass them all as `queries` (they become the `agent` family, the
     highest-recall leg). Optionally:
     - `title_probes`: 2-3 **HyDE-style hypothetical titles** — write the
       title the ideal paper would carry, in PAPER-side vocabulary (method /
       dataset / task names), not question phrasing. This is the measured
       escape hatch for vocabulary mismatch: 71% of bench-missed golds share
       ≤2 content words with the question, so no query phrasing reaches
       them, but their own titles do. Anchor titles of known-canonical
       papers work too (max 3 used).
     - `web_queries`: for the web bridge, 2-3 English queries quoting the
       DISTINCTIVE verbatim wording of the question (the 4-8 words a generic
       paper would NOT share), plus 1-2 natural Chinese phrasings
       (Zhihu/CSDN style, not translations).
     - `policy_queries`: for macro/economics/policy topics, 2-3 PLAIN
       economist phrasings ("natural rate of interest estimates") feeding the
       policy corpus family — NBER working papers, Fed Board FEDS Notes and
       working papers, IMF. Plain wording, not ML-style concept blocks: these
       queries speak the economics the notes themselves use. The family is
       discipline-gated: without explicit `policy_queries` it runs only when
       the topic is detected as economics, so it never injects NBER records
       into a non-economics pool.
     - `pivot: 2` when the vocabulary is uncertain: after the first wave
       the driver builds 2 queries from the corroborated head's
       discriminative terms (LLM-free PRF local analysis — buys the
       on-topic seed that citation chaining needs). It skips itself when
       fewer than 3 cross-family-corroborated records exist, so it never
       drifts alone. Measured to rescue golds no hand-written variant
       reached.
3. **`search`** with `topic` + `queries`. Start with `wait_seconds` = 20 (the
   config default — you get the job_id early instead of a held shell; raise
   it for scripted runs that prefer to wait). A
   rich topic takes 2–6 minutes; if you get a `job_id`, poll `status` rather
   than starting a second search. Keep `append_pool` true so the shared pool
   grows. **Reuse the topic string byte-identically** across searches — pools
   are keyed by a slug of it.
4. **Read the evidence before you claim anything.** The result carries
   `artifacts.pool_jsonl`, `artifacts.search_report`, `artifacts.exclusions`
   and a `report_head`. Read `search_report.md` — it has per-family seat
   counts and per-source `ok / empty / failed` health. **A failed source is
   not a zero-hit source.** If `failed > 0`, say which source failed.
   **Check `query_feedback`** (also `weak_queries` in the tool result, and
   the 查询反馈 table in the report): every query's actual hit count with a
   verdict. empty/thin blocks are vocabulary mismatch — rephrase THAT block
   in paper-side vocabulary (method name / dataset name / task acronym) and
   search again with the fixed block; do not just re-run the same words.
5. **Triage, then judge relevance yourself.** The pool order is RRF/family-seat
   order, NOT a relevance ranking. Call `screen` with the SAME concept-block
   queries you gave `search`: it bands the pool into core / uncertain /
   likely_off on three mechanical channels (local embeddings, BM25,
   `found_by` family votes) and writes `screening.jsonl`. The bands are
   TRIAGE, not verdicts — never treat them as exclusions. Then read the
   core + uncertain records (title + abstract) carefully, bucket by
   concept-block coverage (a paper covering ZERO blocks is `off_topic`),
   and batch-review the likely_off band. Append every paper you screen OUT
   to the run's `exclusions.jsonl` with a reason code (`off_topic`,
   `wrong_subfield`, `duplicate`, `not_peer_reviewed`, ...) — PRISMA
   discipline, machine-written log. Report bands WITH their thresholds and
   which channels fired (they are heuristic defaults, uncalibrated).
   Deep-recall note (bench-measured): the target/seat cut removes golds
   screening would rank top — for review workflows search with
   `target: 0` (or screen the accumulated litdb pool) before screening.
5b. **Feed your judgments back — `expand`.** After reading the pool, take the
   records you judged genuinely on-topic (even 2-3 of them) and call
   `expand` with `topic` + `seeds` (their DOIs / arXiv ids / titles). It
   fetches their references (backward), their citers (forward), OpenAlex
   related works, and S2 recommendations — the neighborhood query
   vocabulary cannot name. Citation chaining is the strongest recall lever
   the bench knows: it reaches the 71% of golds that share ≤2 words with
   the question. The added records carry `found_by: ["expand"]` and are
   STILL UNJUDGED — screen and read them like any other addition. Iterate:
   judge the expansion's best hits → expand again from the new seeds
   (diminishing returns = saturation signal). Check `unresolved` in the
   result: a seed that did not resolve is a hint, not an error to hide.
   While you read, record verdicts with `notes` (core/uncertain/off + one
   line each) — the next `expand` can pass from_notes=core and seed from
   everything you already judged, and `dedup` before `export` keeps the
   bibliography free of preprint/published twins.
6. **`pool`** to iterate without re-searching: `min_citations`, `year_from`,
   `is_review: true` for surveys, `query` for a substring, `sort_by`. This
   reads disk; it never retrieves.
7. **Report numbers, not adjectives.** Kept count, pool size, year spread,
   missing DOI/venue counts, reviews found, and the health table. "Found 47
   papers" is weaker than "七家族共入池 49 → 保留 47，其中综述 9，无 DOI 2；
   web 家族因缺 SERPER_API_KEY 全部 failed".

**Policy corpus mechanics (macro/economics topics).** The `policy` family
pulls NBER working papers, Fed Board FEDS Notes plus the FEDS/IFDP
working-paper series, and IMF papers — mechanically, over Crossref DOI
prefixes, no scraping. It is discipline-gated (runs only for economics
topics or when you pass `policy_queries` explicitly), so a CRISPR or ML
topic never receives policy noise. Every pool record carries `doc_type`
(journal / preprint / working_paper / policy_note / report) and
`policy_org`, so journal evidence and the policy side can be read as two
perspectives on one question. Regional Fed banks, BIS and ECB deposit no
Crossref DOIs — for those, `web_queries` with site-scoped phrasings
("site:dallasfed.org working paper ...") is the documented route. The
target cut would normally drop policy records first (they seat after the
journal families); 8 policy seats are reserved through the cut, so a
default `target` search still returns them. For a policy-topic review,
still search with `target: 0`.

## Coverage discipline

High recall is not "enough results". Before telling a user a field is
covered, check the shapes that are cheap to check:

- **Anchors.** The most-cited works on the topic should be in the pool. If a
  famous survey or the canonical paper is missing, the search is not done —
  re-`search` with differently-phrased queries, or probe its title via
  `title_probes`.
- **Surveys.** `pool` with `is_review: true`. A field with zero surveys in a
  large pool usually means the survey family missed, not that no surveys
  exist.
- **Time.** `pool` returns `by_year`. A pool that stops at 2021 is stale, not
  complete; sources drift.
- **Saturation.** If a second differently-phrased search adds almost nothing
  new, that is evidence of saturation. Say "no new distinct records on the
  second phrasing" rather than "exhaustive".
- **Audit.** `audit` measures pool coverage of the top surveys'
  bibliographies — the cheapest external recall anchor. Surveys are anchored
  by the indexer's `is_review` flag OR a title that declares survey/review/
  overview/meta-analysis (the flag alone missed most real surveys). Low
  coverage or `reviews_checked = 0` means keep searching, not conclude;
  `reviews_available` shows whether the pool even contains an anchor.

Never present a subset as the whole field. If you filtered the pool (as the
user asked), say what the filter was and what it removed.

## 检索模块收工

Before declaring a find-papers job finished:

1. **Anchor verification**: `audit` the topic; report coverage. Missing
   anchors = not done.
2. **Saturation**: one differently-phrased search; report the delta.
3. **Health**: report per-source ok/empty/failed from the last search
   report; failed sources are named, never hidden.
4. **Stop at the deliverable.** The pool, the numbers, the evidence trail —
   delivered. Do not start writing a survey or an essay from them: that is
   a different module and it opens only when the user asks for it. If the
   reading itself is the deliverable, hand over the core list (titles +
   why-core in one line each) — still numbers-first, still no survey.
