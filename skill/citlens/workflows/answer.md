# 答问模块 — answering a specific question

The module for: *does X affect Y?*, *what is the mechanism behind X?*,
*is there evidence that X works in setting Z?*, *how do people usually do
X?* — any request whose deliverable is an ANSWER, with the literature as
the evidence, not as the deliverable itself.

Gate: the user asked a question. If they asked for papers, that is the
[search module](search.md); if they asked for a survey, that is the
[review module](review.md) — and a question NEVER becomes a survey: no
归→评→找→定 scaffolding, no review.md, answer length follows the question.

This file assumes the shared core in [../SKILL.md](../SKILL.md).

## Workflow — answer, don't survey

1. **Restate the question** in one sentence of your own before touching any
   tool (the search module's misread guard: "performance decline in various
   LANGUAGES" is not about quantization — a real bench misread no retrieval
   could fix). Name the 2-3 content blocks the answer hinges on; these
   become your query blocks.
2. **Search targeted, not exhaustive.** Same PRESS discipline as the search
   module (concept blocks → combination queries → register ladder), but
   scaled down: `target` 30–60, `title_probes` carry the most weight (the
   decisive paper for a question is usually nameable as a hypothetical
   title), one scout wave when the field's vocabulary is unknown. Read the
   health table and `query_feedback` exactly as the search module teaches —
   a failed source is named, an empty block is rephrased.
3. **Screen, then read.** `screen` with your concept-block queries; read the
   core + uncertain records' titles and abstracts. You are looking for the
   DECISIVE papers — the ones whose methods/results actually settle (or
   split) the question — not for coverage of the field. Record verdicts
   with `notes` as you go; feed 2-3 judged-on-topic hits to `expand` when
   the decisive paper is clearly one citation hop away.
4. **Fetch only the decisive few** — typically 3–8 papers, not the whole
   core band. `fetch` them; `fulltext: true` claims may quote methods and
   results, `fulltext: false` claims stay at what the abstract states. If
   the decisive paper has no OA copy, say so and answer at abstract level —
   never silently upgrade.
5. **Write the answer, claim by claim with [n].** Direct answer first — the
   one-sentence answer to the question in the first paragraph, then the
   evidence. Every factual claim carries `[n]` tied to a References section
   (the same format `verify` checks). State disagreements AS disagreements:
   "X improves Y at small scale [2][5] but not at scale [7]" — do not
   average them into a consensus that no paper states. Label each claim's
   floor where it matters (full-text vs abstract-only). If the corpus does
   not settle the question, that IS the answer: say what it establishes,
   what it leaves open, and stop.
6. **Verify the answer like a (very short) review.** Write the same
   `verdicts.jsonl` (six-grade verdicts + verbatim spans, one object per
   claim) and call `verify --review <answer file> --topic <byte-identical
   topic> --verdicts verdicts.jsonl`. The machinery is text-agnostic — it
   checks [n]→reference→pool and span-verbatim exactly as for a survey.
   `clean: false` means fix before delivering. A question with three claims
   takes seconds to verify; there is no excuse to skip it.
7. **Deliver.** The answer text, the References section, `verdicts.jsonl`,
   and one line of evidence arithmetic (how many claims supported /
   partial / unverifiable, how many of the cited papers were full-text
   grounded). Save beside the answer file or in the run directory
   (`<home>/citlens-runs/<topic>-<ts>/`).

## 答问模块收工

1. **`verify` reports `clean: true`** on the answer.
2. **Failed sources named**, never reported as zero hits.
3. **Every claim's floor is labelled** — full-text grounded vs abstract-only.
4. **The answer is an answer** — if it grew 归评找定 sections or turned into
   review.md, that was the review module leaking: cut it back.
