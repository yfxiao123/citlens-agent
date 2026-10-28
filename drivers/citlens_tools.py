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
    verify  mechanical review verification (no LLM): citation truth via the
            pool (honeypot), verbatim span grounding, six-grade verdict
            validation and the honesty block (see citens/grounding/verify.py).

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
from citens.grounding.verify import load_verdicts, verify_review  # noqa: E402
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
    content = (
        table.to_bibtex() if fmt == "bib"
        else table.to_ris() if fmt == "ris"
        else table.to_endnote_xml() if fmt == "endnote"
        else table.to_csl_json()
    )
    ext = {"bib": "bib", "ris": "ris", "endnote": "xml", "csljson": "json"}[fmt]
    if args.out:
        path = Path(args.out)
    else:
        base = Path(args.run_dir) if args.run_dir else Path("exports")
        path = base / f"references.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {
        "ok": True, "format": fmt, "count": len(table), "path": str(path),
        "labels_md": table.references_md() if args.with_labels else None,
        "note": "字段缺失就留空，绝不编造——和引擎同一张 CitationTable 序列化。",
    }


# ── screen ────────────────────────────────────────────────────────────────────


def cmd_screen(args) -> dict:
    """Relevance triage over a pool: score every record against the query set
    (semantic + lexical + consensus channels) and band it core / uncertain /
    likely_off. Triage, never judgment — nothing is excluded here."""
    papers, where = _load_papers(args.topic, args.run_dir)
    if not papers:
        return {"ok": False, "error": where}
    queries = [q for q in (args.queries or []) if q.strip()]
    if not queries:
        # The agent should pass its concept-block queries; without them fall
        # back to the queries that actually found these records (deduped,
        # field-constrained suffixes stripped) — honest, and reported as such.
        seen: list[str] = []
        for p in papers:
            for q in p.matched_queries:
                base = q.split(" (")[0].strip()
                if base and base not in seen:
                    seen.append(base)
        queries = seen[:12]
        fallback_note = (
            "未传 --queries：已退回 matched_queries（找到这些记录的查询）——"
            "最好传你自己的概念块查询重跑一次"
        )
    else:
        fallback_note = ""
    from citens.screening import screen_papers

    if args.run_dir:
        out_path = Path(args.run_dir) / "screening.jsonl"
    elif args.topic:
        from citens.collect import pool_path

        out_path = pool_path(args.topic).with_suffix(".screening.jsonl")
    else:
        out_path = None
    out = screen_papers(
        papers,
        queries,
        model=args.model,
        core_threshold=args.core,
        off_threshold=args.off,
        out_path=None if args.no_write else out_path,
        limit=args.limit,
    )
    if fallback_note:
        out["fallback_note"] = fallback_note
    out["ok"] = True
    return out


# ── gaps ─────────────────────────────────────────────────────────────────────


def cmd_gaps(args) -> dict:
    """Mechanical substrate for the 找 movement: coverage matrix (EGM-style
    structural gap candidates), stated-gap mining (verbatim limitation/
    future-work sentences from fetched fulltexts), novelty check (a draft gap
    statement scored against the pool — nearest existing work as mechanical
    refutation). All channels opt-in; all zero LLM."""
    papers, where = _load_papers(args.topic, args.run_dir)
    if not papers:
        return {"ok": False, "error": where}
    qs = [q for q in (args.queries or []) if q.strip()]
    check = (args.check or "").strip()
    if not qs and not check and not args.mine:
        return {"ok": False, "error": "pass --queries (coverage matrix), "
                "--check (novelty check) and/or --mine (stated gaps) — all optional"}
    out: dict = {"ok": True, "n": len(papers)}
    from citens.gapfinding import coverage_matrix, mine_stated_gaps, novelty_check

    if qs:
        out["coverage"] = coverage_matrix(papers, qs)
    if check:
        out["novelty"] = novelty_check(check, papers, k=args.limit or 8)
    if args.mine:
        out["stated_gaps"] = mine_stated_gaps(
            Path(args.fulltext_dir), papers, limit=args.limit or 40
        )
    return out


# ── verify ────────────────────────────────────────────────────────────────────


