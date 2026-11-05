"""Mechanical pivot expansion — PRF's local-analysis leg, LLM-free.

After the first search wave, the corroborated head of the fused pool
(records surfaced by ≥2 recall families — the cross-family consensus
signal) carries the vocabulary the sources actually answer to. Extract its
most discriminative content words — frequent across the seeds, rare across
the wave pool (IDF weighting; the Xu & Croft local-analysis recipe) — and
build the second wave's queries from them.

Why this exists: a planner paraphrasing the user's question inherits the
question's vocabulary. Measured 2026-11-05 on 10 missed LitSearch golds:
all three LLM layers (planned queries, HyDE titles, pivots) repeated the
question's own words while the gold papers spoke "lie detection" /
"post-abstention" / "bootstrapped unsupervised". Citation chaining bypasses
query vocabulary entirely — but only once some on-topic seed reaches the
pool. Pivot queries are the mechanical way to buy that seed.

Drift guards (blind PRF trades recall for precision — see the PRF-failure
audits in the pool): seeds must be corroborated (never single-family
records), the term count is capped, and pivot records enter through the
normal family seats with found_by stamped like any other family — screen's
consensus channel will treat them as corroborated only when another family
surfaces them too.
"""

from __future__ import annotations

import math
import re

from citens.grounding.retrieval import _terms

# Content-word filter for seed terms: stoplist plus the generic academic
# glue that survives tokenization ("results", "propose", "method" …).
_PIVOT_STOP = {
    "results", "result", "propose", "proposed", "method", "methods", "approach",
    "approaches", "based", "using", "show", "shown", "paper", "work", "model",
    "models", "task", "tasks", "data", "dataset", "datasets", "performance",
    "state", "art", "significant", "improve", "improves", "improving",
    "outperforms", "outperform", "achieve", "achieves", "effectively",
    "across", "between", "their", "these", "those", "which", "that", "this",
    "from", "with", "into", "over", "under", "than", "then", "have", "has",
    "been", "were", "are", "our", "can", "may", "such", "also", "both",
    "when", "while", "where", "how", "what", "why", "each", "more", "most",
    "first", "second", "third", "well", "often", "however", "therefore",
    "learning",  # appears in half of all ML titles; never discriminative
}


def _content_terms(text: str) -> list[str]:
    out: list[str] = []
    for t in _terms(text):
        if len(t) < 4 or t in _PIVOT_STOP:
            continue
        if not re.fullmatch(r"[a-z][a-z0-9]+", t):
            continue
        out.append(t)
    return out


def build_pivot_queries(
    seed_papers,
    pool,
    *,
    n_queries: int = 2,
    terms_per_query: int = 6,
) -> list[str]:
    """Discriminative-term queries built from corroborated seed records.

    ``seed_papers``: the corroborated head (found_by ≥ 2). ``pool``: the
    whole first-wave pool — the IDF denominator. Returns up to
    ``n_queries`` space-joined term strings, highest-scoring terms first.
    """
    seeds = list(seed_papers)[:12]
    if not seeds:
        return []
    seed_keys = {(p.title or "").lower().strip() for p in seeds}
    seed_texts = [f"{p.title}. {(p.abstract or '')[:600]}" for p in seeds]
    # The IDF denominator is the REST of the wave: the seeds are in the pool,
    # so counting them makes the very vocabulary we want look "too common"
    # (measured 2026-11-05: 'deception' in all 3 seeds got excluded by the
    # drift guard when the seeds themselves were part of the denominator).
    pool_texts = [
        f"{p.title}. {(p.abstract or '')[:600]}"
        for p in pool
        if (p.title or "").lower().strip() not in seed_keys
    ]

    pool_docs = [set(_terms(t)) for t in pool_texts]
    n = max(len(pool_docs), 1)

    df_pool: dict[str, int] = {}
    for doc in pool_docs:
        for t in set(doc):
            df_pool[t] = df_pool.get(t, 0) + 1

    seed_df: dict[str, int] = {}
    for text in seed_texts:
        for t in set(_content_terms(text)):
            seed_df[t] = seed_df.get(t, 0) + 1

    n_seeds = len(seed_texts)
    scored: list[tuple[float, str]] = []
    for term, k in seed_df.items():
        if k < max(2, n_seeds // 3):
            continue  # must appear across several seeds, not one paper's jargon
        pool_df = df_pool.get(term, 0)
        if pool_df >= 0.5 * n:
            continue  # too common across the wave to steer anything
        idf = math.log(1 + n / (1 + pool_df))
        scored.append((k * idf, term))
    scored.sort(reverse=True)
    terms = [t for _s, t in scored[: terms_per_query * n_queries]]
    if not terms:
        return []
    queries = []
    for i in range(n_queries):
        chunk = terms[i * terms_per_query : (i + 1) * terms_per_query]
        if chunk:
            queries.append(" ".join(chunk))
    return queries
