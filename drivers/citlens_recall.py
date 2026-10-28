#!/usr/bin/env python
"""citlens_recall.py — the CiteLens multi-family recall leg, agent-driven.

This is the retrieval half of CiteLens with the LLM surgically removed. In
the engine repo the same leg had nine families; three of them (planned,
HyDE, pivot) existed to GENERATE queries with an LLM, and the final cascade
rank judged relevance with an LLM. In this build the calling AGENT is that
LLM: it reads the topic, crafts the English queries itself (the skill's
PRESS discipline), passes them via ``--queries``, and judges relevance of
the returned pool itself. Everything mechanical stays measured and
reproducible: per-source cells, RRF fusion, per-family seat quotas,
snowball / recommendations / survey-harvest expansion, the honest health
buckets and the PRISMA exclusion log.

Run it with this repo's interpreter, from the data home (``.env``,
``data/litdb``, ``citlens-runs/`` and ``.cache`` resolve against the CWD):

    cd <CITLENS_HOME>
    python drivers/citlens_recall.py \
        --topic "generative recommendation with semantic IDs" \
        --queries "semantic ID generative recommendation" \
                  "item tokenization retrieval" --target 60

Families
--------
    agent    your own crafted queries (replaces planned/HyDE/pivot)
    raw      the topic verbatim, every source
    oa_title OpenAlex title.search over --title-probes (anchor titles)
    s2_rec   Semantic-Scholar recommendations from the pool head
    snowball one-hop citation expansion (backward + forward)
    web      web bridge (blogs/forums) over --web-queries (EN + ZH)
    survey   reference harvest from topic surveys found in the pool
    policy   NBER / Fed Board / IMF via Crossref DOI prefixes (--policy-queries)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# This repo's citens core wins over any citens the interpreter happens to have
# installed (e.g. the engine repo's editable install).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- CiteLens constants, copied verbatim (do not "improve" them) --------------
PER_SOURCE = 20          # per-source cell depth (== the union@20 ceiling)
AGENT_DEPTH = 40         # agent-query leg per-cell depth; RRF only sums ranks
# (the engine's PLANNED_DEPTH — same leg, the queries just come from you)
FAMILY_QUOTA = 30        # each family's guaranteed seats in the fused pool
POLICY_SEATS = 8         # seats the policy corpus keeps through the target cut
DEFAULT_SOURCES = ["arxiv", "semantic_scholar", "openalex", "crossref"]
ALL_FAMILIES = [
    "agent", "raw", "oa_title", "s2_rec", "snowball", "web", "survey", "policy",
]


def _log(msg: str) -> None:
    """Never let logging kill the run: a zh-CN console defaults to GBK, and
    the sources emit characters outside it."""
    try:
        print(f"[citlens] {msg}", flush=True)
    except Exception:  # noqa: BLE001
        try:
            sys.stdout.write(f"[citlens] {msg}".encode("ascii", "replace").decode("ascii") + "\n")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


async def _cells(
    queries: list[str],
    sources: list[str],
    health: dict,
    depth: int = PER_SOURCE,
) -> dict[str, dict[str, list]]:
    """Per-source result lists for each query — RRF needs cell ranks, not a merge."""
    from citens.eval.litsearch import search_one_query

    out: dict[str, dict[str, list]] = {}
    for q in queries:
        out[q] = await search_one_query(q, sources, per_source=depth, health_out=health)
    return out


def _first_wins(families, quota: int) -> list:
    """Each family contributes its OWN fused head of `quota`; first family wins ties."""
    from citens.eval.litsearch import _key_of

    pool, seen = [], set()
    for fam in families:
        for p in fam[:quota]:
            k = _key_of(p)
            if k not in seen:
                seen.add(k)
                pool.append(p)
    return pool


def _health_summary(health: dict) -> dict:
    return {s: {"ok": b[0], "empty": b[1], "failed": b[2]} for s, b in sorted(health.items())}


async def recall(args) -> dict:
    from citens.eval.litsearch import fuse_multi_query, oa_title_search
    from citens.search.base import deduplicate
    from citens.search.snowball import _s2_recommended, _s2_to_paper, is_article_doi, snowball
    from citens.search.survey_seed import survey_seed_papers
    # imported explicitly: citens/search/__init__.py never imports websearch, so a
    # `"web"` entry in SEARCH_SOURCES is silently dropped by the registry filter.
    # Same registry isolation for the policy corpus — it is a family, not a
    # raw-search source; the driver runs it over its own queries.
    from citens.search.websearch import WebSearchSource
    from citens.search.policy import PolicySearchSource, stamp_doc_types
    from citens.disciplines import detect_discipline

    want = set(args.families)
    topic, sources = args.topic, args.sources
    health: dict[str, list[int]] = {}
    notes: list[str] = []
    agent_qs = [q for q in (args.queries or []) if q.strip()]
    report: dict = {
        "topic": topic, "sources": sources,
        "families_enabled": sorted(want), "agent_queries": agent_qs,
    }

    if not agent_qs:
        notes.append(
            "agent: 未提供 --queries——调用方 agent 就是规划器（skill 的 PRESS 纪律），"
            "把概念块查询传进来；本次仅 raw + 扩展家族"
        )

    families: list[list] = []
    family_sizes: dict[str, int] = {}
    # Cross-family consensus: which recall families surfaced each record.
    # A paper found by 3 independent families (query + snowball + survey
    # harvest) is far likelier on-topic than a single web hit — the vote is
    # recorded on the Paper (found_by) and consumed by `screen`'s consensus
    # channel. Votes are noted over each family's SEAT-truncated head (the
    # part that could actually enter the pool), not its full recall.
    from citens.eval.litsearch import _key_of as _fuse_key

    votes: dict[str, set[str]] = {}

    def _note(fam_name: str, fam_papers: list) -> None:
        for p in fam_papers:
            votes.setdefault(_fuse_key(p), set()).add(fam_name)

    # ── family 1: agent-crafted queries (the "planned" leg, you are the planner)
    agent_cells = await _cells(agent_qs, sources, health, AGENT_DEPTH) if agent_qs else {}
    if agent_cells:
        fam = fuse_multi_query(agent_cells, sources)
        families.append(fam)
        family_sizes["agent"] = len(fam)
        _note("agent", fam[:FAMILY_QUOTA])
        _log(f"family agent: {len(fam)} (from {len(agent_qs)} queries)")
    elif "agent" in want:
        notes.append("agent: 无查询，已跳过")

    # ── family 2: raw question ────────────────────────────────────────────────
    raw_cells = await _cells([topic], sources, health, PER_SOURCE)
    raw_fam = fuse_multi_query(raw_cells, sources)
    families.append(raw_fam)
    family_sizes["raw"] = len(raw_fam)
    _note("raw", raw_fam[:FAMILY_QUOTA])
    _log(f"family raw: {len(raw_fam)}")

    agent_raw = fuse_multi_query({**agent_cells, **raw_cells}, sources)

    # ── query-level feedback: which queries the sources actually answered ────
    # The full-set bench measured 71% of missed golds sharing <=2 content words
    # with the question — vocabulary mismatch is THE recall killer, and the fix
    # loop needs to know WHICH concept block came back empty/thin so the agent
    # can rephrase it in paper-side vocabulary. Computed from the cells already
    # in hand; a source that FAILED its cell counts as 0 here but its failures
    # are reported separately in the health table (never conflated).
    query_feedback: list[dict] = []
    for q, cells in [*agent_cells.items(), (topic, raw_cells.get(topic, {}))]:
        by_src = {s: len(cells.get(s) or []) for s in sources}
        total = sum(by_src.values())
        verdict = "empty" if total == 0 else ("thin" if total < 12 else "ok")
        query_feedback.append(
            {"query": q, "total": total, "verdict": verdict, "by_source": by_src}
        )
    report["query_feedback"] = query_feedback
    weak = [q["query"] for q in query_feedback if q["verdict"] != "ok"]
    if weak:
        notes.append(
            f"查询反馈：{len(weak)}/{len(query_feedback)} 条查询命中过低（empty/thin，见报告表）——"
            "这些概念块换论文侧词汇（方法名/数据集名/任务名/术语缩写）重拟后补一轮 search；"
            "命中过低通常意味着词汇错配，不是池子太小"
        )

    # ── family 3: OpenAlex title index over agent-supplied probe titles ──────
    probes = [t for t in (args.title_probes or []) if t.strip()]
    if "oa_title" in want and probes:
        try:
            # 3 probes max (HyDE shape: hypothetical TITLES of the ideal
            # paper, written in paper vocabulary — the query-vocabulary
            # escape hatch; still capped, the title index shares the daily
            # OpenAlex budget)
            oa_cells = await oa_title_search(probes[:3])
            if any(oa_cells.values()):
                fam = fuse_multi_query(
                    {f"[title] {t}": {"openalex": cs} for t, cs in oa_cells.items()},
                    ["openalex"],
                )
                families.append(fam)
                family_sizes["oa_title"] = len(fam)
                _note("oa_title", fam[:FAMILY_QUOTA])
                _log(f"family oa_title: {len(fam)}")
            else:
                notes.append("oa_title: 0 命中（OpenAlex 标题索引无匹配或预算耗尽），已跳过")
        except Exception as e:  # noqa: BLE001
            notes.append(f"oa_title: 失败，跳过（{str(e)[:120]}）")
    elif "oa_title" in want:
        notes.append(
            "oa_title: 未提供 --title-probes——建议按 HyDE 思路拟 2-3 个『理想论文标题』"
            "（用论文侧词汇，不是提问措辞）喂给标题索引，已跳过"
        )

    pool = _first_wins(families, FAMILY_QUOTA)
    _log(f"pool after quotas: {len(pool)}")
    # Everything the per-family seat quota cut must be reportable: the
    # exclusion log used to silently omit these (only the target cut was
    # logged), so "pool size" overstated what the run actually kept.
    quota_cut = [p for fam in families for p in fam[FAMILY_QUOTA:]]

    # ── family 4: S2 learned recommendations from the pool's own head ────────
    if "s2_rec" in want and pool:
        try:
            rec_dois = [p.doi for p in pool[:10] if is_article_doi(p.doi)][:5]
            items = await _s2_recommended(rec_dois, limit=30) if rec_dois else []
            from citens.eval.litsearch import _key_of
            recs = [
                r for r in (
                    _s2_to_paper(item, "s2-rec", (rec_dois[0] if rec_dois else "")[:30])
                    for item in items
                ) if r is not None
            ]
            # Vote on the family's OWN head (not only the records it added):
            # a paper already in the pool that S2 also recommends is an
            # independent confirmation, and dropping that vote undercounted
            # exactly the cross-family consensus `screen` consumes.
            _note("s2_rec", recs[:FAMILY_QUOTA])
            quota_cut.extend(recs[FAMILY_QUOTA:])
            added = 0
            added_papers = []
            seen = {_key_of(p) for p in pool}
            for rec in recs:
                if _key_of(rec) not in seen:
                    seen.add(_key_of(rec))
                    pool.append(rec)
                    added_papers.append(rec)
                    added += 1
            family_sizes["s2_rec"] = added
            _log(f"family s2_rec: +{added} (head {len(recs)})")
        except Exception as e:  # noqa: BLE001
            notes.append(f"s2_rec: 失败，跳过（{str(e)[:120]}）")

    # ── family 5: one-hop citation expansion (backward + forward) ────────────
    if "snowball" in want and pool:
        try:
            from citens.eval.litsearch import _key_of
            anchors = [p for p in pool[:8] if is_article_doi(p.doi)][:5]
            if anchors:
                expanded = await snowball(
                    anchors, existing_ids={_key_of(p) for p in pool},
                    backward=True, forward=True, related=False,
                    limit_per_paper=100, top=120,
                )
                _note("snowball", expanded[:FAMILY_QUOTA])
                quota_cut.extend(expanded[FAMILY_QUOTA:])
                seen = {_key_of(p) for p in pool}
                added = 0
                added_papers = []
                for p in expanded[:FAMILY_QUOTA]:
                    if _key_of(p) not in seen:
                        seen.add(_key_of(p))
                        pool.append(p)
                        added_papers.append(p)
                        added += 1
                family_sizes["snowball"] = added
                _log(f"family snowball: +{added} (head {len(expanded[:FAMILY_QUOTA])})")
        except Exception as e:  # noqa: BLE001
            notes.append(f"snowball: 失败，跳过（{str(e)[:120]}）")

    # ── family 6: web bridge (English + Chinese corpora) ────────────────────
    if "web" in want:
        web_qs = [q for q in (args.web_queries or []) if q.strip()]
        report["web_queries"] = web_qs
        if web_qs:
            try:
                web_src = WebSearchSource()
                web_papers = await web_src.search(web_qs, 16)
                # honest bucket for the web bridge: [ok, empty, failed] per
                # query. Keyless engines fail by returning [], so without this
                # a dead bridge looked exactly like "the web had nothing".
                health["web"] = list(web_src.health)
                _note("web", web_papers[:FAMILY_QUOTA])
                quota_cut.extend(web_papers[FAMILY_QUOTA:])
                from citens.eval.litsearch import _key_of
                seen = {_key_of(p) for p in pool}
                added = 0
                added_papers = []
                for p in web_papers[:FAMILY_QUOTA]:
                    if _key_of(p) not in seen:
                        seen.add(_key_of(p))
                        pool.append(p)
                        added_papers.append(p)
                        added += 1
                family_sizes["web"] = added
                _log(f"family web: +{added} (head {len(web_papers[:FAMILY_QUOTA])})")
            except Exception as e:  # noqa: BLE001
                notes.append(f"web: 失败，跳过（{str(e)[:120]}）")
        else:
            notes.append("web: 未提供 --web-queries（英文逐字跨度 + 中文自然短语），已跳过")

    # ── family 7: survey reference harvest (human-curated canon) ────────────
    if "survey" in want and pool:
        try:
            from citens.eval.litsearch import _key_of
            survey_papers, seeds = await survey_seed_papers(
                topic, pool[:40], planner=agent_qs or [topic], quota=FAMILY_QUOTA
            )
            report["survey_seeds"] = seeds
            _note("survey", survey_papers[:FAMILY_QUOTA])
            quota_cut.extend(survey_papers[FAMILY_QUOTA:])
            seen = {_key_of(p) for p in pool}
            added = 0
            added_papers = []
            for p in survey_papers:
                if _key_of(p) not in seen:
                    seen.add(_key_of(p))
                    pool.append(p)
                    added_papers.append(p)
                    added += 1
            family_sizes["survey"] = added
            _log(f"family survey: +{added} (head {len(survey_papers)})")
        except Exception as e:  # noqa: BLE001
            notes.append(f"survey: 失败，跳过（{str(e)[:120]}）")

    # ── family 8: policy corpus (NBER / Fed Board / IMF via Crossref) ────────
    # The scholarly families speak journal vocabulary; policy-side research
    # (Fed FEDS Notes, NBER WPs) surfaces only by title accident and arrives
    # indistinguishable from journal evidence. This family queries the three
    # DOI-depositing institutions directly and stamps doc_type/policy_org so
    # the agent can contrast the two perspectives instead of blending them.
    if "policy" in want:
        policy_qs = [q for q in (args.policy_queries or []) if q.strip()] \
            or agent_qs or [topic]
        report["policy_queries"] = policy_qs
        try:
            pol_src = PolicySearchSource()
            pol_papers = await pol_src.search(policy_qs, 24)
            for org, b in pol_src.health.items():
                health[f"policy-{org}"] = list(b)
            _note("policy", pol_papers[:FAMILY_QUOTA])
            quota_cut.extend(pol_papers[FAMILY_QUOTA:])
            from citens.eval.litsearch import _key_of
            seen = {_key_of(p) for p in pool}
            added = 0
            for p in pol_papers[:FAMILY_QUOTA]:
                if _key_of(p) not in seen:
                    seen.add(_key_of(p))
                    pool.append(p)
                    added += 1
            family_sizes["policy"] = added
            _log(f"family policy: +{added} (head {len(pol_papers)})")
        except Exception as e:  # noqa: BLE001
            notes.append(f"policy: 失败，跳过（{str(e)[:120]}）")

    # ── ordering: RRF/family seat order (NO LLM cascade in this build) ──────
    # Stamp the consensus signal BEFORE dedup so every kept record carries it;
    # rejected records keep theirs too — an exclusion log entry that says
    # "3 families voted for this paper" is far more reviewable.
    for p in pool:
        p.found_by = sorted(votes.get(_fuse_key(p), set()))
    consensus = {
        "2plus": sum(1 for v in votes.values() if len(v) >= 2),
        "3plus": sum(1 for v in votes.values() if len(v) >= 3),
    }

    # doc-kind stamping BEFORE dedup: the merge prefers the published variant,
    # so an NBER WP folding into its AER version correctly re-tags as journal —
    # and records the other families surfaced (snowball can pull Fed papers
    # nobody queried for) get the same tag for the 学术/政策端 contrast
    stamp_doc_types(pool)
    stamp_doc_types(quota_cut)

    notes.append(
        "排序说明：本构建无 LLM 级联——顺序为 RRF/家族保底席位序，"
        "引用前必须由调用方 agent 自行判断相关性（读标题+摘要逐篇过）；"
        "record.found_by 记录了召回该篇的家族集合，可用 `screen` 工具做三分带分流"
    )

    deduped = deduplicate(pool)
    deduped_ids = {p.id for p in deduped}
    ranked = deduped
    if args.target:
        ranked = ranked[: args.target]
        # Policy seat reservation through the target cut. The policy family
        # seats AFTER agent/raw, so on any topic where the journal families
        # already fill the target the policy corpus is systematically cut
        # first — the exact records this family exists to deliver (measured
        # on the 2026-10-28 smoke: 30 policy records pooled, 3 survived
        # target=50). Up to POLICY_SEATS cut policy records swap in for the
        # weakest non-policy tail, mirroring blend_pool's diversity
        # reservation. target=0 (review workflows) keeps everything anyway.
        if "policy" in want:
            kept_set = {p.id for p in ranked}
            pol_cut = [p for p in deduped if p.policy_org and p.id not in kept_set]
            pol_in = sum(1 for p in ranked if p.policy_org)
            if pol_cut and pol_in < POLICY_SEATS:
                non_pol_tail = [p for p in reversed(ranked) if not p.policy_org]
                swap = min(POLICY_SEATS - pol_in, len(pol_cut), len(non_pol_tail))
                drop = {p.id for p in non_pol_tail[:swap]}
                ranked = [p for p in ranked if p.id not in drop] + pol_cut[:swap]
    kept_ids = {p.id for p in ranked}
    # doc-kind / policy-org breakdown of what the run actually KEEPS — the
    # dashboard for the 学术证据 vs 政策端视角 contrast, and a coverage check:
    # a macro-policy pool with zero policy_org records means the policy family
    # never fired (families flag, health buckets)
    doc_types: dict[str, int] = {}
    policy_orgs: dict[str, int] = {}
    for p in ranked:
        if p.doc_type:
            doc_types[p.doc_type] = doc_types.get(p.doc_type, 0) + 1
        if p.policy_org:
            policy_orgs[p.policy_org] = policy_orgs.get(p.policy_org, 0) + 1

    # discipline layer: mechanical detection over the search text (lexicon,
    # zero LLM), with a structural fallback — policy-corpus records surviving
    # in the pool imply the economics layer whatever vocabulary was used
    discipline = detect_discipline([topic, *agent_qs, *(args.policy_queries or [])])
    if discipline is None and policy_orgs:
        discipline = {"name": "economics",
                      "matched": ["policy-corpus records in the pool"]}
    if discipline:
        report["discipline"] = discipline
    # Reason-aware PRISMA log. Three distinct fates must not share the label
    # "ranked_below_target": per-family seat quota, dedupe merge, and the
    # target cut are different reviewer decisions.
    rejected: list[tuple[str, Paper]] = []
    seen_rejected: set[str] = set()
    for p in quota_cut:
        if p.id in kept_ids or p.id in seen_rejected:
            continue
        seen_rejected.add(p.id)
        rejected.append(("family_quota", p))
    for p in pool:
        if p.id in kept_ids or p.id in seen_rejected:
            continue
        seen_rejected.add(p.id)
        reason = "ranked_below_target" if p.id in deduped_ids else "duplicate_or_merged"
        rejected.append((reason, p))
    if args.target and len(deduped_ids) > len(ranked):
        notes.append(
            f"target={args.target} 截掉了 {len(deduped_ids) - len(ranked)} 条已融合候选——"
            "扩展家族（s2_rec/snowball/web/survey）排在配额头之后，会被优先截掉"
            "（policy 家族有 8 席保底穿过截断）；"
            "写综述/要广度时用 target: 0"
        )

    report.update(
        family_sizes=family_sizes,
        family_consensus=consensus,
        pool_size=len(pool),
        kept=len(ranked),
        health=_health_summary(health),
        notes=notes,
        doc_types=doc_types,
        policy_orgs=policy_orgs,
        exclusions={
            reason: sum(1 for r, _p in rejected if r == reason)
            for reason in ("family_quota", "duplicate_or_merged", "ranked_below_target")
        },
    )
    # Everything the families put in the pool but the target cut is an EXCLUSION
    # and must be logged with a reason: "pool size" is not a coverage claim.
    return {"report": report, "papers": ranked, "rejected": rejected}


def write_run(out_root: Path, topic: str, result: dict) -> Path:
    from citens.grounding.fulltext import slugify

    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = out_root / f"{slugify(topic)}-{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    papers = result["papers"]
    report = result["report"]

    with (run_dir / "pool.jsonl").open("w", encoding="utf-8") as fh:
        for p in papers:
            fh.write(json.dumps(p.model_dump(), ensure_ascii=False) + "\n")

    # PRISMA-style exclusion log: everything retrieved but not kept, with a reason
    kept_keys = {p.id for p in papers}
    with (run_dir / "exclusions.jsonl").open("w", encoding="utf-8") as fh:
        for reason, p in result.get("rejected", []):
            if p.id in kept_keys:
                continue
            fh.write(json.dumps({
                "title": p.title, "doi": p.doi, "source": p.source,
                "reason": reason, "citation_count": p.citation_count,
                "found_by": p.found_by,
            }, ensure_ascii=False) + "\n")

    # query-level feedback as a machine-readable artifact (the MCP search view
    # surfaces it so the agent can rephrase weak concept blocks without
    # parsing the markdown report)
    (run_dir / "queries.json").write_text(
        json.dumps({"query_feedback": report.get("query_feedback", [])},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    # discipline layer hint as a machine-readable artifact — the MCP search
    # view surfaces it so the calling agent receives the domain's core
    # disciplines even when its client never loaded the skill
    disc = report.get("discipline")
    disc_pointer = ""
    if disc:
        from citens.disciplines import DISCIPLINES

        disc_pointer = DISCIPLINES[disc["name"]]["pointer"]
        (run_dir / "discipline.json").write_text(
            json.dumps({**disc, "pointer": disc_pointer},
                       ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    disc_box = (
        f"## 学科层（{disc['name']}）——检测词命中："
        f"{'、'.join(disc.get('matched', [])[:3])}\n\n> {disc_pointer}\n"
        if disc else ""
    )

    fam_rows = "\n".join(
        f"| {k} | {v} |" for k, v in report.get("family_sizes", {}).items()
    ) or "| （无） | 0 |"
    health_rows = "\n".join(
        f"| {k} | {v['ok']} | {v['empty']} | {v['failed']} |"
        for k, v in report.get("health", {}).items()
    ) or "| （无） | 0 | 0 | 0 |"
    notes = "\n".join(f"- {n}" for n in report.get("notes", [])) or "- （无）"
    missing_venue = sum(1 for p in papers if not p.venue)
    no_doi = sum(1 for p in papers if not p.doi)
    reviews = sum(1 for p in papers if p.is_review)
    doc_types = report.get("doc_types", {})
    policy_orgs = report.get("policy_orgs", {})
    kind_line = " · ".join(f"{k} {v}" for k, v in sorted(doc_types.items())) or "（无标记）"
    org_line = " · ".join(f"{k} {v}" for k, v in sorted(policy_orgs.items())) or "无"
    cons = report.get("family_consensus", {})
    excl = report.get("exclusions", {})
    qfb_rows = "\n".join(
        f"| {q['query'][:60]} | {q['total']} | {q['verdict']} | "
        + " ".join(f"{s.split('_')[0]}:{n}" for s, n in q["by_source"].items())
        + " |"
        for q in report.get("query_feedback", [])
    ) or "| （无查询执行） | 0 | – | – |"

    (run_dir / "search_report.md").write_text(f"""# CiteLens 检索报告 — {topic}

