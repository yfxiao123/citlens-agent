# 综述模块 — writing a survey

The module for: *write a survey / literature review on X*. It opens ONLY on
an explicit review/survey request (router gate 2) — a search request, a
question, or your own judgement that a survey "would be useful" never opens
it. The pool underneath comes from the
[search module](search.md) under its own 收工 discipline (audit, saturation,
health); this module never skips that floor by writing over an unaudited
pool.

This file assumes the shared core in [../SKILL.md](../SKILL.md).

## Before starting — ask, then WAIT

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
7. **Policy dimension** (macro/econ topics) — whether to bring in the
   policy-side corpus and its perspective (NBER / Fed Board / IMF). Default
   yes when the topic is policy-adjacent; a policy-topic pool with zero
   `policy_org` records means the `policy` family never fired — check
   `families` and the health table before writing.

Then run the whole chain below. It is the engine's measured pipeline
translated into your discipline — the numbers it produced (citation
precision 73%→98% after the rewrite loop) came from these steps, not from a
model being told to "be careful".

## Select

From the ranked pool pick the core papers (full-text read) and the
supporting layer (abstract-only citations). Every screened-out paper goes
to `exclusions.jsonl` with a reason code. A large pool with an empty
exclusion log means you did not actually screen.

## Ground

`fetch` each core paper. `fulltext: true` gives `text_path` — that text is
the ONLY grounding for claims about methods and results. `fulltext: false`
means abstract-only: claims about that paper are restricted to what its
abstract states. Write the unfetchable ones into `fetch_list.md` (DOI +
suggested filename) and count them — they cap how strong the review can
honestly be.

## Write with numbered claims, structured 归 → 评 → 找 → 定

Every factual sentence carries a `[n]` citation marker tied to the reference
list; no uncited claims, no markers that decorate rather than ground. And
the review ARGUES — it never lists one paper's findings after another's.
Organize the body in four movements:

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

   Run `gaps` before writing this movement — it turns the gap from an
   inference into contrastable structure, mechanically: the coverage matrix
   (your concept blocks × time bands) exposes cells the pool never reached —
   structural gap candidates, visible rather than argued; `mine: true`
   returns verbatim limitation/future-work sentences from the fetched
   fulltexts — quote those with `[n]` and they become gap evidence `verify`
   can check like any other span (author-testimony beats inference from
   silence); `check: "<draft gap statement>"` scores the draft against the
   pool and returns its nearest existing work — a close neighbour is
   mechanical refutation that the gap may already be done. No close
   neighbour is WEAK positive evidence — never ship it alone.
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

## Produce movement by movement — verify as you go

Quality drift compounds: a review written end-to-end and verified once at
the end fails in clusters (the rewrite loop then touches everything).
Produce incrementally instead — the verification is mechanical and cheap
against a partial text:

1. Write 归 with its claims and its slice of `verdicts.jsonl`, references
   list included so far → run `verify` on the partial review → fix what it
   flags → only then start 评.
2. 评 → verify again (the whole partial text). 找 (run `gaps` first) →
   verify. 定, when it exists → verify.
3. Final pass on the COMPLETE review: defense pass below, rewrite, and the
   definitive `verify` + honesty block.

Each movement is small enough that `verify` catches a drift while it is one
paragraph old, not after it has shaped three sections. Keep ONE cumulative
`verdicts.jsonl` — append each movement's lines, never rewrite the file from
memory.

## Prose style — 去 AI 味

Four tics mark machine-written prose; write against all four, and reread
each movement against them before its verify pass:

1. **Alternate long and short sentences.** A wall of long sentences with no
   short ones reads generated. After a long analysis sentence, land a short
   one — "This advantage disappears at scale." Two long sentences in a row
   is the limit; the third must be short.
2. **No quotes around concepts.** Introduce a term once in plain text, then
   use it bare. Wrapping every concept in double quotes when it is neither
   a quotation nor a coined term is a tell. Reserve quote marks for actual
   quotations.
3. **No parenthetical results.** Numbers belong in the sentence: "F1 drops
   4.1 points when the adapter is removed", not "performance drops (−4.1
   F1)". Parentheses are for citations and mathematics, not for smuggling
   results past the sentence.
4. **No templated layered listing.** If every paragraph opens with the same
   shape, or a section is a stack of bullets that could have been an
   argument, restructure into prose. Lists are for content that genuinely
   IS an enumeration; structure templates are a tell.

Each sentence states its subject clearly — a "this means…" with no
antecedent, or a sentence whose main claim hides inside a subordinate
clause, fails this test. The `[n]` citation markers and the verify workflow
(verdicts, spans, honesty numbers) are exempt: they are grounding machinery,
not review prose.

## Verify every claim (six-grade verdicts + mechanical check)

For each claim, compare it against the cited paper's ground text and record
one of the engine's six verdicts: `supported` / `partial` / `background` /
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

## Defense pass (辩护律师)

Re-read every `supported` verdict arguing the OPPOSITE: hunt for the span
that contradicts or weakens the claim. Verdicts that flip get rewritten, not
defended; re-run `verify` afterwards.

## Rewrite and re-verify

Delete or rewrite `unsupported` / `contradictory` claims to match what the
source says; re-verify the rewritten text (record pre-rewrite and
post-rewrite precision). Do not keep a claim because it reads well.

## Report the honesty block the tool computed, verbatim:

```
citation_precision   = (supported + partial) / verifiable_claims
unverifiable_rate    = unverifiable / total_claims
grounding            = with_fulltext / core_papers   (0 ⇒ the review is ABSTRACT-ONLY — label it)
papers_cited          = n / pool_size
```

If `grounding` is 0, the review is **abstract-only** — label it. If your
verification was rushed, say so; a review that hides its weaknesses is
worthless.

## Deliver

`review.md`, `verdicts.jsonl`, `verification/verification.jsonl`,
`references.bib` (via `export`), `exclusions.jsonl`, `fetch_list.md`, and the
honesty block in the summary. Save them beside the review or in the run
directory (`<home>/citlens-runs/<topic>-<ts>/`).

## 综述模块收工

Before declaring a survey finished:

1. **Pool floor**: the underlying pool passed the search module's 收工
   (audit coverage reported, saturation delta reported, health table named).
2. **`verify` reports `clean: true`** on the complete review, after the
   defense pass and the rewrite loop.
3. **The honesty block is reported verbatim** (and the abstract-only label
   applied when grounding is 0).
4. **Every screened-out paper is in `exclusions.jsonl`** with a reason code.
