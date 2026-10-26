"""Deterministic relevance triage for a literature pool — no LLM, no key.

The agent remains the judge (the engine's LLM cascade stays absent). What
this module adds is TRIAGE: every pool record is scored against the
caller's concept-block queries on channels that are mechanical and
explainable, then banded into ``core`` / ``uncertain`` / ``likely_off``.
Nothing is ever excluded here — the bands only decide where the agent's
reading attention goes first, and every final call still goes through the
PRISMA exclusion log.

Channels (each degrades gracefully, weights renormalized per paper over
the channels that record actually has — mirroring ranking.py):

    semantic   local sentence-transformers embeddings (optional extra,
               ``pip install citlens-agent[embedding]``). Score = MAX over
               the query set of cosine(title+abstract, query): a paper that
               nails ONE concept block is on-topic even if it ignores the
               rest — the same shape as the agent recall family.
    lexical    BM25 over title+abstract vs the joined query set, normalized
               by the pool max: exact terminology (LOB, OFI) must beat
               paraphrase.
    consensus  how many distinct recall families surfaced the record
               (``Paper.found_by``, filled by the recall driver); 4+ families
               saturates. Legacy records without the field simply lose this
               channel instead of being punished for missing metadata.

Composite (semantic available): 0.6*semantic + 0.2*lexical + 0.2*consensus
Composite (no model / extra):    0.7*lexical + 0.3*consensus

Band cutoffs default to 0.5 / 0.32 on the bge cosine scale — heuristic and
provisional (uncalibrated against the LitSearch gold labels); every call
can override them, and the report says which channels fired.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path

from citens import cache
from citens.config import settings
from citens.grounding.retrieval import _terms
from citens.models import Paper

# channel weights when the semantic channel is available / absent
_W_WITH_SEM = {"semantic": 0.6, "lexical": 0.2, "consensus": 0.2}
_W_NO_SEM = {"lexical": 0.7, "consensus": 0.3}
_CONSENSUS_SAT = 4  # families at which the consensus channel saturates

_EMB_TEXT_MAX = 1000  # abstract chars fed to the embedding (bge truncates anyway)


# --- lexical channel -----------------------------------------------------------


def bm25_scores(texts: list[str], query: str, *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Absolute BM25 scores (``bm25_rank_texts`` returns only an order; bands
    need values). Pure-Python on purpose: pools are hundreds, not millions."""
    docs = [_terms(t) for t in texts]
    n = len(docs)
    if n == 0:
        return []
    avgdl = sum(len(d) for d in docs) / n
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    qterms = list(dict.fromkeys(_terms(query)))
    scores: list[float] = []
    for d in docs:
        tf: dict[str, int] = {}
        for t in d:
            tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for t in qterms:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avgdl))
        scores.append(s)
    return scores


# --- semantic channel -----------------------------------------------------------

_model_singleton = None
_model_name_loaded: str | None = None


def _load_model(name: str):
    """sentence-transformers singleton; None whenever the extra is absent or
    the model cannot load (offline, bad name) — semantic channel then skips
    and the composite renormalizes over the remaining channels."""
    global _model_singleton, _model_name_loaded
    if _model_singleton is not None and _model_name_loaded == name:
        return _model_singleton
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:  # noqa: BLE001 — the extra is optional by design
        return None
    try:
        _model_singleton = SentenceTransformer(name)
        _model_name_loaded = name
        return _model_singleton
    except Exception:  # noqa: BLE001 — offline / unknown repo id
        return None


def embed_local(texts: list[str], model_name: str) -> list[list[float]] | None:
    """Unit-normalized vectors via the local model, disk-cached per text.
    None on any failure (the channel skips; the run never depends on it)."""
    model = _load_model(model_name)
    if model is None:
        return None
    cached: list[list[float] | None] = []
    missing: list[int] = []
    for i, t in enumerate(texts):
        v = cache.get("screen.emb", {"model": model_name, "text": t})
        if isinstance(v, list):
            cached.append(v)
        else:
            cached.append(None)
            missing.append(i)
    if missing:
        try:
            vecs = model.encode(
                [texts[i] for i in missing],
                batch_size=32, normalize_embeddings=True, show_progress_bar=False,
            )
            for i, vec in zip(missing, vecs, strict=False):
                v = [float(x) for x in vec]
                cached[i] = v
                cache.put("screen.emb", {"model": model_name, "text": texts[i]}, v)
        except Exception:  # noqa: BLE001
            return None
    if any(v is None for v in cached):
        return None
    return cached  # type: ignore[return-value]


# --- triage ----------------------------------------------------------------------


def _paper_text(p: Paper) -> str:
    return f"{p.title}. {(p.abstract or '')[:_EMB_TEXT_MAX]}".strip()


