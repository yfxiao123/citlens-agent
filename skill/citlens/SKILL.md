---
name: citlens
description: High-recall literature search and citation-grounded writing through the CiteLens CLI (%USERPROFILE%\.citlens\bin\citlens.cmd <tool> — search, pool, screen, expand, fetch, export, audit, verify, status, doctor; one JSON document per call). Use for any request to find papers, search or map a research field, check coverage, write a literature review/survey with real citations, or answer a specific question from the literature. THREE SEPARATE JOBS routed to three module files — finding literature (workflows/search.md), writing a survey (workflows/review.md, only on an explicit survey request), answering a specific question (workflows/answer.md). A find-papers request delivers the pool and the coverage numbers and STOPS — it never escalates into survey writing. You are the planner and the judge: craft the English concept-block queries yourself and pass them to `search`; feed papers you judge on-topic back via `expand`; the tool handles the eight recall families, RRF fusion, citation snowball, survey harvest, the policy corpus (NBER / Fed / IMF), full-text fetch, mechanical citation/verdict verification and BibTeX export. Do not substitute your own web search for it.
---

# CiteLens

`citlens` is a tool, not a prompt. The retrieval mechanics live in a Python
core exposed as a CLI (one subprocess per call, one JSON document on stdout);
you call it and report what it returns.
That is the whole point: **the tool is what makes the search reproducible** —
two different agents calling `search` with the same queries get the same
pool, and an agent that searched can hand its pool to an agent that writes.

This build has **no LLM of its own and needs no LLM key**. That is not a
limitation, it is the division of labour: the tool owns everything
mechanical (multi-source cells, RRF fusion, citation graphs, PDF fetching,
BibTeX serialization, honest health counting); **you own the intelligence** —
planning queries, judging relevance, writing, and verifying every claim.

## Route FIRST — three jobs, three modules

Finding literature, writing a survey, and answering a specific question are
DIFFERENT jobs with different deliverables. Read the module file for the job
the user actually asked for — not all of them:

| the user asked to | module | deliverable | you are done when |
|---|---|---|---|
| find papers, map a field, check coverage | [workflows/search.md](workflows/search.md) | the pool + coverage numbers + evidence trail (health table, query feedback, audit) | the numbers and the trail are reported — **never escalates into prose** |
| write a survey / literature review (explicit request ONLY) | [workflows/review.md](workflows/review.md) | review.md: 归→评→找→定 body, verdicts.jsonl (six-grade verdicts), `verify` clean=true, honesty block | verify passes, the honesty block is reported |
| answer a specific question (影响 / 机制 / 有没有证据 / 怎么做) | [workflows/answer.md](workflows/answer.md) | the answer itself, claim by claim with [n] citations, verify-checked | the question is answered and its evidence is named |

Four hard gates:

1. **A search request is COMPLETE when the numbers and the evidence trail
   are reported.** Starting to write a survey or an essay from a search the
   user did not ask to have written is the failure this routing exists to
   prevent.
2. **The survey module opens only on an explicit review/survey request** —
   and only after its seven setup questions are asked and answered.
3. **A question gets an answer, not a survey**: no 归→评→找→定 scaffolding,
   no review.md, length follows the question.
4. **When the job is ambiguous, ask once** — "do you want the papers, a
   survey over them, or an answer to a specific question?" — then route.

The rest of this file is shared by all three modules: the tools, the CLI
surface, the one rule, discipline layers, failure semantics. The module
files assume it.

## Tools

Every tool is a subcommand of the shim. The names are:

