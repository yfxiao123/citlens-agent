"""Offline tests for the discipline-layer mechanism — detection, artifact
surfacing, and the separation of discipline content from the general skill.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from citens.models import Paper

dspec = importlib.util.spec_from_file_location(
    "disciplines_mod", ROOT / "citens" / "disciplines.py")
disciplines = importlib.util.module_from_spec(dspec)
dspec.loader.exec_module(disciplines)

rspec = importlib.util.spec_from_file_location(
    "recall_mod", ROOT / "drivers" / "citlens_recall.py")
recall = importlib.util.module_from_spec(rspec)
rspec.loader.exec_module(recall)

mspec = importlib.util.spec_from_file_location(
    "mcp_mod", ROOT / "citlens_mcp.py")
mcp = importlib.util.module_from_spec(mspec)
mspec.loader.exec_module(mcp)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} - {name}" + (f" ({detail})" if detail and not cond else ""))


# ── detection ────────────────────────────────────────────────────────────────

print("== detect_discipline ==")
hit = disciplines.detect_discipline(
    ["measuring the natural rate of interest", "monetary policy r-star"])
check("econ topic detected", hit and hit["name"] == "economics", str(hit))
check("matched terms reported", hit and "monetary policy" in hit["matched"])

zh = disciplines.detect_discipline(["货币政策对通胀预期的影响"])
check("Chinese econ topic detected", zh and zh["name"] == "economics", str(zh))

ml = disciplines.detect_discipline(
    ["transformer attention mechanism", "semantic id generative recommendation"])
check("ML topic fires nothing", ml is None, str(ml))

mem = disciplines.detect_discipline(["memory bank retrieval augmentation"])
check("'memory bank' does not fire (no bare 'bank' term)", mem is None, str(mem))

check("empty text fires nothing", disciplines.detect_discipline(["", " "]) is None)

reg = disciplines.DISCIPLINES["economics"]
check("registry entries carry terms + pointer",
      bool(reg["terms"]) and bool(reg["pointer"]))
check("lexicon terms are lowercase (substring matching assumes it)",
      all(t == t.lower() for t in reg["terms"]))

# ── write_run: discipline.json + markdown box ────────────────────────────────

print("\n== write_run artifacts ==")
with tempfile.TemporaryDirectory() as td:
    result = {
        "report": {
            "topic": "t", "sources": [], "families_enabled": [],
            "agent_queries": [], "query_feedback": [],
            "family_sizes": {}, "family_consensus": {}, "pool_size": 0,
            "health": {}, "notes": [], "doc_types": {}, "policy_orgs": {},
            "exclusions": {}, "discipline": {"name": "economics",
                                             "matched": ["inflation"]},
        },
        "papers": [Paper(title="x", doi="10.3386/w1")],
        "rejected": [],
    }
    run_dir = recall.write_run(Path(td), "discipline smoke topic", result)
    disc = json.loads((run_dir / "discipline.json").read_text(encoding="utf-8"))
    check("discipline.json written with name+matched+pointer",
          disc.get("name") == "economics" and disc.get("matched")
          and "pointer" in disc, str(disc)[:80])
    check("pointer carries the core rules (economic significance named)",
          "经济显著" in disc.get("pointer", ""))
    md = (run_dir / "search_report.md").read_text(encoding="utf-8")
    check("report md renders the discipline box",
          "学科层（economics）" in md and "经济显著" in md)

    # a run without a discipline writes no half-empty artifacts
    result["report"]["discipline"] = None
    run_dir2 = recall.write_run(Path(td), "no discipline topic", result)
    check("no hint -> no discipline.json, no box",
          not (run_dir2 / "discipline.json").exists()
          and "学科层" not in (run_dir2 / "search_report.md").read_text(encoding="utf-8"))

# ── skill wiring: layer file, references, and content separation ────────────

print("\n== skill wiring ==")
skill = (ROOT / "skill" / "citlens" / "SKILL.md").read_text(encoding="utf-8")
layer = (ROOT / "skill" / "citlens" / "disciplines" / "economics.md").read_text(encoding="utf-8")
check("layer file exists", bool(layer))
check("SKILL.md indexes the layer", "disciplines/economics.md" in skill)
check("SKILL.md states automatic activation", "discipline" in skill and "lexicon" in skill)
check("layer carries the four econ disciplines",
      all(k in layer for k in ("economic significance", "找-evidence",
                               "NBER working papers", "stakes")))
check("general 归→评→找→定 movements stay field-neutral",
      "economic" not in skill[skill.find("**Write with numbered claims"):skill.find("**Prose style")])
check("MCP instructions carry the mechanism, not the discipline text",
      "discipline" in mcp.INSTRUCTIONS
      and "ECONOMIC significance" not in mcp.INSTRUCTIONS)

print(f"\n{'ALL PASS' if not FAIL else 'FAILURES: ' + str(FAIL)} ({len(PASS)} checks)")
sys.exit(1 if FAIL else 0)
