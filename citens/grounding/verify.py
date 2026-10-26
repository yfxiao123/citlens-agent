"""Mechanical verification of a review's citations and claim verdicts — no LLM.

The writing half of CiteLens is the calling AGENT's job in this build, but
the *mechanical* half of the engine's verification chain does not need a
model and must not be left to prose discipline.  This module performs the
checks that are decidable from files:

* **Citation truth (honeypot).** Every ``[n]`` marker in the review must
  resolve to a reference entry, and every reference entry must resolve to a
  record in the literature pool (by DOI or normalized title).  A reference
  that resolves to nothing is a fabricated-or-unverifiable citation and is
  reported as such.
* **Reference hygiene.** A reference that is never cited is reported; a
  marker with no matching reference is reported.
* **Span grounding.** When the agent supplies per-claim verdicts, every
  verdict must quote a ``span`` from the cited paper's ground text.  The
  span is checked *verbatim* (whitespace/case normalized) against the fetched
  full text when present, otherwise against the abstract floor.  A span that
  does not occur in the source is a mismatch — the quote is a guess, not
  evidence.
* **Honesty arithmetic.** With verdicts present it computes the same block
  the engine's health check reports: citation precision (supported + partial
  over verifiable claims), unverifiable rate, full-text grounding ratio and
  papers cited / pool size.  The *agent* still judges; this module only
  counts what the agent recorded and checks it against the sources.

Verdict vocabulary is the engine's six-grade scale
(``Verdict`` in :mod:`citens.models`): supported / partial / background /
contradictory / unsupported / unverifiable.

Verdict file format (JSONL, one object per line; JSON array also accepted)::

    {"claim": "<exact claim sentence, markers included>",
     "verdict": "supported",
     "span": "<verbatim quote from the cited source>",
     "citations": [3, 7]}

``claim`` may also be given as ``text``; ``citations`` is optional (defaults
to the markers the parser found in that sentence).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from citens.grounding.citations import parse_claims_from_review
from citens.grounding.fulltext import slugify
from citens.models import Paper, Verdict

# --- vocabulary -------------------------------------------------------------

VERDICTS = {v.value for v in Verdict}
PASS_VERDICTS = {Verdict.SUPPORTED.value, Verdict.PARTIAL.value}
BAD_VERDICTS = {Verdict.UNSUPPORTED.value, Verdict.CONTRADICTORY.value}
WARN_VERDICTS = {Verdict.BACKGROUND.value}

_REF_HEADER_RE = re.compile(r"(?mi)^#{1,6}\s+.*(?:references|参考文献)\s*$")
_REF_ENTRY_RE = re.compile(r"^\s*\[(\d{1,3})\]\s+(.+?)\s*$")
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
_CITE_RE = re.compile(r"\[(\d{1,3})\]")
_WS_RE = re.compile(r"\s+")


# --- normalization ----------------------------------------------------------


def norm_space(text: str) -> str:
    """Collapse whitespace, strip, casefold — the comparison form for quotes."""
    return _WS_RE.sub(" ", (text or "")).strip().casefold()


def norm_title(text: str) -> str:
    """Lowercase alphanumeric tokens only — the comparison form for titles."""
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def norm_doi(doi: str | None) -> str:
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", (doi or "").strip().lower())


# --- review parsing ---------------------------------------------------------


def split_references(markdown: str) -> tuple[str, dict[int, str], int]:
    """Return (body, {n: raw reference text}, references-line-count).

    The references section starts at the LAST ``# ... References`` /
    ``# ... 参考文献`` heading and ends at the next heading of the same or
    higher level (or EOF).  Lines are parsed as ``[n] text``.
    """
    matches = list(_REF_HEADER_RE.finditer(markdown or ""))
    if not matches:
        return markdown or "", {}, 0
    start = matches[-1]
    body = (markdown or "")[: start.start()]
    tail = (markdown or "")[start.end():]
    stop = re.search(r"(?m)^#{1,6}\s+\S", tail)
    section = tail[: stop.start()] if stop else tail
    refs: dict[int, str] = {}
    for line in section.splitlines():
        m = _REF_ENTRY_RE.match(line)
        if m:
            n = int(m.group(1))
            refs.setdefault(n, m.group(2).strip())
    return body, refs, len(section.splitlines())


def _fallback_claims(body: str) -> list[dict]:
    """Sentence scan used when the review has no ``##`` sections at all."""
    out: list[dict] = []
    for chunk in re.split(r"(?<=[。！？])\s*|(?<=[.!?])\s+", body or ""):
        sentence = chunk.strip()
        if not sentence:
            continue
        indices = sorted({int(m) for m in _CITE_RE.findall(sentence)})
        if indices:
            out.append({"section": "", "claim": sentence, "citations": indices})
    return out


