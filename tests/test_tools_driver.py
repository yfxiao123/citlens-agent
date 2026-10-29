"""Offline tests for drivers/citlens_tools.py fetch basics — the minimal-record
path (no pool to resolve from) must build a valid Paper and never crash on
required-str fields.

Dogfooded 2026-10-28: fetch --title without a pool raised ValidationError
(url=None) and killed every title-only fetch. These checks pin the fix.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    "tools_mod", ROOT / "drivers" / "citlens_tools.py")
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} - {name}" + (f" ({detail})" if detail and not cond else ""))


def _args(**kw):
    base = {"topic": None, "run_dir": None, "doi": None, "title": None,
            "arxiv": None, "text_dir": None}
    base.update(kw)
    return argparse.Namespace(**base)


# no pool, no network: fetch_fulltext stubbed — these tests exercise the
# record-construction path only
tools.fetch_fulltext = lambda paper: None

print("== fetch minimal-record path ==")
out = tools.cmd_fetch(_args(title="Some Paper Title"))
check("title-only fetch survives (url bug)", out.get("ok") is True, str(out.get("error")))
check("title-only fetch reports abstract-only posture",
      out.get("fulltext") is False and "仅摘要级" in (out.get("note") or ""))

out = tools.cmd_fetch(_args(arxiv="2401.12345"))
check("arxiv fetch builds the abs url",
      out.get("ok") is True and out.get("doi") == "10.48550/arXiv.2401.12345")

out = tools.cmd_fetch(_args())
check("no identifier at all is a clean error",
      out.get("ok") is False and "--doi" in (out.get("error") or ""))

print(f"\n{'ALL PASS' if not FAIL else 'FAILURES: ' + str(FAIL)} ({len(PASS)} checks)")
sys.exit(1 if FAIL else 0)
