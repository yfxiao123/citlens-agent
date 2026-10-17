#!/usr/bin/env python
"""citlens_tools.py — the synchronous I/O tools behind fetch / export / audit.

The review pipeline in the engine repo was LLM end-to-end. In this build the
AGENT is the writer and the verifier — but it still needs the same three
mechanical services that pipeline had, and they are all pure I/O:

    fetch   grounding substrate: arXiv -> S2 -> OpenAlex -> Unpaywall -> CORE
            open-access PDF hunt, MarkItDown conversion, cached. Abstract
            returned as fallback so an unfetchable paper can still be cited,
            but only as abstract-only.
    export  BibTeX / RIS from a pool (topic or run directory), via the same
            CitationTable the engine used — no invented fields.
    audit   recall-vs-reality: how much of the top surveys' bibliographies
            the pool already covers (the stage-F anchor check).

Every subcommand prints exactly one JSON document on stdout. Run from the
data home with this repo's interpreter, like citlens_recall.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from citens.collect import audit_recall, pool_path, read_pool  # noqa: E402
from citens.grounding.citations import CitationTable  # noqa: E402
from citens.grounding.fulltext import fetch_fulltext, slugify  # noqa: E402
from citens.models import Paper  # noqa: E402


def _log(msg: str) -> None:
    try:
        print(f"[citlens-tools] {msg}", flush=True, file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def _load_papers(topic: str | None, run_dir: str | None) -> tuple[list[Paper], str]:
    """Resolve a pool by run directory (preferred) or topic slug."""
    if run_dir:
        path = Path(run_dir) / "pool.jsonl"
        if not path.is_file():
            return [], f"no pool.jsonl under {run_dir}"
    elif topic:
        path = pool_path(topic)
        if not path.is_file():
            return [], f"no pool for topic {topic!r} (expected {path}); run a search first"
    else:
        return [], "pass --run-dir or --topic"
    papers: list[Paper] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(rec, dict) and rec.get("title"):
            papers.append(Paper(**{k: v for k, v in rec.items()
                                   if k in Paper.model_fields}))
    return papers, str(path)


def _match(papers: list[Paper], doi: str | None, title: str | None) -> Paper | None:
    if doi:
        d = doi.strip().lower().removeprefix("https://doi.org/")
        for p in papers:
            if (p.doi or "").lower() == d:
                return p
    if title:
        t = " ".join((title or "").lower().split())
        for p in papers:
            if " ".join((p.title or "").lower().split()) == t:
                return p
    return None


# ── fetch ─────────────────────────────────────────────────────────────────────


def cmd_fetch(args) -> dict:
    papers, where = _load_papers(args.topic, args.run_dir)
    paper = _match(papers, args.doi, args.title) if papers else None
    if paper is None:
        # No pool to resolve from (or no match): build a minimal record.
        # Paper carries arXiv identity via url/doi (10.48550/arXiv.<id>) —
        # exactly what _arxiv_pdf_url greps for.
        arxiv = (args.arxiv or "").strip()
        paper = Paper(
            title=(args.title or args.doi or arxiv or "").strip(),
            authors=[], year=None,
            doi=args.doi or (f"10.48550/arXiv.{arxiv}" if arxiv else None),
            url=f"https://arxiv.org/abs/{arxiv}" if arxiv else None,
        )
    out: dict = {
        "title": paper.title,
        "doi": paper.doi,
        "year": paper.year,
        "citation_count": paper.citation_count,
        "abstract": (paper.abstract or "")[:1200] or None,
        "resolved_from_pool": bool(papers) and paper in papers,
    }
    if not paper.title and not paper.doi and not paper.arxiv:
        return {"ok": False, "error": "pass --doi, --title or --arxiv "
                "(plus --topic/--run-dir to resolve from a pool)"}
    try:
        text = fetch_fulltext(paper)
    except Exception as e:  # noqa: BLE001 — a dead source must not kill the tool
        text = None
        out["fetch_error"] = str(e)[:200]
    if text:
        out_dir = Path(args.text_dir or "fulltext")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{slugify(paper.title)[:80]}.txt"
        path.write_text(text, encoding="utf-8")
        out.update(
            fulltext=True, chars=len(text), text_path=str(path),
            head=text[:1500],
            note="全文已取回。逐条主张核验必须对着 text_path 的原文做；"
                 "引用页码/章节时给出可核对的定位。",
        )
    else:
        out.update(
            fulltext=False, text_path=None,
            note="拿不到开放获取全文——该论文只能以【仅摘要级】引用："
                 "主张限于摘要明说的内容，并在成稿的 grounding 块里如实计数。",
        )
    out["ok"] = True
    return out


# ── export ────────────────────────────────────────────────────────────────────


def cmd_export(args) -> dict:
    papers, where = _load_papers(args.topic, args.run_dir)
    if not papers:
        return {"ok": False, "error": where}
    table = CitationTable(papers)
    fmt = (args.format or "bib").lower()
    content = table.to_bibtex() if fmt == "bib" else table.to_ris()
    if args.out:
        path = Path(args.out)
    else:
        base = Path(args.run_dir) if args.run_dir else Path("exports")
        path = base / f"references.{fmt}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {
        "ok": True, "format": fmt, "count": len(table), "path": str(path),
        "labels_md": table.references_md() if args.with_labels else None,
        "note": "字段缺失就留空，绝不编造——和引擎同一张 CitationTable 序列化。",
    }


# ── audit ─────────────────────────────────────────────────────────────────────


def cmd_audit(args) -> dict:
    try:
        out = audit_recall(args.topic, top_reviews=args.top_reviews)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"audit failed: {e}"}
    out["ok"] = True
    out["note"] = (
        "coverage = 池子覆盖 top 综述参考文献的比例（外部锚点）。"
        "收工判据见 SKILL.md 阶段 F：coverage 低或 reviews_checked=0 时不得声明覆盖。"
    )
    return out


def main(argv=None) -> int:
    _force_utf8_stdio()
    ap = argparse.ArgumentParser(description="CiteLens synchronous I/O tools")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="取一篇论文的开放获取全文（或摘要兜底）")
    p_fetch.add_argument("--doi")
    p_fetch.add_argument("--title")
    p_fetch.add_argument("--arxiv")
    p_fetch.add_argument("--topic", help="从该主题的池子里解析记录")
    p_fetch.add_argument("--run-dir", help="从该 run 目录的 pool.jsonl 解析记录")
    p_fetch.add_argument("--text-dir", default="fulltext", help="全文文本落盘目录")

    p_export = sub.add_parser("export", help="把池子导出为 BibTeX/RIS")
    p_export.add_argument("--topic")
    p_export.add_argument("--run-dir")
    p_export.add_argument("--format", choices=["bib", "ris"], default="bib")
    p_export.add_argument("--out", help="输出文件路径（默认 run 目录或 exports/ 下）")
    p_export.add_argument("--with-labels", action="store_true", help="附带 [n] APA 标签清单")

    p_audit = sub.add_parser("audit", help="池子对 top 综述参考文献的覆盖审计")
    p_audit.add_argument("--topic", required=True)
    p_audit.add_argument("--top-reviews", type=int, default=3)

    args = ap.parse_args(argv)
    fn = {"fetch": cmd_fetch, "export": cmd_export, "audit": cmd_audit}[args.cmd]
    try:
        payload = fn(args)
    except Exception as e:  # noqa: BLE001
        payload = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(payload, ensure_ascii=False, indent=1, default=str))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