def parse_claims(markdown: str) -> list[dict]:
    """Sentences with at least one ``[n]`` marker, outside the references list."""
    body, _refs, _ = split_references(markdown)
    claims = parse_claims_from_review(body)
    if not claims:
        # parse_claims_from_review only walks text after a `##`/`###` heading;
        # a short review may have claims before any heading.
        raw = _fallback_claims(body)
    else:
        raw = [
            {"section": c.section, "claim": c.text, "citations": list(c.citation_indices)}
            for c in claims
        ]
    out: list[dict] = []
    for i, c in enumerate(raw, 1):
        out.append({"id": i, **c})
    return out


# --- reference -> pool resolution ------------------------------------------

_DOI_LIKE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)


def _best_title_match(ref_text: str, titles: Sequence[tuple[int, str]]) -> int | None:
    """Index into ``titles`` whose normalized title occurs inside the reference.

    ``titles`` is a list of (pool index, normalized title).  The LONGEST
    matching title wins — a short generic title is a weaker identification
    than a full descriptive one.  Requires ≥ 4 tokens to avoid matching a
    two-word fragment of a completely different work.
    """
    hay = norm_title(ref_text)
    if not hay:
        return None
    best, best_len = None, 0
    for idx, title in titles:
        if not title or title.count(" ") < 3:
            continue
        if title in hay and len(title) > best_len:
            best, best_len = idx, len(title)
    return best


def resolve_reference(ref_text: str, pool: Sequence[Paper]) -> dict:
    """Resolve one reference entry to a pool record.

    Returns ``{"index": pool_index|None, "how": "doi"|"title"|"none"}``.
    """
    doi = _DOI_RE.search(ref_text or "")
    if doi:
        wanted = norm_doi(doi.group(0))
        for i, p in enumerate(pool):
            if p.doi and norm_doi(p.doi) == wanted:
                return {"index": i, "how": "doi"}
    titles = [(i, norm_title(p.title)) for i, p in enumerate(pool)]
    idx = _best_title_match(ref_text, titles)
    if idx is not None:
        return {"index": idx, "how": "title"}
    return {"index": None, "how": "none"}


# --- ground text ------------------------------------------------------------


def _fulltext_candidates(paper: Paper, text_dir: Path) -> Iterable[Path]:
    if not text_dir or not text_dir.is_dir():
        return []
    slug = slugify(paper.title)[:80]
    if not slug:
        return []
    direct = text_dir / f"{slug}.txt"
    if direct.is_file():
        return [direct]
    try:
        return sorted(text_dir.glob(f"{slug}*.txt"))
    except OSError:
        return []


def ground_text(paper: Paper, text_dir: Path) -> tuple[str, bool]:
    """The paper's ground text and whether it is FULL TEXT (True) or abstract.

    The fetched-full-text filename is ``fulltext/<slug(title)[:80]>.txt``
    (written by ``fetch``); a missing file falls back to the stored abstract,
    which is the same floor the engine's verifier uses for abstract-only
    citations.
    """
    for path in _fulltext_candidates(paper, text_dir):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if text.strip():
            return text, True
    return (paper.abstract or ""), False