def cmd_verify(args) -> dict:
    """Mechanical citation/verdict verification for a written review.

    Decidable-from-files checks only: markers→references, references→pool
    (honeypot), and each agent verdict's quoted span against the cited
    source's fetched full text (abstract floor otherwise). No LLM.
    """
    review_path = Path(args.review).expanduser()
    if not review_path.is_file():
        return {"ok": False, "error": f"review not found: {review_path}"}
    try:
        review_text = review_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "error": f"cannot read review: {e}"}

    papers: list[Paper] = []
    pool_source = ""
    if args.topic or args.run_dir:
        papers, pool_source = _load_papers(args.topic, args.run_dir)
        if not papers:
            pool_source = pool_source or "no pool found"

    verdicts = load_verdicts(args.verdicts) if args.verdicts else []
    text_dir = Path(args.text_dir or "fulltext")
    out_dir = Path(args.out) if args.out else review_path.parent / "verification"
    out = verify_review(
        review_text,
        papers,
        verdicts=verdicts,
        text_dir=text_dir,
        core_papers=args.core_papers,
        review_path=str(review_path),
        out_dir=out_dir,
    )
    out["pool_source"] = pool_source or "not loaded (pass --topic or --run-dir to resolve citations)"
    if not papers:
        out.setdefault("notes", []).append(
            "no pool loaded: every reference will be reported as not-in-pool. "
            "Pass --topic (byte-identical to the search topic) or --run-dir."
        )
    if not verdicts:
        out.setdefault("notes", []).append(
            "no verdicts file: citation truth was checked, but span/precision checks need "
            "a verdicts JSONL (see SKILL.md)."
        )
    return out


# ── expand ────────────────────────────────────────────────────────────────────


def cmd_expand(args) -> dict:
    """Judgment feedback loop: expand the topic pool around agent-picked seeds
    (citation chaining + S2 recommendations). Triage, never judgment."""
    import asyncio

    from citens.search.expand import expand_from_seeds

    seeds = [s for s in (args.seeds or []) if s.strip()]
    directions = {d.strip() for d in args.directions.split(",") if d.strip()}
    from_notes = 0
    if args.from_notes:
        # judgment feedback: the topic's own reading notes become seeds —
        # `expand --from-notes core` expands around everything YOU judged core
        from citens.library import read_notes

        seen = {s.strip().lower() for s in seeds}
        for n in read_notes(args.topic, verdict=args.from_notes):
            seed = n.get("doi") or n.get("title")
            if seed and seed.strip().lower() not in seen:
                seen.add(seed.strip().lower())
                seeds.append(seed)
                from_notes += 1
    if not seeds:
        return {"ok": False, "error": "pass --seeds (DOIs / arXiv ids / titles of papers you judged on-topic)"
                " or --from-notes core (expand around your judged-core notes)"}
    directions = {d.strip() for d in args.directions.split(",") if d.strip()}
    pool = read_pool(args.topic)  # may be empty — expansion can seed a new topic
    existing = {p.id for p in pool}
    result = asyncio.run(expand_from_seeds(
        seeds, existing,
        directions=directions,
        relevance_terms=[args.topic],
        limit_per_paper=args.limit_per_paper,
        top=args.top,
    ))
    added = 0
    if not args.no_write and result["papers"]:
        from citens.collect import append_pool

        added = append_pool(args.topic, result["papers"])
    compact = [
        {"title": p.title, "year": p.year, "doi": p.doi,
         "citation_count": p.citation_count, "source": p.source}
        for p in result["papers"][:args.top]
    ]
    return {
        "ok": True,
        "topic": args.topic,
        "seeds": seeds,
        "seeds_from_notes": from_notes,
        "resolved": result["anchors"],
        "unresolved": result["unresolved"],
        "counts": {**result["counts"], "appended_to_pool": added,
                   "pool_size_before": len(pool)},
        "papers": compact,
        "note": (
            "邻域扩展不是切题认定：新记录只带 found_by=[expand] 入池，"
            "仍需 screen 分流 + 你逐篇判断（PRISMA 排除照记 exclusions.jsonl）。"
            "命中过低时换种子或补方向（--directions recs 只跑相似推荐）。"
        ),
    }


# ── dedup ─────────────────────────────────────────────────────────────────────


