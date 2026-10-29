"""Mechanical substrate for the 找 (gap-locating) movement — no LLM, no key.

The verify tool can check a 找 claim's "what exists" half but never its
"what is missing" half: absence has no span to quote. The gap-identification
literature (dogfooded survey 2026-10-28) converges on one fix — turn the gap
from an inference into a CONTRASTABLE STRUCTURE. Three channels implement
that mechanically:

1. coverage_matrix — the evidence-and-gap-map move (Campbell/3ie): bucket the
   pool by concept block × time band; an empty or sparse cell that the block
   otherwise populates is a STRUCTURAL gap candidate, visible rather than
   argued. Assignment is BM25 per block (deterministic; the channel is
   reported so the agent knows paraphrase can misfile a paper).
2. mine_stated_gaps — institutions and authors publish their own limitations:
   fetch-archived fulltexts are scanned for limitation/future-work sentences.
   Each hit is a verbatim span with paper, section and cue — the agent cites
   it as gap evidence and `verify` can check the span like any other quote.
   Third-party testimony replaces inference-from-silence.
3. novelty_check — the SciMON move: before keeping a draft gap statement,
   score it against the pool (BM25, embedding blended when available). A
   close neighbor is mechanical refutation: the gap may already be done.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from citens.config import settings
from citens.models import Paper
from citens.screening import _paper_text, bm25_scores, embed_local

# ── 1. coverage matrix ─────────────────────────────────────────────────────


def year_bands(years: Sequence[int | None], n: int = 3) -> list[tuple[str, int, int]]:
    """n equal-width (lo, hi) bands over the pool's year range, oldest-first.

    With a 1998-2026 pool the bands read 1998-2007, 2008-2017, 2018-2026; a
    trailing sliver merges into the previous band so rounding never
    manufactures a one-year "era".
    """
    ys = [y for y in years if isinstance(y, int)]
    if not ys:
        return []
    lo, hi = min(ys), max(ys)
    span = max(1, -(-(hi - lo + 1) // n))
    edges: list[tuple[int, int]] = []
    start = lo
    while start <= hi:
        end = min(hi, start + span - 1)
        edges.append((start, end))
        start = end + 1
    if len(edges) >= 2 and (edges[-1][1] - edges[-1][0] + 1) * 2 < span:
        s0 = edges[-2][0]
        edges[-2:] = [(s0, edges[-1][1])]
    return [(f"{s}-{e}" if s != e else str(s), s, e) for s, e in edges]


def coverage_matrix(
    papers: Sequence[Paper], blocks: Sequence[str]
) -> dict:
    """Pool bucketed by concept block × time band; empty/sparse cells flagged.

    A paper joins the block its text scores highest against (BM25 per block,
    > 0 required — zero-matching papers land in `none` rather than being
    force-filed). Cells a block populates elsewhere but leaves empty here are
    structural gap candidates: the question is visible, not argued.
    """
    bs = [b.strip() for b in blocks if b and b.strip()]
    if not bs or not papers:
        return {"ok": False, "error": "pass papers and concept-block queries"}

    texts = [_paper_text(p) for p in papers]
    per_block = {b: bm25_scores(texts, b) for b in bs}
    bands = year_bands([p.year for p in papers])

    def _band(p: Paper) -> str:
        if not isinstance(p.year, int):
            return "?"
        for label, lo, hi in bands:
            if lo <= p.year <= hi:
                return label
        return "?"

    matrix: dict[str, dict[str, list[str]]] = {
        b: {label: [] for label, _, _ in bands} for b in bs
    }
    if bands:
        for row in matrix.values():
            row["?"] = []
    matrix["none"] = {label: [] for label, _, _ in bands} if bands else {"?": []}
    if bands:
        matrix["none"]["?"] = []

    for i, p in enumerate(papers):
        best_b, best_s = "none", 0.0
        for b in bs:
            s = per_block[b][i]
            if s > best_s:
                best_b, best_s = b, s
        matrix[best_b][_band(p)].append(p.title)

    counts = {
        b: {label: len(titles) for label, titles in row.items()}
        for b, row in matrix.items()
    }
    band_labels = [label for label, _, _ in bands] + (["?"] if bands else [])
    # the unknown-year band is metadata poverty, not a gap signal — it stays
    # in counts but never in the empty/sparse flags
    flag_labels = [label for label, _, _ in bands]
    empty_cells: list[dict] = []
    sparse_cells: list[dict] = []
    for b in bs:
        block_total = sum(counts[b].values())
        if block_total == 0:
            continue  # a block matching nothing is a query problem, not a gap
        for label in flag_labels:
            n = counts[b][label]
            if n == 0:
                empty_cells.append({"block": b, "band": label})
            elif n == 1:
                sparse_cells.append(
                    {"block": b, "band": label,
                     "only_paper": matrix[b][label][0][:100]}
                )
    return {
        "ok": True,
        "channel": "bm25 per block (deterministic; paraphrase can misfile)",
        "bands": band_labels,
        "blocks": bs,
        "counts": counts,
        "empty_cells": empty_cells,
        "sparse_cells": sparse_cells,
        "examples": {
            f"{b} | {label}": [t[:80] for t in titles[:2]]
            for b, row in matrix.items() for label, titles in row.items()
            if titles
        },
        "note": (
            "空/稀疏格是结构性 gap 候选（EGM 的矩阵空格逻辑），不是判决："
            "引用它前先读该块其他年代的论文确认不是检索词问题；"
            "block 全零说明查询没匹配上，属于 query_feedback 范畴。"
        ),
    }


# ── 2. stated-gap mining ───────────────────────────────────────────────────

_SECTION_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\s+|[IVXLC]+\.\s*)?"
    r"(limitations?|future work|future research|future directions?|conclusions?|"
    r"discussion|open (?:questions?|problems?|issues?)|threats to validity|"
    r"remaining challenges)\b.{0,60}$",
    re.IGNORECASE,
)
_CUE_RE = re.compile(
    r"future (?:work|research|stud(?:y|ies)|direction)"
    r"|remains? (?:unclear|open|unresolved|unexplored|to be)"
    r"|(?:has |have |are )?not been (?:studied|explored|examined|investigated|addressed)"
    r"|open (?:question|problem|challenge|issue)"
    r"|little (?:is known|attention|research|work)"
    r"|lack(?:s|ing)? of (?:evidence|research|studies|understanding|data)"
    r"|(?:we|researchers) (?:cannot|could not|fail(?:ed)? to)"
    r"|calls? for (?:further|additional|more)"
    r"|warrants? (?:further|additional)"
    r"|needs? to be (?:addressed|explored|studied)"
    r"|unanswered|under-explored|underexplored|open problem",
    re.IGNORECASE,
)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
# smoke-tested noise (2026-10-28, real pool): markdown table rows survive PDF
# conversion and cue-cross-references ("§8 discusses open questions") are
# pointers, not gap statements
_TABLE_LINE = re.compile(r"^\s*\|")
_XREF_RE = re.compile(r"§|see (?:section|chapter|appendix)|discussed in "
                      r"(?:section|appendix)|^\s*(?:cf\.|e\.g\.,?)\s", re.IGNORECASE)
_MAX_PER_PAPER = 5
_MIN_WORDS = 8


def mine_stated_gaps(
    fulltext_dir: Path, papers: Sequence[Paper], limit: int = 40
) -> dict:
    """Limitation/future-work sentences from fetch-archived fulltexts.

    Files are fetch's own naming (slugified title), so each hit maps back to
    a pool record; unmatched files are reported, not guessed. Every hit is a
    VERBATIM sentence — the agent quotes it as gap evidence and `verify`
    checks it like any other span.
    """
    d = Path(fulltext_dir)
    if not d.is_dir():
        return {"ok": False, "error": f"no fulltext dir at {d} (fetch core papers first)"}

    from citens.grounding.fulltext import slugify

    by_file = {f"{slugify(p.title)[:80]}.txt": p for p in papers}
    hits: list[dict] = []
    scanned = 0
    for f in sorted(d.glob("*.txt")):
        p = by_file.get(f.name)
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: S112, BLE001 — one unreadable file must not kill the scan
            continue
        scanned += 1
        section = ""
        n_this = 0
        for line in text.splitlines():
            m = _SECTION_RE.match(line.strip())
            if m and len(line.strip()) <= 80:
                section = m.group(1).lower()
                continue
            if _TABLE_LINE.match(line):
                continue
            if n_this >= _MAX_PER_PAPER:
                break
            for sent in _SENT_SPLIT.split(line.strip()):
                if n_this >= _MAX_PER_PAPER:
                    break
                s = sent.strip()
                if not (40 <= len(s) <= 400) or len(s.split()) < _MIN_WORDS:
                    continue
                if _XREF_RE.search(s):
                    continue
                cue = _CUE_RE.search(s)
                if not cue:
                    continue
                hits.append({
                    "title": p.title if p else f.name,
                    "doi": p.doi if p else None,
                    "text_file": str(f),
                    "section": section or "body",
                    "cue": cue.group(0).lower(),
                    "span": s[:400],
                })
                n_this += 1
                if len(hits) >= limit:
                    break
            if len(hits) >= limit:
                break
    return {
        "ok": True,
        "scanned_files": scanned,
        "matched_to_pool": sum(1 for h in hits if h["doi"] or h["title"] != ""),
        "hits": hits,
        "note": (
            "每条 span 是原文逐字句：引用为 gap 证据时走 [n] 纪律，"
            "verify 会核 span 是否在被引原文逐字出现。"
            "自陈局限是第三方证词，强于从沉默推测空白；"
            "但作者没写局限不等于没有局限。"
        ),
    }


# ── 3. novelty check ───────────────────────────────────────────────────────


def novelty_check(statement: str, papers: Sequence[Paper], k: int = 8,
                  model: str | None = None) -> dict:
    """A draft gap statement scored against the pool — nearest existing work.

    BM25 always fires (deterministic); the local embedding channel blends in
    when the extra is installed (0.6 semantic + 0.4 lexical, mirroring
    screen's weights). ``model=""`` disables the semantic channel outright —
    the zero-network test suite and offline runs must be able to force
    lexical-only, or the embedding stack's hub reachability can hang them.
    A close neighbor is mechanical refutation: the gap may already be done.
    No close neighbor is WEAK evidence of a gap — pair it with the coverage
    matrix, never ship it alone.
    """
    st = (statement or "").strip()
    if not st or not papers:
        return {"ok": False, "error": "pass a gap statement and a pool"}
    texts = [_paper_text(p) for p in papers]
    raw = bm25_scores(texts, st)
    mx = max(raw) if raw else 0.0
    lex = [r / mx if mx > 0 else 0.0 for r in raw]

    model_name = settings.screen_embedding_model if model is None else model.strip()
    sem: list[float] | None = None
    if model_name:
        sv = embed_local([st], model_name)
        pv = embed_local(texts, model_name)
        if sv and pv:
            qv = sv[0]
            sem = [sum(a * b for a, b in zip(qv, v, strict=False)) for v in pv]

    scored: list[tuple[float, Paper]] = []
    for i, p in enumerate(papers):
        s = 0.6 * sem[i] + 0.4 * lex[i] if sem is not None else lex[i]
        scored.append((max(0.0, s), p))
    scored.sort(key=lambda t: (-t[0], -(t[1].citation_count or 0)))
    top = scored[: max(1, k)]
    top_score = top[0][0]
    if top_score >= 0.7:
        verdict = (
            "高重叠：这个『空白』可能已被下面的文献做过——引用 gap 前先读它。"
        )
    elif top_score >= 0.4:
        verdict = "部分重叠：最相近的文献与陈述共享核心词，引用 gap 前先读它。"
    else:
        verdict = (
            "池内无近邻——注意这是弱证据（负证据证明力有限），"
            "请配合覆盖矩阵与自陈局限使用，不要单独当空白成立。"
        )
    return {
        "ok": True,
        "statement": st[:200],
        "channels": ["bm25"] + (["embedding"] if sem is not None else []),
        "neighbors": [
            {"score": round(s, 4), "title": p.title[:100], "doi": p.doi,
             "year": p.year, "citation_count": p.citation_count}
            for s, p in top
        ],
        "verdict": verdict,
    }
