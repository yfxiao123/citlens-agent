"""Module-split checks (2026-11-20): 找文献 / 写综述 / 答问题 are separate jobs.

The teaching layer used to be one 504-line SKILL.md plus one mixed DISCIPLINE
string, so a pure search consult received the full survey-writing sermon and
agents slid from searching into writing (the user's "找完文献后自动写综述").
These checks pin the split at every layer that teaches:

- the catalogue DISCIPLINE (citlens_cli.DISCIPLINE) is search-scoped and
  carries the routing boundary instead of the writing sermon;
- the skill is a ROUTER: three module files under workflows/, each with its
  own deliverable, gates and 收工 section, referenced from SKILL.md;
- the search result hint (_search_view) carries the stop rule.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} - {name}" + (f"  ({detail})" if detail and not cond else ""))


import citlens_cli as m  # noqa: E402

SKILL = ROOT / "skill" / "citlens"
ROUTER = (SKILL / "SKILL.md").read_text(encoding="utf-8")

# ── the catalogue discipline is SEARCH-scoped, with a routing boundary ───────
print("== DISCIPLINE scope ==")
sermon_marks = ("归→评→找→定", "去AI味", "Structure the review body",
                "prose style", "Writing a review is opt-in")
leftover = [s for s in sermon_marks if s.lower() in m.DISCIPLINE.lower()]
check("discipline carries no survey-writing sermon",
      not leftover, f"leftover: {leftover}")
check("discipline keeps the search planner rules",
      "planner" in m.DISCIPLINE.lower() and "literature" in m.DISCIPLINE.lower()
      and "query_feedback" in m.DISCIPLINE and "expand" in m.DISCIPLINE)
check("discipline carries the module boundary sentence",
      "SEPARATE jobs" in m.DISCIPLINE and "never slide from a" in m.DISCIPLINE
      and "workflows/review.md" in m.DISCIPLINE
      and "workflows/answer.md" in m.DISCIPLINE)

# ── the skill routes to three gated module files ─────────────────────────────
print("== router SKILL.md ==")
for f in ("workflows/search.md", "workflows/review.md", "workflows/answer.md"):
    check(f"router references {f}", f in ROUTER)
check("router states the search stop-gate (never escalates into prose)",
      "never escalates into prose" in ROUTER
      and "COMPLETE when the numbers" in ROUTER.replace("**", ""))
check("router states the survey gate (explicit request only)",
      "explicit request ONLY" in ROUTER and "seven setup questions" in ROUTER)
check("router states the answer gate (an answer, not a survey)",
      "an answer, not a survey" in ROUTER)
check("router keeps the verification chain strings for the review row",
      all(k in ROUTER for k in ("six-grade", "verdicts.jsonl",
                                "verify", "clean", "honesty")))
check("router keeps shared core (one rule, discipline layers, failures)",
      "Use `search` for literature" in ROUTER
      and "disciplines/economics.md" in ROUTER
      and "Failure modes" in ROUTER)

# ── each module file exists, is non-trivial, and owns its 收工 ────────────────
print("== module files ==")
done_marks = {"search.md": "检索模块收工", "review.md": "综述模块收工",
              "answer.md": "答问模块收工"}
for f, mark in done_marks.items():
    p = SKILL / "workflows" / f
    text = p.read_text(encoding="utf-8") if p.is_file() else ""
    check(f"{f} ships with its own 收工 section ({mark})",
          len(text.splitlines()) > 40 and mark in text)

review = (SKILL / "workflows" / "review.md").read_text(encoding="utf-8")
check("review module: gate + seven setup questions",
      "explicitly asked for" in review and "Output language" in review
      and "Own research to position" in review)
check("review module: movement-by-movement verify (quality-stability fix)",
      "movement by movement" in review.lower()
      and "verify as you go" in review.lower()
      and "cumulative" in review.lower())

answer = (SKILL / "workflows" / "answer.md").read_text(encoding="utf-8")
check("answer module: never becomes a survey + decisive-few fetch",
      "NEVER becomes a survey" in answer and "3–8" in answer)
check("answer module: same verify machinery applies",
      "verify --review" in answer and "six-grade" in answer)

search_md = (SKILL / "workflows" / "search.md").read_text(encoding="utf-8")
check("search module: PRESS + scout + coverage discipline migrated intact",
      "PRESS" in search_md and "Scout before you search" in search_md
      and "Coverage discipline" in search_md and "query_feedback" in search_md)
check("search module: 收工 forbids the write escalation",
      "Do not start writing a survey" in search_md)

# ── the search result hint carries the stop rule ─────────────────────────────
print("== search result hint ==")
with tempfile.TemporaryDirectory() as td:
    rd = Path(td) / "run"
    rd.mkdir()
    (rd / "pool.jsonl").write_text(
        json.dumps({"doi": "10.1/x", "title": "T", "source": "openalex"}) + "\n",
        encoding="utf-8")
    (rd / "queries.json").write_text(
        json.dumps({"query_feedback": [{"query": "q", "total": 3,
                                        "verdict": "ok"}]}), encoding="utf-8")
    (rd / "search_report.md").write_text("# report\nok\n", encoding="utf-8")
    (rd / "discipline.json").write_text("{}", encoding="utf-8")
    st = {"job_id": "j", "state": "done", "topic": "t", "run_dir": str(rd),
          "log_path": str(rd / "log.txt"), "exit_code": 0}
    out = m._search_view({"home": td}, st)
    hint = out.get("hint") or ""
    check("_search_view hint tells the agent to STOP at the search deliverable",
          "SEARCH deliverable" in hint and "workflows/review.md" in hint
          and "workflows/answer.md" in hint, hint[-160:])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