def cmd_dedup(args) -> dict:
    """Duplicate report over a pool; --merge (topic pools only) collapses the
    groups into their DOI-carrying survivor, with a .bak written first."""
    from citens.library import dedup_pool, duplicate_groups

    papers, where = _load_papers(args.topic, args.run_dir)
    if not papers:
        return {"ok": False, "error": where}
    groups = duplicate_groups(papers)
    out: dict = {
        "ok": True,
        "total": len(papers),
        "groups": len(groups),
        "collapsed_records": sum(len(g["members"]) - 1 for g in groups),
        "duplicates": groups[:args.limit],
        "merge": False,
    }
    if args.merge and groups:
        if not args.topic:
            return {
                "ok": False,
                "error": "--merge needs --topic (run-directory pools are immutable "
                         "artifacts of that search; re-run search instead)",
                "groups": len(groups),
            }
        from citens.collect import pool_path, read_pool

        path = pool_path(args.topic)
        kept, removed = dedup_pool(read_pool(args.topic))
        if removed and path.is_file():
            bak = path.with_suffix(".jsonl.bak")
            bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            with path.open("w", encoding="utf-8") as fh:
                for p in kept:
                    fh.write(json.dumps(p.model_dump(), ensure_ascii=False) + "\n")
        out.update(merge=True, removed=removed, pool_after=len(kept),
                   backup=str(bak) if removed else None)
    out["note"] = (
        "报告只指出嫌疑组（doi / arxiv / 题名+共作者三种信号）；要不要合并由你决定。"
        "--merge 只对主题池生效，合并前写 .bak，被合并记录的 pdf_url/摘要/found_by "
        "会并入保留记录。"
    )
    return out


# ── notes ─────────────────────────────────────────────────────────────────────