# --- verdicts ---------------------------------------------------------------


def load_verdicts(path: str | Path | None) -> list[dict]:
    """Read a verdicts JSONL (or JSON array) file; [] when not provided."""
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    raw = p.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = []
        return [d for d in data if isinstance(d, dict)]
    out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _verdict_key(entry: dict) -> str:
    return norm_space(str(entry.get("claim") or entry.get("text") or ""))


def _check_span(span: str, paper: Paper, text_dir: Path) -> dict:
    """Check one quoted span against one source paper's ground text."""
    text, is_fulltext = ground_text(paper, text_dir)
    out = {
        "paper": paper.title,
        "doi": paper.doi,
        "fulltext": is_fulltext,
        "has_ground_text": bool(text.strip()),
        "span_ok": False,
        "problem": "",
    }
    if not text.strip():
        out["problem"] = "no_ground_text"
        return out
    norm_span = norm_space(span)
    if len(norm_span) < 8:
        out["problem"] = "span_too_short"
        return out
    if norm_span in norm_space(text):
        out["span_ok"] = True
        return out
    out["problem"] = "span_not_found"
    return out


# --- main entry -------------------------------------------------------------


def verify_review(
    review_text: str,
    pool: Sequence[Paper],
    *,
    verdicts: Sequence[dict] | None = None,
    text_dir: str | Path | None = None,
    core_papers: int = 0,
    review_path: str | None = None,
    out_dir: str | Path | None = None,
    max_listed: int = 12,
) -> dict:
    """Run the mechanical verification chain and optionally write artifacts.

    ``clean`` is the gate the skill can trust: no dangling markers, no
    fabricated references, no missing/invalid verdicts, no span mismatch and
    no claim whose verdict contradicts the availability of ground text.
    """
    text_root = Path(text_dir) if text_dir else Path("fulltext")
    claims = parse_claims(review_text)
    _body, refs, _ref_lines = split_references(review_text)

    # -- references -> pool
    ref_rows: list[dict] = []
    ref_paper: dict[int, Paper] = {}
    unresolved_refs: list[int] = []
    for n in sorted(refs):
        res = resolve_reference(refs[n], pool)
        row = {
            "n": n,
            "reference": refs[n][:300],
            "in_pool": res["index"] is not None,
            "how": res["how"],
        }
        if res["index"] is not None:
            paper = pool[res["index"]]
            ref_paper[n] = paper
            row["doi"] = paper.doi
            row["title"] = paper.title
        else:
            unresolved_refs.append(n)
        ref_rows.append(row)

    # -- markers -> references
    cited: set[int] = set()
    markers_without_reference: list[int] = []
    claims_out: list[dict] = []
    for c in claims:
        missing = [n for n in c["citations"] if n not in refs]
        markers_without_reference.extend(missing)
        cited.update(n for n in c["citations"] if n in refs)
        claims_out.append(
            {
                "id": c["id"],
                "section": c["section"],
                "claim": c["claim"],
                "citations": c["citations"],
                "missing_reference": missing,
                "resolved": [],
            }
        )

    uncited_refs = [n for n in sorted(refs) if n not in cited]

    # -- verdicts: match, validate, span-check
    verdict_list = list(verdicts or [])
    by_key: dict[str, dict] = {}
    unmatched_verdicts: list[dict] = []
    for v in verdict_list:
        key = _verdict_key(v)
        if not key:
            unmatched_verdicts.append({"reason": "empty claim", "verdict": v.get("verdict")})
            continue
        by_key.setdefault(key, v)

    problems: list[str] = []
    span_ok = span_mismatch = no_ground = invalid_verdict = unverifiable_with_text = 0
    unresolved_source = 0
    counts: dict[str, int] = {v: 0 for v in sorted(VERDICTS)}
    claims_without_verdict = 0
    verdict_checks: list[dict] = []

    for c in claims_out:
        ckey = norm_space(c["claim"])
        v = by_key.pop(ckey, None)
        if v is None:
            claims_without_verdict += 1
            c["verdict"] = None
            continue
        value = str(v.get("verdict") or "").strip().lower()
        span = str(v.get("span") or "").strip()
        cites = v.get("citations")
        if not isinstance(cites, list) or not cites:
            cites = c["citations"]
        c["citations"] = [int(x) for x in cites if isinstance(x, (int, str)) and str(x).isdigit()]

        check = {
            "claim_id": c["id"],
            "verdict": value,
            "span": span[:400],
            "sources": [],
            "valid": value in VERDICTS,
            "problems": [],
        }
        if value not in VERDICTS:
            invalid_verdict += 1
            check["problems"].append("invalid_verdict")
            problems.append(f"claim {c['id']}: invalid verdict {value!r}")
        else:
            counts[value] += 1

        cited_papers: list[Paper] = []
        seen_ids: set[str] = set()
        for n in c["citations"]:
            p = ref_paper.get(int(n)) if str(n).isdigit() else None
            if p is not None and p.id not in seen_ids:
                seen_ids.add(p.id)
                cited_papers.append(p)
        if not cited_papers:
            check["problems"].append("no_resolved_source")
            unresolved_source += 1
            problems.append(f"claim {c['id']}: no cited reference resolves to the pool")
        else:
            checked = [_check_span(span, p, text_root) for p in cited_papers]
            check["sources"] = checked
            if value == Verdict.UNVERIFIABLE.value:
                if any(s["has_ground_text"] for s in checked):
                    check["problems"].append("unverifiable_but_ground_text_exists")
                    unverifiable_with_text += 1
                    problems.append(
                        f"claim {c['id']}: marked unverifiable but ground text exists"
                    )
            else:
                if not any(s["span_ok"] for s in checked):
                    if not any(s["has_ground_text"] for s in checked):
                        check["problems"].append("no_ground_text")
                        no_ground += 1
                        problems.append(f"claim {c['id']}: no ground text for a verifiable claim")
                    else:
                        check["problems"].append("span_not_found")
                        span_mismatch += 1
                        problems.append(f"claim {c['id']}: quoted span not found in source")
                else:
                    span_ok += 1
                    check["span_ok"] = True

        c["verdict"] = value
        c["span"] = span
        c["checks"] = check
        verdict_checks.append(check)

    for leftover in by_key.values():
        unmatched_verdicts.append(
            {"claim": str(leftover.get("claim") or leftover.get("text") or "")[:200],
             "verdict": leftover.get("verdict")}
        )
    if claims_without_verdict:
        problems.append(f"{claims_without_verdict} claim(s) have no verdict")
    for n in markers_without_reference:
        problems.append(f"marker [{n}] has no reference entry")
    for n in unresolved_refs:
        problems.append(f"reference [{n}] does not resolve to a pool record")
    for n in uncited_refs:
        problems.append(f"reference [{n}] is never cited")

    # -- honesty block (same arithmetic as the engine's health check)
    total_claims = len(claims_out)
    verifiable = [k for k in verdict_checks if k["verdict"] in VERDICTS
                  and k["verdict"] != Verdict.UNVERIFIABLE.value
                  and "no_resolved_source" not in (k.get("problems") or [])]
    passed = sum(1 for k in verifiable if k["verdict"] in PASS_VERDICTS)
    unverifiable = counts.get(Verdict.UNVERIFIABLE.value, 0)
    precision = (passed / len(verifiable)) if verifiable else 0.0
    unverifiable_rate = (unverifiable / total_claims) if total_claims else 0.0

    cited_papers: list[Paper] = []
    seen_titles: set[str] = set()
    for n in sorted(ref_paper):
        paper = ref_paper[n]
        key = paper.id or paper.title
        if key in seen_titles:
            continue
        seen_titles.add(key)
        cited_papers.append(paper)
    with_fulltext = sum(1 for p in cited_papers if ground_text(p, text_root)[1])
    core = int(core_papers) if int(core_papers or 0) > 0 else len(cited_papers)
    grounding = (with_fulltext / core) if core else 0.0

    honesty = {
        "claims_total": total_claims,
        "verdicts_provided": len(verdict_list),
        "verdicts_matched": len(verdict_checks),
        "claims_without_verdict": claims_without_verdict,
        "verdicts": {k: v for k, v in counts.items() if v},
        "citation_precision": round(precision, 3),
        "unverifiable_rate": round(unverifiable_rate, 3),
        "grounding": round(grounding, 3),
        "with_fulltext": with_fulltext,
        "core_papers": core,
        "papers_cited": len(cited_papers),
        "pool_size": len(pool),
        "refs_total": len(refs),
        "refs_in_pool": len(refs) - len(unresolved_refs),
        "refs_not_in_pool": len(unresolved_refs),
        "markers_without_reference": len(markers_without_reference),
        "uncited_references": len(uncited_refs),
        "span_ok": span_ok,
        "span_mismatch": span_mismatch,
        "no_ground_text": no_ground,
        "unverifiable_with_text": unverifiable_with_text,
        "unresolved_source_claims": unresolved_source,
        "invalid_verdicts": invalid_verdict,
    }

    structural_problems = (
        bool(unresolved_refs)
        or bool(markers_without_reference)
        or invalid_verdict > 0
        or span_mismatch > 0
        or no_ground > 0
        or unverifiable_with_text > 0
    )
    clean = not structural_problems and (
        not verdict_list or (claims_without_verdict == 0 and not unmatched_verdicts)
    )

    result: dict[str, Any] = {
        "ok": True,
        "review": review_path,
        "claims": total_claims,
        "references": len(refs),
        "pool": len(pool),
        "citations": {
            "in_pool": len(refs) - len(unresolved_refs),
            "not_in_pool": unresolved_refs[:max_listed],
            "not_in_pool_count": len(unresolved_refs),
            "markers_without_reference": sorted(set(markers_without_reference))[:max_listed],
            "uncited_references": uncited_refs[:max_listed],
            "uncited_count": len(uncited_refs),
            "references": ref_rows[:max_listed],
        },
        "verdicts": {
            "provided": len(verdict_list),
            "matched": len(verdict_checks),
            "unmatched": unmatched_verdicts[:max_listed],
            "missing_for_claims": claims_without_verdict,
            "counts": {k: v for k, v in counts.items() if v},
        },
        "checks": {
            "span_ok": span_ok,
            "span_mismatch": span_mismatch,
            "no_ground_text": no_ground,
            "invalid_verdicts": invalid_verdict,
            "problems": problems[: max_listed * 4],
            "problem_count": len(problems),
        },
        "honesty": honesty,
        "clean": bool(clean),
        "artifacts": {},
        "note": (
            "Mechanical checks only: citation→pool resolution, marker/reference "
            "integrity and verbatim span matching against fetched full text "
            "(abstract floor otherwise). It does NOT judge whether the claim is "
            "supported — that is the agent's reading; it only verifies that the "
            "recorded verdict is well-formed and its quoted span exists in the "
            "cited source. clean=false must be fixed before delivery; a verifiable "
            "claim with no ground text must be downgraded to unverifiable."
        ),
    }

    if out_dir:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        vpath = out / "verification.jsonl"
        with vpath.open("w", encoding="utf-8") as fh:
            for c in claims_out:
                fh.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")
        hpath = out / "honesty.json"
        hpath.write_text(json.dumps(honesty, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        result["artifacts"] = {
            "verification_jsonl": str(vpath),
            "honesty_json": str(hpath),
        }
    return result