生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}
检索源：{', '.join(report.get('sources', []))}
启用家族：{', '.join(report.get('families_enabled', []))}

## 结果

- 候选池：{report.get('pool_size', 0)} 篇 → 保留 **{len(papers)}** 篇
- 其中综述 {reviews} 篇 · 无 DOI {no_doi} 篇 · 无 venue {missing_venue} 篇
- 文献类型：{kind_line}（政策机构：{org_line}）
  （doc_type/policy_org 已写入每条记录——学术证据与政策端视角分开读，
  二者的分析框架与关心变量并不相同）
- 家族共识：≥2 家族同时命中 {cons.get('2plus', 0)} 篇 · ≥3 家族 {cons.get('3plus', 0)} 篇
  （`found_by` 已写入每条 pool 记录；`screen` 工具的 consensus 通道消费它）
- 排除日志：家族配额 {excl.get('family_quota', 0)} · 合并去重 {excl.get('duplicate_or_merged', 0)}
  · 目标截断 {excl.get('ranked_below_target', 0)}（`exclusions.jsonl` 逐条带原因码）
- 顺序为 RRF/家族席位序（无 LLM 级联）：引用前由 agent 逐篇判断相关性，
  可先跑 `screen` 做三分带（core / uncertain / likely_off）分流精读
