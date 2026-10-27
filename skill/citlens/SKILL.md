---
name: citlens
description: High-recall literature search and citation-grounded survey writing through the CiteLens MCP tools (server "citlens": search, pool, screen, expand, fetch, export, audit, verify, status, doctor). Use for any request to find papers, search the literature, map a research field, check coverage, find surveys on a topic, or write a literature review/survey with real citations. You are the planner and the judge: craft the English concept-block queries yourself and pass them to `search`; feed papers you judge on-topic back via `expand`; the tool handles the seven recall families, RRF fusion, citation snowball, survey harvest, full-text fetch, mechanical citation/verdict verification and BibTeX export. Do not substitute your own web search for it.
---

# CiteLens

`citlens` is a tool, not a prompt. The retrieval mechanics live in a Python
core running behind an MCP server; you call it and report what it returns.
That is the whole point: **the tool is what makes the search reproducible** —
two different agents calling `search` with the same queries get the same
pool, and an agent that searched can hand its pool to an agent that writes.

This build has **no LLM of its own and needs no LLM key**. That is not a
limitation, it is the division of labour: the tool owns everything
mechanical (multi-source cells, RRF fusion, citation graphs, PDF fetching,
BibTeX serialization, honest health counting); **you own the intelligence** —
planning queries, judging relevance, writing, and verifying every claim.

## Tools

Your client prefixes tool names with the server name (`mcp__citlens__search`,
`citlens:search`, `citlens.search` — whatever it shows you). The names are:

| tool | purpose |
|---|---|
| `doctor` | health: interpreter, drivers, data home, `.env` key NAMES (never values), pool count, jobs, `screen_embedding_runtime`. No key is required |
| `search` | seven-family recall with YOUR queries → RRF fusion → pool + PRISMA exclusions; every record carries `found_by` (family votes) |
| `screen` | relevance TRIAGE: bands the pool core / uncertain / likely_off (local embeddings + BM25 + family consensus; writes screening.jsonl). Triage, not judgment — nothing is auto-excluded |
| `expand` | judgment feedback loop: citation-chain + S2-similarity expansion around papers YOU judged on-topic (`seeds` = DOIs / arXiv ids / titles). The vocabulary-mismatch escape hatch — neighbors don't need query words to be found |
| `pool` | read/filter the pool on disk (citations, years, reviews, DOIs); no new retrieval |
| `fetch` | one paper's open-access full text (arXiv→S2→OpenAlex→Unpaywall→CORE), or abstract fallback |
| `export` | pool → BibTeX/RIS via the same citation table the engine used |
| `audit` | stage-F anchor check: pool coverage of the top surveys' bibliographies |
| `verify` | MECHANICAL review check (no LLM, no key): every `[n]`→reference→pool (honeypot), quoted span must occur verbatim in the cited source, six-grade verdicts validated, honesty block computed |
| `status` | poll a running search job: state, elapsed, log tail, artifacts, stats |

If your client has no MCP, the same tools are one shell call away:

```
%USERPROFILE%\.citlens\bin\citlens.cmd search --topic "..." --queries "..." --target 80
%USERPROFILE%\.citlens\bin\citlens.cmd pool --topic "..." --min-citations 50
```
Same JSON, same shared data home. Never reimplement the search yourself when
the CLI or the MCP tool is available.

## The one rule

**Use `search` for literature. Do not answer a literature question from generic
web search or from memory.** The tool exists because single-source search
measurably fails: on the engine's gold-paper benchmark the adaptive leg
reached recall@20 = 33.3% where single planned keyword queries reached 6.7%
and a single source 0%. Your own web search is a different, weaker
instrument — and a mixture of both makes coverage unauditable.

Your own search is still useful for things the tool does not do: chasing a
specific named paper, resolving a DOI, skimming a PDF you already have.

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
3. **`search`** with `topic` + `queries`. Start with `wait_seconds` = 45. A
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
6. **`pool`** to iterate without re-searching: `min_citations`, `year_from`,
   `is_review: true` for surveys, `query` for a substring, `sort_by`. This
   reads disk; it never retrieves.
7. **Report numbers, not adjectives.** Kept count, pool size, year spread,
   missing DOI/venue counts, reviews found, and the health table. "Found 47
   papers" is weaker than "七家族共入池 49 → 保留 47，其中综述 9，无 DOI 2；
   web 家族因缺 SERPER_API_KEY 全部 failed".