| tool | purpose |
|---|---|
| `doctor` | health: interpreter, drivers, data home, `.env` key NAMES (never values), pool count, jobs, `screen_embedding_runtime`. No key is required |
| `search` | eight-family recall with YOUR queries → RRF fusion → pool + PRISMA exclusions; every record carries `found_by` (family votes) and `doc_type`/`policy_org` (journal vs policy-side) |
| `screen` | relevance TRIAGE: bands the pool core / uncertain / likely_off (local embeddings + BM25 + family consensus; writes screening.jsonl). Triage, not judgment — nothing is auto-excluded |
| `gaps` | mechanical substrate for 找: coverage matrix (concept blocks × time bands — empty cells are structural gap candidates), stated-gap mining (verbatim limitation/future-work sentences from fetched fulltexts), novelty check (a draft gap statement vs the pool's nearest existing work) |
| `expand` | judgment feedback loop: citation-chain + S2-similarity expansion around papers YOU judged on-topic (`seeds` = DOIs / arXiv ids / titles, or `from_notes: core` to seed from your notes). The vocabulary-mismatch escape hatch — neighbors don't need query words to be found |
| `notes` | reading notes: per-paper verdict (core / uncertain / off) + one-line reason, persisted per topic in data/notes/. The judgment memory — record as you read |
| `dedup` | duplicate report over a pool (doi / arXiv / normalized title — a specific ≥4-token title stands alone even with missing authors); merge=true collapses groups into the DOI-carrying survivor (topic pools, .bak first) |
| `pool` | read/filter the pool on disk (citations, years, reviews, DOIs); no new retrieval |
| `fetch` | one paper's open-access full text (arXiv→S2→OpenAlex→Unpaywall→CORE), or abstract fallback |
| `export` | pool → BibTeX / RIS / EndNote XML / CSL JSON via the same citation table the engine used |
| `audit` | stage-F anchor check: pool coverage of the top surveys' bibliographies |
| `verify` | MECHANICAL review check (no LLM, no key): every `[n]`→reference→pool (honeypot), quoted span must occur verbatim in the cited source, six-grade verdicts validated, honesty block computed. Fail-closed: a review with claims but no verdicts file returns `clean=false` |
| `status` | poll a running search job: state, elapsed, log tail, artifacts, stats |

## One surface — the CLI

The 13 tools, one JSON contract, one shared data home, one way in (the MCP
server that used to shadow this CLI was removed in 2.0):

```
%USERPROFILE%\.citlens\bin\citlens.cmd search --topic "..." --queries "..." --target 60 --pivot 2
%USERPROFILE%\.citlens\bin\citlens.cmd screen --topic "..." --queries "..."
%USERPROFILE%\.citlens\bin\citlens.cmd notes --topic "..." --doi "..." --verdict core --note "..."
%USERPROFILE%\.citlens\bin\citlens.cmd expand --topic "..." --from-notes core
%USERPROFILE%\.citlens\bin\citlens.cmd pool --topic "..." --min-citations 50
%USERPROFILE%\.citlens\bin\citlens.cmd fetch --doi "..." --topic "..."
%USERPROFILE%\.citlens\bin\citlens.cmd status --job_id "..."
```
(macOS/Linux: `~/.citlens/bin/citlens` shim, same syntax. `citlens.cmd`
with no arguments prints usage; `citlens.cmd tools` prints the catalogue
with every argument schema.)

Timing, two classes of command:

- **Detached by design — `search` (always) and `fetch --background true`.**
  They return a `job_id` after ~20s (`wait_seconds`): the search genuinely
  takes 2–6 min and its runner must outlive your shell. Poll `status`.
- **Synchronous — everything else** (`screen`/`expand` ~1–2 min, `gaps`,
  `pool`, ...). Wrap them in your shell's OWN background mechanism
  (run_in_background) and read stdout when done: a detached job spawned
  from a short-lived shell command dies with the shell's process tree
  (measured), so these never detach. Long operations write artifacts as
  they go (`screening.jsonl`, `<topic>.expand.json`, `pool.jsonl`), so a
  killed run keeps its evidence.

Dead jobs self-heal: any state read reaps runners whose process died or
that went silent >45 min, persisting state=lost with the reason — a job
never sits in "running" forever.

Never reimplement the search yourself when the CLI is available.

## The one rule

**Use `search` for literature. Do not answer a literature question from generic
web search or from memory.** The tool exists because single-source search
measurably fails: on the engine's gold-paper benchmark the adaptive leg
reached recall@20 = 33.3% where single planned keyword queries reached 6.7%
and a single source 0%. Your own web search is a different, weaker
instrument — and a mixture of both makes coverage unauditable.

Your own search is still useful for things the tool does not do: chasing a
specific named paper, resolving a DOI, skimming a PDF you already have.

## Discipline layers (学科层)

Some rules are not literature-search mechanics — they belong to a field.
Economic vs statistical significance is an economics discipline; a medicine
review has evidence hierarchies; law has doctrinal weight. Those rules live
in LAYERS, one file per field under `disciplines/`, not in this skill's
general flow — the general flow stays field-neutral.

Activation is automatic and mechanical. `search` detects the domain from
your topic and queries (a per-discipline lexicon, zero LLM; policy-corpus
records surviving in the pool are a second trigger) and stamps a
`discipline` hint into the result, with a pointer stating that field's core
rules. When you see it: read the matched layer below and apply it from
triage through writing.

| layer | applies when |
|---|---|
| [`disciplines/economics.md`](disciplines/economics.md) | empirical macro / monetary / policy topics — detected by lexicon or by policy-corpus records in the pool |

If your topic clearly belongs to a field with no layer yet, follow that
field's native epistemic conventions and say which you used — do not import
another field's. The registry (`citens/disciplines.py`) and the
`disciplines/` folder are the extension point: a new layer is one registry
entry plus one file.

## Failure modes and what they mean

| symptom | meaning / action |
|---|---|
| `state: running` | normal. Poll `status`; do not start a duplicate |
| `state: lost` | the runner died without an exit state (client restart/kill). Read the artifacts and log tail; the work may be complete |
| `doctor.ok: false` | environment problem — the paths printed are the ones to fix |
| `api_keys_recommended_absent` | degraded *breadth*, not broken: no SERPER → web family skipped (report it); no OA key → polite-pool throttling |
| `failed` sources in report | report them explicitly; never as zero hits |
| pool empty before writing | run `search` for the byte-identical topic first |
| `rejected: too many concurrent jobs` | poll the existing jobs; the runner caps concurrency deliberately |
| `fetch` returns `fulltext: false` | abstract-only citation; restrict claims accordingly and count it in the honesty block. `outcomes` names every leg tried and why it failed; `fetch --force` retries past the 1-day miss cache |
| `verify` returns `clean: false` | fix before delivery: unresolved reference = fabricated citation; `span_not_found` = the quote is not in the source; `unverifiable_but_ground_text_exists` = downgrade or ground it; `claims_without_verdict > 0` = you shipped without judging every claim (write the verdicts file) |
| `quality_flag: ai_generated` on a record | machine-synthesized report that self-describes as such — human judgment required, not citable as peer-reviewed scholarship |

## Sharing

All agents on this machine point at one data home, so the pool is shared:
search in one agent, `pool`/`fetch`/write from another. Jobs survive the
agent that started them (they are detached), so a long search is not lost
when a session ends. One `~/.citlens/config.json` configures every agent at
once. No LLM key is ever needed by the tool — each agent uses its own
model for the judgment work.