- 收工条件未自动判定：请按 SKILL.md 阶段 F 跑锚点核验（`audit` 工具）与
  饱和检查后再声明完成

{disc_box}
## 家族 → 入池条数

| 家族 | 入池 |
|---|---|
{fam_rows}

## 逐源健康（ok / empty / failed，按检索 cell 计）

| 源 | ok | empty | failed |
|---|---|---|---|
{health_rows}

> failed > 0 时必须显式报告：源失败绝不能写成"零命中"。

## 查询反馈（每条查询的实际命中——造词迭代的仪表盘）

| 查询 | 总命中 | 判定 | 逐源 |
|---|---|---|---|
{qfb_rows}

> empty/thin 的概念块是词汇错配的信号：换成论文侧词汇（方法名/数据集名/
> 任务名/术语缩写）重拟后补一轮 search，而不是加大同词重试。

## agent 供查询（家族 1）

{chr(10).join('- ' + q for q in report.get('agent_queries', [])) or '- （无——调用方未提供；你就是规划器，见 SKILL.md PRESS 纪律）'}

## web 桥接查询（英文 + 中文）

{chr(10).join('- ' + q for q in report.get('web_queries', [])) or '- （无——需显式提供 --web-queries）'}

## 综述种子（参考文献收割锚点）

{chr(10).join('- ' + q for q in report.get('survey_seeds', [])) or '- （无）'}

