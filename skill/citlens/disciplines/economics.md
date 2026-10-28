# Economics layer

Applied automatically when a search reports `"discipline": "economics"` —
the lexicon matched your topic/queries, or policy-corpus records survived in
the pool. Apply it to any empirical macro / monetary / policy topic even
when no hint fired; ignore it outside them.

## Evidence comes in two perspectives — never blend them

Journal evidence and the policy side answer the same question with different
framings. Pool records separate them mechanically: `doc_type`
(journal / working_paper / policy_note / preprint / report) and `policy_org`
(NBER, Federal Reserve Board, IMF). When you read and when you write, treat
them as two perspectives, and say where each framing departs from the other:
which variables the policy researchers watch, which constraints they state
(forward guidance, the effective lower bound, data latency), which questions
they treat as live that the journals consider settled — and vice versa.

Policy notes (FEDS Notes, IFDP Notes) are written FOR decision-makers. That
is their methodological value, not a weakness: every number in them carries
a how-big-before-we-act yardstick, and their structure shows how the
institution frames the problem.

## Statistical significance is not economic significance

Many published coefficients are significant and economically negligible;
policy does not move for them, and a review that reports stars instead of
sizes misleads. For every key coefficient, elasticity, or impulse response
you cite:

- give the magnitude, not just its sign and stars;
- put it against a reference scale the reader can judge (a basis-point move
  in the policy rate, a percent of GDP, a decade trend);
- state what policy tradeoff that size implies, if any.

An effect too small to act on is a finding worth stating as such.

## Policy notes are 找-evidence

Institutions publish their own limitation sections and stated data gaps. A
Fed note saying "we cannot yet measure X" or "the evidence on Y remains
inconclusive" is citable gap evidence — stronger than a gap inferred from
silence, because the institution itself concedes it. Mine the notes for
these statements and cite them like any other source (same [n] discipline,
same span verification).

## NBER working papers are the frontier

The working-paper-to-journal lag is one to three years, so this year's NBER
WPs ARE the field's leading edge — a pool of only published journal papers
is systematically stale. Frontier-reading discipline:

- a one-to-two-year-old WP already gathering citations is pioneer work —
  distinguish it from incremental extensions in your 找 and 归;
- to see where a line is moving, `expand` FORWARD from the WP that opened
  it (its citers are the follow-on work), not just backward to its roots;
- WPs are not peer-reviewed final claims — cite their findings as
  preliminary where the published version differs.

## Writing hooks

- **评**: quantitative disagreements are often magnitude disagreements — two
  estimates can agree in sign and differ threefold in size, and the policy
  meaning lives in the size. Discriminate sizes, not only positions.
- **找**: policy-note data gaps (above) are earned support for a gap claim.
- **定**: state the stakes — which policy tradeoff, welfare impact, or
  real-world outcome turns on the answer. A positioning that names no
  consequence reads as an exercise.

## Boundaries of this layer

Regional Fed banks, BIS, and ECB deposit no Crossref DOIs; reach them
through the web bridge with site-scoped `web_queries`
("site:dallasfed.org working paper ..."). Mapping the field's overall
boundary (学科边界) is a general move — survey family plus the 归 movement —
not specific to economics; this layer only governs how economic evidence is
read, sized, and argued.