def cmd_notes(args) -> dict:
    """Reading notes: record per-paper verdicts (core/uncertain/off) + a
    one-line judgment; list them back. Feeds `expand --from-notes`."""
    from citens.library import VERDICTS, add_note, notes_path, read_notes

    if args.verdict and args.verdict not in VERDICTS:
        return {"ok": False, "error": f"verdict must be one of {VERDICTS}"}
    if args.doi or args.title:
        if not args.note:
            return {"ok": False, "error": "adding a note needs --note (your one-line judgment)"}
        try:
            rec = add_note(
                args.topic, doi=args.doi, title=args.title,
                verdict=args.verdict or "core", note=args.note,
            )
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {
            "ok": True, "added": rec, "path": str(notes_path(args.topic)),
            "note": "判定已落盘。core 判定会被 expand --from-notes core 直接当种子用。",
        }
    notes = read_notes(args.topic, verdict=args.verdict, limit=args.limit)
    by_verdict: dict[str, int] = {}
    for n in notes:
        by_verdict[n.get("verdict", "?")] = by_verdict.get(n.get("verdict", "?"), 0) + 1
    return {
        "ok": True, "topic": args.topic, "count": len(notes),
        "by_verdict": by_verdict, "notes": notes,
        "path": str(notes_path(args.topic)),
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
    p_export.add_argument("--format", choices=["bib", "ris", "endnote", "csljson"],
                          default="bib")
    p_export.add_argument("--out", help="输出文件路径（默认 run 目录或 exports/ 下）")
    p_export.add_argument("--with-labels", action="store_true", help="附带 [n] APA 标签清单")

    p_dedup = sub.add_parser(
        "dedup", help="文献池去重报告（doi/arxiv/题名+共作者三信号）；--merge 合并（仅主题池，先备份）")
    p_dedup.add_argument("--topic")
    p_dedup.add_argument("--run-dir")
    p_dedup.add_argument("--merge", action="store_true",
                         help="把嫌疑组合并成 DOI 承载的保留记录（仅 --topic；写 .bak）")
    p_dedup.add_argument("--limit", type=int, default=20, help="返回的组数上限")

    p_notes = sub.add_parser(
        "notes", help="阅读笔记：逐篇判定（core/uncertain/off）+ 一句话理由，落盘并可回流 expand")
    p_notes.add_argument("--topic", required=True)
    p_notes.add_argument("--doi", help="添加模式：论文 DOI")
    p_notes.add_argument("--title", help="添加模式：论文标题")
    p_notes.add_argument("--verdict", choices=["core", "uncertain", "off"],
                         help="判定（添加模式默认 core）")
    p_notes.add_argument("--note", help="一句话判定理由")
    p_notes.add_argument("--limit", type=int, default=50, help="列表模式返回条数")

    p_audit = sub.add_parser("audit", help="池子对 top 综述参考文献的覆盖审计")
    p_audit.add_argument("--topic", required=True)
    p_audit.add_argument("--top-reviews", type=int, default=3)

    p_screen = sub.add_parser(
        "screen", help="相关性三分带分流（core / uncertain / likely_off）——分流不是判决"
    )
    p_screen.add_argument("--topic", help="主题池（data/litdb/<slug>.jsonl）")
    p_screen.add_argument("--run-dir", help="run 目录（读其 pool.jsonl）")
    p_screen.add_argument("--queries", nargs="+", default=[],
                          help="agent 概念块英文查询（强烈建议传；缺省退回 matched_queries）")
    p_screen.add_argument("--model", default=None,
                          help="本地嵌入模型（默认取 SCREEN_EMBEDDING_MODEL；空串禁用语义通道）")
    p_screen.add_argument("--core", type=float, default=None, help="core 带阈值（默认 0.5）")
    p_screen.add_argument("--off", type=float, default=None, help="likely_off 带阈值（默认 0.32）")
    p_screen.add_argument("--limit", type=int, default=30, help="返回条数上限")
    p_screen.add_argument("--no-write", action="store_true", help="不写 screening.jsonl")

    p_gaps = sub.add_parser(
        "gaps", help="「找」的机械基底：覆盖矩阵（结构 gap 候选）/ 自陈空白挖掘 / novelty check"
    )
    p_gaps.add_argument("--topic", help="主题池（data/litdb/<slug>.jsonl）")
    p_gaps.add_argument("--run-dir", help="run 目录（读其 pool.jsonl）")
    p_gaps.add_argument("--queries", nargs="+", default=[],
                        help="概念块英文查询——按块×年代生成覆盖矩阵")
    p_gaps.add_argument("--check", help="gap 陈述草稿：对池子找最近邻已有工作")
    p_gaps.add_argument("--mine", action="store_true",
                        help="从 fetch 全文目录挖掘 limitations/future work 原句")
    p_gaps.add_argument("--fulltext-dir", default="fulltext", help="全文目录（默认 fulltext）")
    p_gaps.add_argument("--limit", type=int, default=40, help="novelty/stated-gaps 返回上限")

    p_expand = sub.add_parser(
        "expand",
        help="判断反馈环：以你判定的种子论文为中心做引文链 + S2 相似推荐扩展",
    )
    p_expand.add_argument("--topic", required=True,
                          help="并入的主题池（data/litdb/<slug>.jsonl；可为空池——直接从种子起步）")
    p_expand.add_argument("--seeds", nargs="+", default=[],
                          help="种子：DOI / arXiv id / 标题（你判过切题的论文）")
    p_expand.add_argument("--from-notes", nargs="?", const="core", default=None,
                          metavar="VERDICT",
                          help="从阅读笔记取种子（默认 core；与 --seeds 可同用、去重合并）")
    p_expand.add_argument("--directions", default="backward,forward,related,recs",
                          help="逗号分隔方向：backward,forward,related,recs（默认全部）")
    p_expand.add_argument("--limit-per-paper", type=int, default=20,
                          help="每个种子每个方向最多取几条")
    p_expand.add_argument("--top", type=int, default=30, help="返回/入池上限")
    p_expand.add_argument("--no-write", action="store_true", help="只返回结果，不并入池子")

    p_verify = sub.add_parser(
        "verify",
        help="机械核验综述引用与判定：marker→参考文献→池（蜜罐）+ span 原文核对 + 诚实数字",
    )
    p_verify.add_argument("--review", required=True, help="综述 markdown 路径（正文 + [n] 参考文献）")
    p_verify.add_argument("--topic", help="主题池（解析参考文献用；与检索 topic 逐字相同）")
    p_verify.add_argument("--run-dir", help="run 目录（读其 pool.jsonl）")
    p_verify.add_argument("--verdicts", help="agent 判定的 JSONL（claim/verdict/span[/citations]）")
    p_verify.add_argument("--text-dir", default="fulltext", help="fetch 全文落盘目录（默认 fulltext）")
    p_verify.add_argument("--out", help="产物目录（默认 <review 所在目录>/verification）")
    p_verify.add_argument("--core-papers", type=int, default=0,
                          help="精读论文数（grounding 分母；缺省=被引池内论文数）")

    args = ap.parse_args(argv)
    fn = {"fetch": cmd_fetch, "export": cmd_export, "audit": cmd_audit,
          "screen": cmd_screen, "verify": cmd_verify, "expand": cmd_expand,
          "dedup": cmd_dedup, "notes": cmd_notes, "gaps": cmd_gaps}[args.cmd]
    try:
        payload = fn(args)
    except Exception as e:  # noqa: BLE001
        payload = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(payload, ensure_ascii=False, indent=1, default=str))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
