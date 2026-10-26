"""Library management over the shared pools: duplicate reports, reading notes.

Two mechanical services the pool needs once it starts accumulating across
searches and agents:

* **Duplicate report.** The litdb pool is append-only, so the arXiv preprint
  and the published journal version of one study can sit in it as two records
  (search-time :func:`citens.search.base.deduplicate` catches them inside one
  run; ACROSS runs their keys differ — preprint keys on title, published keys
  on DOI). :func:`duplicate_groups` groups records by the same signals
  (exact DOI, arXiv id, fuzzy title plus a shared author) and
  :func:`dedup_pool` collapses a group the way ``_merge_variants`` does:
  the DOI-carrying record wins, pdf_url / abstract / found_by /
  matched_queries carry over, citations take the max.
* **Reading notes.** The agent's per-paper judgment (verdict + one-line note)
  persisted per topic as ``data/notes/<slug>.jsonl``. This is the judgment
  memory the recall loop consumes: ``expand --from-notes core`` seeds the
  citation expansion from papers the agent judged core — ASReview-style
  prioritization with no LLM inside the loop.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from citens.models import Paper
from citens.search.base import (
    _fuzzy_title,
    _merge_variants,
    _shared_author,
    paper_arxiv_id,
)

VERDICTS = ("core", "uncertain", "off")


def _norm_doi(doi: str | None) -> str:
    return (doi or "").strip().lower().removeprefix("https://doi.org/").removeprefix(
        "http://doi.org/"
    ).removeprefix("https://dx.doi.org/")


# --- duplicate groups ---------------------------------------------------------


def _signals(p: Paper) -> dict[str, str | None]:
    return {
        "doi": ("d:" + _norm_doi(p.doi)) if p.doi else None,
        "arxiv": ("a:" + aid) if (aid := paper_arxiv_id(p)) else None,
    }


def duplicate_groups(papers: list[Paper]) -> list[dict]:
    """Suspected duplicate groups (>=2 members) over a pool, report-only.

    Greedy single pass: a paper joins the first group it shares an exact
    signal (DOI / arXiv id) with, or where its fuzzy title matches a member
    AND the two share a surname — the same conservative rule the search-time
    dedup uses (a false merge is worse than a duplicate).
    """
    groups: list[dict] = []  # {"members": [Paper], "signals": set[str]}
    for p in papers:
        sig = _signals(p)
        target = None
        for g in groups:
            reasons: list[str] = []
            if sig["doi"] and any(
                _signals(m)["doi"] == sig["doi"] for m in g["members"]
            ):
                reasons.append("doi")
            if sig["arxiv"] and any(
                _signals(m)["arxiv"] == sig["arxiv"] for m in g["members"]
            ):
                reasons.append("arxiv")
            if any(
                _fuzzy_title(m.title) == _fuzzy_title(p.title) and _shared_author(m, p)
                for m in g["members"]
            ):
                reasons.append("title+author")
            if reasons:
                target = (g, reasons)
                break
        if target:
            g, reasons = target
            g["members"].append(p)
            g["signals"].update(reasons)
        else:
            groups.append({"members": [p], "signals": set()})
    out = []
    for g in groups:
        if len(g["members"]) < 2:
            continue
        out.append({
            "reasons": sorted(g["signals"] or {"title+author"}),
            "members": [
                {
                    "title": m.title,
                    "doi": m.doi,
                    "arxiv": paper_arxiv_id(m),
                    "year": m.year,
                    "citation_count": m.citation_count,
                    "source": m.source,
                }
                for m in g["members"]
            ],
        })
    return out


def dedup_pool(papers: list[Paper]) -> tuple[list[Paper], int]:
    """Collapse duplicate groups, keeping first-occurrence order.

    Returns (kept papers, number of records removed). Each group folds into
    ONE surviving record via ``_merge_variants`` (the DOI-carrying record's
    metadata wins; the preprint's pdf_url/abstract ride along) — the survivor
    may be any member object, so membership is tracked by group index, not by
    which object the fold returned.
    """
    groups: list[list[Paper]] = []
    group_of: dict[int, int] = {}  # id(paper) -> group index
    for p in papers:
        sig = _signals(p)
        target = None
        for g in groups:
            if (sig["doi"] and any(_signals(m)["doi"] == sig["doi"] for m in g)) or (
                sig["arxiv"] and any(_signals(m)["arxiv"] == sig["arxiv"] for m in g)
            ) or any(
                _fuzzy_title(m.title) == _fuzzy_title(p.title) and _shared_author(m, p)
                for m in g
            ):
                target = g
                break
        if target:
            target.append(p)
            group_of[id(p)] = groups.index(target)
        else:
            groups.append([p])
            group_of[id(p)] = len(groups) - 1
    merged: dict[int, Paper] = {}
    removed = 0
    for gi, g in enumerate(groups):
        if len(g) < 2:
            continue
        keep = g[0]
        for other in g[1:]:
            keep = _merge_variants(keep, other)
        merged[gi] = keep
        removed += len(g) - 1
    kept: list[Paper] = []
    emitted: set[int] = set()
    for p in papers:
        gi = group_of[id(p)]
        if gi in merged:
            if gi not in emitted:
                emitted.add(gi)
                kept.append(merged[gi])
        else:
            kept.append(p)
    return kept, removed


# --- reading notes ------------------------------------------------------------


def notes_path(topic: str) -> Path:
    """data/notes/<slug>.jsonl, sibling of the litdb pools."""
    from citens.collect import pool_path

    return pool_path(topic).parent.parent / "notes" / pool_path(topic).name


def _resolve_from_pool(topic: str, doi: str | None, title: str | None) -> Paper | None:
    from citens.collect import read_pool

    for p in read_pool(topic):
        if doi and _norm_doi(p.doi) == _norm_doi(doi):
            return p
        if title and " ".join((p.title or "").lower().split()) == " ".join(
            (title or "").lower().split()
        ):
            return p
    return None


def add_note(
    topic: str,
    *,
    doi: str | None = None,
    title: str | None = None,
    verdict: str = "core",
    note: str = "",
) -> dict:
    """Append one reading note for a paper (verdict + one-line judgment).

    The paper need not be in the pool (fetch-only papers get notes too); when
    it is, the record is enriched from the pool copy. Verdicts mirror the
    screen bands: core / uncertain / off.
    """
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {verdict!r}")
    if not (doi or title):
        raise ValueError("pass doi or title (the paper this note is about)")
    hit = _resolve_from_pool(topic, doi, title)
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "key": ("d:" + _norm_doi(doi)) if doi else "t:" + " ".join(
            (title or "").lower().split()
        ),
        "doi": _norm_doi(doi) or (hit.doi if hit else None),
        "title": (hit.title if hit else title) or "",
        "verdict": verdict,
        "note": note or "",
        "in_pool": hit is not None,
    }
    path = notes_path(topic)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def read_notes(
    topic: str, *, verdict: str | None = None, limit: int | None = None
) -> list[dict]:
    """The topic's reading notes, newest last; optional verdict filter."""
    path = notes_path(topic)
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001 — one bad line must not kill the log
            continue
        if verdict and rec.get("verdict") != verdict:
            continue
        out.append(rec)
    return out[-limit:] if limit else out
