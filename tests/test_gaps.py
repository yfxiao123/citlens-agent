"""Offline tests for citens/gapfinding.py — the mechanical 找 substrate.

No network: novelty runs BM25-only (the embedding model setting is blanked),
stated-gap mining reads fixture fulltext files.
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

from citens.config import settings
from citens.models import Paper

spec = importlib.util.spec_from_file_location(
    "gap_mod", ROOT / "citens" / "gapfinding.py")
gap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gap)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} - {name}" + (f" ({detail})" if detail and not cond else ""))


def _p(title, year, abstract, doi):
    return Paper(title=title, year=year, abstract=abstract, doi=doi,
                 source="t", citation_count=1)


# ── year bands ───────────────────────────────────────────────────────────────

print("== year_bands ==")
check("wide range -> three oldest-first bands",
      gap.year_bands([1998, 2026]) == [("1998-2007", 1998, 2007),
                                       ("2008-2017", 2008, 2017),
                                       ("2018-2026", 2018, 2026)],
      str(gap.year_bands([1998, 2026])))
check("sliver merges into the previous band (no 1-year era)",
      all(e - s >= 4 for _, s, e in gap.year_bands([2000, 2021])),
      str(gap.year_bands([2000, 2021])))
check("degenerate range collapses", gap.year_bands([2024, 2024]) == [("2024", 2024, 2024)])
check("empty -> no bands", gap.year_bands([None, None]) == [])

# ── coverage matrix ──────────────────────────────────────────────────────────

print("\n== coverage_matrix ==")
ps = [
    _p("Natural rate estimates with monetary shocks", 2015,
       "monetary policy natural rate estimates", "10.1/a"),
    _p("Monetary policy transmission postwar", 1999,
       "monetary policy transmission channels", "10.1/b"),
    _p("Deep reinforcement learning recommendation", 2023,
       "reinforcement learning recommendation survey", "10.1/c"),
    _p("Natural rate and fiscal interactions", 2024,
       "fiscal policy natural rate r-star", "10.1/d"),
]
m = gap.coverage_matrix(ps, ["natural rate", "monetary policy", "reinforcement learning"])
check("matrix ok with bands", m["ok"] and "?" in m["bands"])
check("old natural-rate cell flagged empty",
      {"block": "natural rate", "band": "1999-2007"} in m["empty_cells"],
      str(m["empty_cells"]))
check("unknown-year band never flagged", all(c["band"] != "?" for c in m["empty_cells"]))
check("sparse cells carry their only paper",
      all("only_paper" in c for c in m["sparse_cells"]))
check("empty input errors cleanly",
      gap.coverage_matrix([], ["x"])["ok"] is False)

# ── stated-gap mining ────────────────────────────────────────────────────────

print("\n== mine_stated_gaps ==")
from citens.grounding.fulltext import slugify

with tempfile.TemporaryDirectory() as td:
    fdir = Path(td)
    good = ps[0]
    (fdir / f"{slugify(good.title)[:80]}.txt").write_text(
        "Introduction. We study the natural rate. "
        "Nothing here triggers the miner.\n\n"
        "5 Limitations\n"
        "The natural rate remains unclear under fiscal dominance regimes. "
        "We could not observe expectations directly at monthly frequency.\n"
        "Another paragraph. Future work should examine survey-based measures "
        "of the natural rate, but this sentence is fine too.\n\n"
        "6 Conclusion\nThe estimates are stable.",
        encoding="utf-8",
    )
    # eight cue sentences -> per-paper cap of 5
    (fdir / f"{slugify(ps[1].title)[:80]}.txt").write_text(
        "Limitations\n" + " ".join(
            f"Aspect {i} remains unclear in the postwar sample." for i in range(8)
        ),
        encoding="utf-8",
    )
    mg = gap.mine_stated_gaps(fdir, ps, limit=40)
    check("mine ok over fixture dir", mg["ok"] and mg["scanned_files"] == 2)
    good_hits = [h for h in mg["hits"] if h["doi"] == "10.1/a"]
    check("cue sentence extracted verbatim (span checkable)",
          any("remains unclear under fiscal dominance" in h["span"] for h in good_hits),
          str([h["span"][:60] for h in good_hits]))
    check("section tag from the preceding header",
          any(h["section"] == "limitations" for h in good_hits))
    check("cue word recorded", all(h["cue"] for h in mg["hits"]))
    check("per-paper cap respected",
          sum(1 for h in mg["hits"] if h["doi"] == "10.1/b") == 5,
          str(sum(1 for h in mg["hits"] if h["doi"] == "10.1/b")))
    bad = gap.mine_stated_gaps(Path(td) / "nope", ps)
    check("missing dir is a clean error", bad["ok"] is False and "fetch" in bad["error"])

# ── novelty check (BM25-only: embedding setting blanked) ────────────────────

print("\n== novelty_check ==")
settings.screen_embedding_model = ""
nv = gap.novelty_check("no work has studied the natural rate under fiscal dominance", ps)
check("nearest neighbour is the fiscal paper",
      "fiscal" in nv["neighbors"][0]["title"].lower(), str(nv["neighbors"][0]))
check("high-overlap verdict fires",
      "可能已被" in nv["verdict"] or "高重叠" in nv["verdict"], nv["verdict"][:40])
nv2 = gap.novelty_check("quantum error correction for topological superconductors", ps)
check("unrelated statement gets the weak-evidence warning",
      "弱证据" in nv2["verdict"], nv2["verdict"][:40])
check("empty statement errors cleanly",
      gap.novelty_check("", ps)["ok"] is False)

# ── CLI wiring (subprocess: also exercises the argparse registration; an
# in-process importlib load of the driver proved flaky on this machine's
# D:\Desktop — grep sees the file, exec_module transiently does not) ────────

print("\n== cmd_gaps (CLI) ==")
import os
import subprocess

with tempfile.TemporaryDirectory() as td:
    rd = Path(td) / "run"
    rd.mkdir()
    with (rd / "pool.jsonl").open("w", encoding="utf-8") as fh:
        for p in ps:
            fh.write(json.dumps(p.model_dump(), ensure_ascii=False) + "\n")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"),
         str(ROOT / "drivers" / "citlens_tools.py"),
         "gaps", "--run-dir", str(rd),
         "--queries", "natural rate", "monetary policy",
         "--check", "the natural rate under fiscal dominance",
         "--limit", "8"],
        capture_output=True, text=True, timeout=180, env=env, check=False,
    )
    out = json.loads(r.stdout)
    check("CLI gaps returns coverage + novelty", out.get("ok") and "coverage" in out
          and "novelty" in out and out.get("n") == 4,
          str({k: out.get(k) for k in ("ok", "n", "error")}))
    r2 = subprocess.run(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"),
         str(ROOT / "drivers" / "citlens_tools.py"), "gaps", "--run-dir", str(rd)],
        capture_output=True, text=True, timeout=180, env=env, check=False,
    )
    out2 = json.loads(r2.stdout)
    check("no channel requested -> clean error", out2.get("ok") is False)

print(f"\n{'ALL PASS' if not FAIL else 'FAILURES: ' + str(FAIL)} ({len(PASS)} checks)")
sys.exit(1 if FAIL else 0)