## 政策语料查询（家族 8：NBER / Fed Board / IMF）

{chr(10).join('- ' + q for q in report.get('policy_queries', [])) or '- （未显式提供——复用 agent 查询或主题；政策语料建议用平实的经济学措辞）'}

> 政策机构命中：{org_line}。政策笔记（FEDS Notes 等）是写给决策者的：
> 读其中的效应量级判断与 stated data gaps——前者是经济显著性的参照系，
> 后者是「找空白」的直接证据。

## 备注与降级

{notes}

## 下一步（未完成即不算收工）

1. **相关性粗排/精排**：读池内每篇的标题+摘要，逐篇判断与主题的相关性，
   排序并筛除（筛除的写入 `exclusions.jsonl`，带原因码）。
2. **锚点核验**：用 `audit` 工具算池子对 top 综述参考文献的 coverage。
3. **饱和检查**：换一种主题措辞再搜一次，几乎无新记录才算饱和。
4. **全文清单**：对核心论文用 `fetch` 工具取全文；拿不到的标注
   "仅摘要级"并写入 `fetch_list.md`。
""", encoding="utf-8")
    return run_dir


def build_args(argv=None):
    ap = argparse.ArgumentParser(description="CiteLens agent-driven recall leg (no LLM)")
    ap.add_argument("--topic", required=True, help="研究主题（中英皆可；查询由 agent 用英文供给）")
    ap.add_argument("--queries", nargs="+", default=[],
                    help="agent 亲拟的英文概念块查询（PRESS 纪律），空格分隔多条")
    ap.add_argument("--title-probes", nargs="+", default=[],
                    help="锚点/假想论文标题（HyDE：用论文侧词汇拟理想论文的标题），"
                         "喂 OpenAlex title.search 家族（最多取前 3 条）")
    ap.add_argument("--web-queries", nargs="+", default=[],
                    help="web 桥接查询：英文逐字跨度 + 中文自然短语")
    ap.add_argument("--policy-queries", nargs="+", default=[],
                    help="政策语料查询（NBER/Fed/IMF）：平实的经济学措辞，"
                         "缺省复用 --queries 或主题")
    ap.add_argument("--target", type=int, default=0, help="保留条数上限（0 = 不截断）")
    ap.add_argument("--sources", default="", help="逗号分隔检索源；默认取 SEARCH_SOURCES")
    ap.add_argument("--families", default=",".join(ALL_FAMILIES),
                    help="逗号分隔家族；可选 " + ",".join(ALL_FAMILIES)
                    + "（agent/raw 是主干：始终执行，不受此开关限制）")
    ap.add_argument("--out", default="citlens-runs", help="报告输出根目录")
    ap.add_argument("--append-pool", action="store_true",
                    help="把结果并入 CiteLens 文献池 data/litdb/<topic>.jsonl")
    ap.add_argument("--dry-run", action="store_true", help="只打印将执行的查询与家族，不发检索请求")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    _force_utf8_stdio()
    args = build_args(argv)
    if args.sources.strip():
        args.sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    else:
        try:
            from citens.config import settings
            args.sources = [s.strip() for s in settings.search_sources.split(",") if s.strip()]
        except Exception:  # noqa: BLE001
            args.sources = list(DEFAULT_SOURCES)
    args.families = [f.strip() for f in args.families.split(",") if f.strip()]

    if args.dry_run:
        print(json.dumps({
            "topic": args.topic,
            "agent_queries": args.queries,
            "title_probes": args.title_probes[:3],
            "web_queries": args.web_queries,
            "policy_queries": args.policy_queries,
            "sources": args.sources,
            "families": args.families,
            "note": "你就是规划器：查询为空时先按 SKILL.md PRESS 纪律拟好再搜",
        }, ensure_ascii=False, indent=1))
        return 0

    t0 = time.time()
    result = asyncio.run(recall(args))
    run_dir = write_run(Path(args.out), args.topic, result)
    papers = result["papers"]
    _log(f"kept {len(papers)} papers -> {run_dir}")

    if args.append_pool:
        from citens.collect import append_pool
        added = append_pool(args.topic, papers)
        _log(f"appended {added} new records to the literature pool")

    _log(f"elapsed {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