## Coverage discipline

High recall is not "enough results". Before telling a user a field is
covered, check the shapes that are cheap to check:

- **Anchors.** The most-cited works on the topic should be in the pool. If a
  famous survey or the canonical paper is missing, the search is not done —
  re-`search` with differently-phrased queries, or probe its title via
  `title_probes`.
- **Surveys.** `pool` with `is_review: true`. A field with zero surveys in a
  large pool usually means the survey family missed, not that no surveys exist.
- **Time.** `pool` returns `by_year`. A pool that stops at 2021 is stale, not
  complete; sources drift.
- **Saturation.** If a second differently-phrased search adds almost nothing
  new, that is evidence of saturation. Say "no new distinct records on the
  second phrasing" rather than "exhaustive".
- **Audit.** `audit` measures pool coverage of the top surveys'
  bibliographies — the cheapest external recall anchor. Low coverage or
  `reviews_checked = 0` means keep searching, not conclude.

Never present a subset as the whole field. If you filtered the pool (as the
user asked), say what the filter was and what it removed.

## Writing a review — opt-in only, and YOU write it

Writing a survey is opt-in: start only after the user explicitly asked for
one. Before starting, ask and WAIT for answers:

1. **Output language** — `zh` or `en`.
2. **Which themes / sub-directions** to centre on (never invent them).
3. **How many core papers** to deep-read (default 12).
4. **Supporting layer** — one layer of abstract-only citations (default 15) or off.
5. **Full-text grounding** — on by default; off is faster but every
   full-text-level claim must be dropped and the output labelled abstract-only.
6. **Own research to position** — for the 定 step: a description of the
   user's own work/idea. Without it the review ends at 找 (the gaps), and
   that ending is complete — never invent a positioning for them.

Then run the whole chain below. It is the engine's measured pipeline
translated into your discipline — the numbers it produced (citation
precision 73%→98% after the rewrite loop) came from these steps, not from a
model being told to "be careful".

**Select.** From the ranked pool pick the core papers (full-text read) and
the supporting layer (abstract-only citations). Every screened-out paper
goes to `exclusions.jsonl` with a reason code. A large pool with an empty
exclusion log means you did not actually screen.

**Ground.** `fetch` each core paper. `fulltext: true` gives `text_path` —
that text is the ONLY grounding for claims about methods and results.
`fulltext: false` means abstract-only: claims about that paper are
restricted to what its abstract states. Write the unfetchable ones into
`fetch_list.md` (DOI + suggested filename) and count them — they cap how
strong the review can honestly be.

**Write with numbered claims, structured 归 → 评 → 找 → 定.** Every factual
sentence carries a `[n]` citation marker tied to the reference list; no
uncited claims, no markers that decorate rather than ground. And the review
ARGUES — it never lists one paper's findings after another's. Organize the
body in four movements:

1. **归 (consolidate).** Open with what the corpus AGREES on. A consensus
   statement cites the papers that establish it (`[3][7][12]`): one sentence
   synthesized across several papers beats five sentences quoting each.
2. **评 (discriminate).** Map the disagreements: who claims what, under
   which conditions, and WHY they diverge (different benchmarks, scales,
   task definitions, datasets). Put the disagreeing papers side by side
   (`[4]` vs `[9]`) so the reader sees the fault line — two unrelated
   paragraphs are a listing failure, not an analysis.
3. **找 (locate the gap).** State what the searched corpus does NOT
   establish, precisely and relative to what it does: cite what exists
   (`[2][5]`), then name the missing piece — the setting never tested, the
   contradiction never reconciled, the population absent. A gap must be
   EARNED by the preceding 归 and 评; a gap no cited disagreement or stated
   limitation supports is a guess, not a finding.
4. **定 (position).** Place the user's own work on that gap: what it does
   differently and which 找-finding it answers. If the user gave no
   description of their own work, STOP after 找 and present the gaps —
   never invent their contribution.

The integration is the deliverable (整合辨析): each movement synthesizes
ACROSS papers. The claim-level verification below applies unchanged — a 归
claim is verdict-checked against every cited paper's span, a 评 claim needs
spans from both sides, a 找 claim grounds its "what exists" half normally
while its "what is missing" half must stay inside what the searched corpus
actually shows.