def _consensus(p: Paper) -> float | None:
    if not p.found_by:
        return None
    return min(len(set(p.found_by)), _CONSENSUS_SAT) / _CONSENSUS_SAT


def screen_papers(
    papers: Sequence[Paper],
    queries: Sequence[str],
    *,
    model: str | None = None,
    core_threshold: float | None = None,
    off_threshold: float | None = None,
    out_path: Path | None = None,
    limit: int = 30,
) -> dict:
    """Score + band a pool against the query set. Returns the report dict
    (see the driver / MCP tool for the exact surface)."""
    qs = [q.strip() for q in queries if q and q.strip()]
    core_t = settings.screen_core_threshold if core_threshold is None else core_threshold
    off_t = settings.screen_off_threshold if off_threshold is None else off_threshold
    model_name = settings.screen_embedding_model if model is None else model.strip()

    sem_vecs: list[list[float] | None] | None = None
    query_vecs: list[list[float]] = []
    sem_note = "off"
    if qs and model_name:
        texts = [_paper_text(p) for p in papers]
        pool_vecs = embed_local(texts, model_name)
        qv = embed_local(list(qs), model_name)
        if pool_vecs is not None and qv is not None:
            sem_vecs = pool_vecs
            query_vecs = qv
            sem_note = f"{model_name} (local)"
        else:
            sem_note = "unavailable (model not installed/loadable — lexical+consensus only)"

    lex_norm: list[float] = []
    if qs:
        raw = bm25_scores([_paper_text(p) for p in papers], " ".join(qs))
        mx = max(raw) if raw else 0.0
        lex_norm = [r / mx if mx > 0 else 0.0 for r in raw]

    rows: list[dict] = []
    for i, p in enumerate(papers):
        channels: dict[str, float] = {}
        best_q: str | None = None
        if sem_vecs is not None:
            v = sem_vecs[i]
            best = -1.0
            for q, qv in zip(qs, query_vecs, strict=False):
                c = sum(a * b for a, b in zip(v, qv, strict=False))
                if c > best:
                    best = c
                    best_q = q
            channels["semantic"] = round(max(best, 0.0), 4)
        if qs:
            channels["lexical"] = round(lex_norm[i] if lex_norm else 0.0, 4)
        cons = _consensus(p)
        if cons is not None:
            channels["consensus"] = round(cons, 4)

        weights = _W_WITH_SEM if "semantic" in channels else _W_NO_SEM
        wsum = sum(weights.get(c, 0.0) for c in channels)
        score = (
            sum(weights.get(c, 0.0) * v for c, v in channels.items()) / wsum
            if wsum
            else 0.0
        )
        band = (
            "core" if score >= core_t
            else "likely_off" if score < off_t
            else "uncertain"
        )
        rows.append({
            "key": p.doi or p.title.lower().strip(),
            "title": p.title,
            "doi": p.doi,
            "year": p.year,
            "citation_count": p.citation_count,
            "is_review": p.is_review,
            "band": band,
            "score": round(score, 4),
            "channels": channels,
            "best_query": best_q,
            "found_by": p.found_by,
        })

    rows.sort(key=lambda r: (-r["score"], -(r["citation_count"] or 0)))
    for rank, r in enumerate(rows, 1):
        r["rank"] = rank

    bands = {"core": 0, "uncertain": 0, "likely_off": 0}
    for r in rows:
        bands[r["band"]] += 1

    written = None
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "queries": qs,
            "channels": {
                "semantic": sem_note,
                "lexical": "bm25 (pool-normalized)" if qs else "off (no queries)",
                "consensus": "found_by family votes" if any(p.found_by for p in papers) else "absent (legacy pool records)",
            },
            "thresholds": {"core": core_t, "off": off_t},
            "n": len(rows),
            "bands": bands,
            "papers": rows,
        }
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        written = str(out_path)

    top = rows[: max(0, limit)]
    return {
        "n": len(rows),
        "queries": qs,
        "channels": {
            "semantic": sem_note,
            "lexical": "bm25 (pool-normalized)" if qs else "off (no queries)",
            "consensus": "found_by family votes" if any(p.found_by for p in papers) else "absent (legacy pool records)",
        },
        "thresholds": {"core": core_t, "off": off_t},
        "bands": bands,
        "screening_path": written,
        "papers": [
            {k: r[k] for k in ("rank", "title", "doi", "year", "band", "score",
                               "channels", "best_query", "found_by")}
            for r in top
        ],
        "note": (
            "三分带是分流不是判决：core+uncertain 值得精读，likely_off 批量复核后"
            "按 PRISMA 记入 exclusions（绝不因 band 自动剔除）。阈值是启发式默认值，"
            "尚未在 LitSearch 金标上校准——报告 bands 时请同时报告阈值与通道。"
        ),
    }
