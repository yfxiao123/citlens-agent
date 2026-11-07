"""Regression checks for the 2026-11-07 2.0 retest (test-report/21-*).

P1-2 (config propagation), the run_job failure path, caller-relative paths,
the fetch note branching and the tools-catalogue contract all live in the
front-end layer, so every check here drives citlens_cli directly.
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
import subprocess as _sp  # noqa: E402

# subprocess is a singleton module: any m.subprocess.run patch mutates it
# globally, and a later `import subprocess` sees the FAKE. Capture the real
# functions before any patching so the run_job section can restore them.
_REAL_RUN, _REAL_POPEN = _sp.run, _sp.Popen

# ── P1-2a: _run_driver_json injects CITLENS_HOME ────────────────────────────
print("== driver env propagation ==")
captured: dict = {}


def _fake_run(cmd, **kw):
    captured["cmd"] = cmd
    captured["env"] = kw.get("env") or {}

    class R:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""
    return R()


m.subprocess.run = _fake_run
cfg = {"python": sys.executable, "tools_driver": "x.py",
       "recall_driver": "y.py", "home": "D:/custom/home"}
m._run_driver_json(cfg, "tools", ["audit", "--topic", "t"])
check("sync driver calls carry CITLENS_HOME",
      captured["env"].get("CITLENS_HOME") == "D:/custom/home",
      str(captured["env"].get("CITLENS_HOME")))

# ── P1-2b: run-job receives the globally extracted --config ─────────────────
print("\n== run-job config propagation ==")
seen: dict = {}
m.run_job = lambda job_dir, config, kind: seen.update(job_dir=job_dir, config=config, kind=kind) or 0
m.main(["run-job", "--job-dir", "/jobs/j1", "--config", "/custom/config.json", "--kind", "search"])
check("run-job loads the caller's --config (not the default)",
      seen.get("config") == "/custom/config.json" and seen.get("job_dir") == "/jobs/j1",
      str(seen))
# start_job still forwards config_path to the runner argv (unchanged path)
import importlib  # noqa: E402

real_start = importlib.reload(m).start_job
with tempfile.TemporaryDirectory() as td:
    jobs = Path(td) / "jobs"
    jobs.mkdir()

    def _fake_popen(cmd, **kw):
        seen["runner_argv"] = cmd
        raise KeyboardInterrupt  # never actually spawn

    m.subprocess.Popen = _fake_popen
    try:
        cfg2 = {"python": sys.executable,
                "recall_driver": str(ROOT / "drivers" / "citlens_recall.py"),
                "home": str(Path(td)), "jobs_dir": str(jobs),
                "config_path": "/custom/config.json", "max_concurrent_jobs": 3}
        real_start(cfg2, "search", {"topic": "t"})
    except KeyboardInterrupt:
        pass
    finally:
        m.subprocess.Popen = m.subprocess.Popen
        import subprocess as _sp
        m.subprocess.Popen = _sp.Popen
argv = seen.get("runner_argv") or []
check("start_job forwards --config to the runner argv",
      "--config" in argv and argv[argv.index("--config") + 1] == "/custom/config.json",
      str(argv))

# ── P2: run_job failure path must not crash on run_dir ──────────────────────
print("\n== run_job failure path ==")
# the real run_job (m.run_job was stubbed above). NOTE: patching
# m.subprocess.run mutated the GLOBAL subprocess module (a singleton) —
# reload cannot undo that — so restore them before exercising the real path.
m.run_job = None
real_run_job = importlib.reload(m).run_job
m.subprocess.run = _REAL_RUN
m.subprocess.Popen = _REAL_POPEN
with tempfile.TemporaryDirectory() as td:
    jd = Path(td) / "job1"
    jd.mkdir()
    (jd / "payload.json").write_text(json.dumps({"topic": "t"}), encoding="utf-8")
    (jd / "state.json").write_text(json.dumps({"job_id": "job1", "state": "running"}), encoding="utf-8")
    (jd / "log.txt").write_text("", encoding="utf-8")
    # a driver path that cannot launch -> code -2 -> the old code raised
    # UnboundLocalError on run_dir in the emit line. The config is written to
    # a file and passed EXPLICITLY: run_job("") would load the real machine
    # config and actually spawn a search.
    bad_cfg = {"python": sys.executable, "recall_driver": "Z:/no/such/driver.py",
               "tools_driver": "Z:/no/such/driver.py", "home": td,
               "jobs_dir": td}
    cfg_file = Path(td) / "bad-config.json"
    cfg_file.write_text(json.dumps(bad_cfg), encoding="utf-8")
    rc = real_run_job(str(jd), str(cfg_file), "search")
    state = json.loads((jd / "state.json").read_text(encoding="utf-8"))
    check("failed driver -> state=failed, no UnboundLocalError, no run_dir",
          rc == 0 and state.get("state") == "failed"
          and "run_dir" not in state and state.get("error"),
          str(state))
    check("failure reason lands in the log",
          "FAILED" in (jd / "log.txt").read_text(encoding="utf-8"))

# ── P2: caller-relative paths resolve against the CALLER's cwd ──────────────
print("\n== caller-relative paths ==")
sent: dict = {}


def _capture_driver(cfg, kind, argv, timeout=0):
    sent["argv"] = argv
    return {"ok": True}


def _driver_result(result):
    def f(cfg, kind, argv, timeout=0):
        return dict(result)
    return f


m._run_driver_json = _capture_driver
m.tool_verify({"home": "D:/home"}, {"review": "review.md", "text_dir": "texts",
                                    "verdicts": "v.jsonl", "topic": "t"})
argv = sent.get("argv") or []
cwd = Path.cwd().resolve()
check("verify resolves --review against cwd",
      argv[argv.index("--review") + 1] == str(cwd / "review.md"), str(argv))
check("verify resolves --text-dir against cwd",
      argv[argv.index("--text-dir") + 1] == str(cwd / "texts"))
check("verify keeps --topic verbatim",
      argv[argv.index("--topic") + 1] == "t")
m.tool_export({"home": "D:/home"}, {"topic": "x", "out": "refs.bib"})
argv = sent.get("argv") or []
check("export resolves --out against cwd",
      argv[argv.index("--out") + 1] == str(cwd / "refs.bib"), str(argv))
abs_arg = str(cwd / "somewhere" / "r.md")
m.tool_verify({"home": "D:/home"}, {"review": abs_arg})
argv = sent.get("argv") or []
check("absolute paths pass through untouched",
      argv[argv.index("--review") + 1] == abs_arg)

# ── P2: fetch front-end note branches on what actually came back ────────────
print("\n== fetch note branching ==")
m._run_driver_json = _driver_result({"ok": True, "fulltext": True,
                                     "text_path": "x.txt", "note": ""})
out = m.tool_fetch({}, {"doi": "10.1/x"})
check("fulltext result keeps the grounding prefix",
      "ONLY grounding" in out["note"], out["note"][:80])

m._run_driver_json = _driver_result({"ok": True, "fulltext": False,
                                     "abstract": "we study momentum", "note": ""})
out = m.tool_fetch({}, {"doi": "10.1/x"})
check("abstract-only fallback is labelled abstract-only",
      "abstract-only" in out["note"], out["note"][:80])
m._run_driver_json = _driver_result({"ok": True, "fulltext": False,
                                     "abstract": "", "note": "driver said no"})
out = m.tool_fetch({}, {"doi": "10.1/x"})
check("no-abstract record is marked NOT citable",
      "cannot ground any claim" in out["note"] and "driver said no" in out["note"],
      out["note"][:90])
m._run_driver_json = _driver_result({"ok": False, "error": "boom"})
out = m.tool_fetch({}, {"doi": "10.1/x"})
check("driver error passes through without a note prefix",
      out.get("ok") is False and out.get("note") is None, str(out))

# ── P2: tools catalogue states the real CLI contract ─────────────────────────
print("\n== tools catalogue contract ==")
tools = {t["name"]: t for t in m.TOOL_DEFS}
for name in ("screen", "gaps", "expand"):
    desc = tools[name]["inputSchema"]["properties"]["background"]["description"]
    check(f"{name} background says synchronous (no detached default)",
          "ALWAYS synchronous" in desc and "DEFAULT TRUE" not in desc, desc[:80])
fetch_desc = tools["fetch"]["inputSchema"]["properties"]["background"]["description"]
check("fetch background is DEFAULT FALSE (opt-in detach)",
      "DEFAULT FALSE" in fetch_desc, fetch_desc[:80])
search_desc = tools["search"]["description"]
check("search description no longer claims wait_seconds default 45",
      "default 45" not in search_desc)

# ── round-2 H2: --run-dir resolves against the caller's cwd EVERYWHERE ──────
print("\n== run_dir path semantics unified ==")
m._run_driver_json = _capture_driver  # re-point at the argv-capturing stub
for tool_args, tool_fn, flag in (
        ({"topic": "x", "run_dir": "run/x"}, m.tool_export, "--run-dir"),
        ({"run_dir": "run/x", "queries": ["q"], "background": False},
         m.tool_screen, "--run-dir"),
        ({"run_dir": "run/x", "queries": ["q"], "background": False},
         m.tool_gaps, "--run-dir"),
        ({"run_dir": "run/x"}, m.tool_dedup, "--run-dir"),
        ({"doi": "10.1/x", "run_dir": "run/x"}, m.tool_fetch, "--run-dir")):
    sent.clear()
    tool_fn({"home": "D:/home"}, tool_args)
    argv = sent.get("argv") or []
    resolved = str((Path.cwd() / "run" / "x").resolve())
    check(f"{argv[0]} --run-dir resolves against cwd",
          flag in argv and argv[argv.index(flag) + 1] == resolved, str(argv))

# ── round-2 H3: _find_run_dir reads the 2.0 layout, never legacy runs/ ───────
print("\n== _find_run_dir layout ==")
real_find = m._find_run_dir
with tempfile.TemporaryDirectory() as td:
    home = Path(td)
    legacy = home / "runs" / "old-topic-20260101"
    legacy.mkdir(parents=True)
    (legacy / "review.md").write_text("stale", encoding="utf-8")
    import os as _os

    _os.utime(legacy)  # fresh mtime: a 1.x leftover that LOOKS recent
    found = real_find({"home": str(home)}, "fetch", 0)
    check("legacy runs/ is never scanned (1.x leftovers not misattributed)",
          found is None, str(found))
    modern = home / "citlens-runs" / "t-20261107"
    modern.mkdir(parents=True)
    (modern / "pool.jsonl").write_text("{}", encoding="utf-8")
    found2 = real_find({"home": str(home)}, "search", 0)
    check("search jobs find citlens-runs run dirs",
          found2 is not None and "citlens-runs" in str(found2), str(found2))

# ── round-3 R2: pool resolves a relative --run-dir against the CALLER's cwd ───
print("\n== round-3: pool run_dir semantics ==")
_, where = m._pool_path_for({"home": "D:/home"}, run_dir="run/x", topic=None)
cwd = Path.cwd().resolve()
check("pool: relative run_dir resolves against the caller's cwd, not home",
      where == f"no pool.jsonl under {cwd / 'run' / 'x'}", where)
with tempfile.TemporaryDirectory() as td:
    work = Path(td) / "work"
    (work / "run" / "x").mkdir(parents=True)
    (work / "run" / "x" / "pool.jsonl").write_text(
        json.dumps({"doi": "10.1/x", "title": "caller-cwd pool"}) + "\n",
        encoding="utf-8")
    home = Path(td) / "home"
    home.mkdir()
    old = _os.getcwd()
    _os.chdir(work)
    try:
        out = m.tool_pool({"home": str(home)}, {"run_dir": "run/x"})
    finally:
        _os.chdir(old)
    check("pool finds the pool.jsonl under the caller's cwd",
          out.get("ok") is True and out.get("total") == 1, str(out)[:120])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