**Verify every claim (six-grade verdicts + mechanical check).** For each
claim, compare it against the cited paper's ground text and record one of the
engine's six verdicts: `supported` / `partial` / `background` /
`contradictory` / `unsupported` / `unverifiable`. Quote the source **span**
that justifies the verdict — a verdict without a span is a guess.
`background` = the source backs the field context but not this claim;
`contradictory` = the source conflicts with or narrows it; `unverifiable` =
neither abstract nor fetched text can settle it (never silently upgrade).

Write those verdicts to `verdicts.jsonl` beside the review — one object per
line:

```json
{"claim":"<exact claim sentence incl. [n]>","verdict":"supported",
 "span":"<verbatim quote from the cited source>","citations":[3]}
```

Then call **`verify --review review.md --topic <byte-identical topic>
--verdicts verdicts.jsonl`**. It is mechanical (no LLM, no key) and checks:

- every `[n]` resolves to a reference, and every reference resolves to the
  pool by DOI/title — an unresolved reference is the fabricated-citation
  (蜜罐) case; delete it and the claims it supported;
- each verdict value is one of the six, and every claim has one;
- each `span` occurs **verbatim** in the cited paper's fetched full text
  (abstract floor otherwise) — a span that does not occur is a guess;
- it returns `honesty` (computed, not estimated) and `artifacts`
  (`verification.jsonl`, `honesty.json`).

`clean: false` means fix before delivery; a verifiable claim with no ground
text must be downgraded to `unverifiable`. Fix, re-run, and only then report.

**Defense pass (辩护律师).** Re-read every `supported` verdict arguing the
OPPOSITE: hunt for the span that contradicts or weakens the claim. Verdicts
that flip get rewritten, not defended; re-run `verify` afterwards.

**Rewrite and re-verify.** Delete or rewrite `unsupported` / `contradictory`
claims to match what the source says; re-verify the rewritten text (record
pre-rewrite and post-rewrite precision). Do not keep a claim because it reads
well.

**Report the honesty block the tool computed, verbatim:**

```
citation_precision   = (supported + partial) / verifiable_claims
unverifiable_rate    = unverifiable / total_claims
grounding            = with_fulltext / core_papers   (0 ⇒ the review is ABSTRACT-ONLY — label it)
papers_cited          = n / pool_size
```

If `grounding` is 0, the review is **abstract-only** — label it. If your
verification was rushed, say so; a review that hides its weaknesses is
worthless.

**Deliver.** `review.md`, `verdicts.jsonl`, `verification/verification.jsonl`,
`references.bib` (via `export`), `exclusions.jsonl`, `fetch_list.md`, and the
honesty block in the summary. Save them beside the review or in the run
directory (`<home>/citlens-runs/<topic>-<ts>/`).

## 收工协议 (stage F — done means verified)

Before declaring a task finished:

1. **Anchor verification**: `audit` the topic; report coverage. Missing
   anchors = not done.
2. **Saturation**: one differently-phrased search; report the delta.
3. **Health**: report per-source ok/empty/failed from the last search
   report; failed sources are named, never hidden.
4. **For reviews**: `verify` reports `clean: true`, honesty block reported,
   defense pass done, exclusions logged.

## Failure modes and what they mean

| symptom | meaning / action |
|---|---|
| `state: running` | normal. Poll `status`; do not start a duplicate |
| `state: lost` | the runner died without an exit state (client restart/kill). Read the artifacts and log tail; the work may be complete |
| `doctor.ok: false` | environment problem — the paths printed are the ones to fix |
| `api_keys_recommended_absent` | degraded *breadth*, not broken: no SERPER → web family skipped (report it); no OA key → polite-pool throttling |
| `failed` sources in report | report them explicitly; never as zero hits |
| pool empty before writing | run `search` for the byte-identical topic first |
| `rejected: too many concurrent jobs` | poll the existing jobs; the server caps concurrency deliberately |
| `fetch` returns `fulltext: false` | abstract-only citation; restrict claims accordingly and count it in the honesty block |
| `verify` returns `clean: false` | fix before delivery: unresolved reference = fabricated citation; `span_not_found` = the quote is not in the source; `unverifiable_but_ground_text_exists` = downgrade or ground it |

## Sharing

All agents on this machine point at one data home, so the pool is shared:
search in one agent, `pool`/`fetch`/write from another. Jobs survive the
agent that started them (they are detached), so a long search is not lost
when a session ends. One `~/.citlens/config.json` configures every agent at
once. No LLM key is ever needed by the server — each agent uses its own
model for the judgment work.
