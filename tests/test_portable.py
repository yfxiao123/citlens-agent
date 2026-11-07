#!/usr/bin/env python
"""test_portable.py — offline verification of the citlens-agent tool.

Two things are checked, both without network and without touching the user's
real agent configs:

1. the CLI front end dispatches correctly (tool catalogue, real tool calls,
   error paths, exit-code contract, stdout purity) — every call is a real
   subprocess, exactly how an agent invokes it;
2. `install.py` discovers the repo and plans/applies idempotently against a
   throwaway HOME: shim + config + skill are written and LEGACY 1.x MCP
   registrations are cleaned up, never created.

Run:  python test_portable.py            (plain, no pytest needed)
      python -m pytest test_portable.py  (if pytest is available)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                  # the citlens-agent repo root
SERVER = ROOT / "citlens_cli.py"
INSTALL = ROOT / "install.py"

TOOLS = {"search", "pool", "fetch", "export", "audit", "screen", "verify",
         "expand", "notes", "dedup", "gaps", "status", "doctor"}

PASS, FAIL = [], []

for _stream in (sys.stdout, sys.stderr):
    try:  # a zh-CN console is GBK; config diffs contain non-GBK characters
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))


def _cli(config: Path, *args: str, timeout: float = 180.0) -> tuple[int, dict]:
    """Run the CLI exactly like an agent would; return (exit_code, payload)."""
    r = subprocess.run([sys.executable, str(SERVER), "--config", str(config), *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    try:
        return r.returncode, json.loads(r.stdout)
    except Exception:  # noqa: BLE001
        return r.returncode, {"_stdout": r.stdout[:400]}


def _temp_config() -> tuple[Path, Path]:
    """Repo paths (so doctor is meaningful) + a throwaway home AND jobs dir.

    Round-3 R1: this used install.discover(), which reads the REAL
    ~/.citlens/config.json and mkdirs the REAL data home — a fresh HOME came
    out of the suite with .citlens/home created. Hand-build the config from
    THIS checkout instead; the suite must never touch the real machine.
    """
    tmp = Path(tempfile.mkdtemp(prefix="citlens-test-"))
    home = tmp / "home"
    home.mkdir(parents=True)
    cfg = {
        "home": str(home),
        "python": sys.executable,
        "engine": str(ROOT),
        "recall_driver": str(ROOT / "drivers" / "citlens_recall.py"),
        "tools_driver": str(ROOT / "drivers" / "citlens_tools.py"),
        "jobs_dir": str(tmp / "jobs"),
    }
    cfg_path = tmp / "config.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return cfg_path, tmp


# ── CLI dispatch tests ───────────────────────────────────────────────────────


def test_protocol() -> None:
    print("\n== CLI dispatch ==")
    cfg_path, tmp = _temp_config()
    try:
        # catalogue
        code, cat = _cli(cfg_path, "tools")
        names = {t.get("name") for t in (cat.get("tools") or [])}
        check("tools exposes all thirteen tools", code == 0 and names == TOOLS,
              str(sorted(names)))
        check("every tool has a description and an object inputSchema", all(
            t.get("description") and (t.get("inputSchema") or {}).get("type") == "object"
            for t in cat.get("tools") or []))
        check("tools carries the discipline text",
              "literature" in (cat.get("discipline") or "").lower()
              and "planner" in (cat.get("discipline") or "").lower())
        search_schema = next(t for t in cat["tools"] if t["name"] == "search")["inputSchema"]
        check("search schema requires topic", search_schema.get("required") == ["topic"])
        check("search schema enumerates the eight families incl. policy", (
            search_schema["properties"]["families"]["items"].get("enum") or []
        ) == ["agent", "raw", "oa_title", "s2_rec", "snowball", "web", "survey",
              "policy"])
        check("search schema takes agent-crafted queries",
              "queries" in search_schema["properties"])
        check("search schema takes policy_queries",
              "policy_queries" in search_schema["properties"])
        screen_def = next(t for t in cat["tools"] if t["name"] == "screen")["inputSchema"]
        check("screen schema takes agent queries",
              "queries" in screen_def["properties"])
        verify_def = next(t for t in cat["tools"] if t["name"] == "verify")["inputSchema"]
        check("verify schema requires a review path",
              "review" in verify_def["properties"]
              and "review" in (verify_def.get("required") or []))
        expand_def = next(t for t in cat["tools"] if t["name"] == "expand")["inputSchema"]
        check("expand schema: topic required, seeds optional with from_notes",
              set(expand_def.get("required") or []) == {"topic"}
              and "from_notes" in expand_def["properties"]
              and "directions" in expand_def["properties"])
        notes_def = next(t for t in cat["tools"] if t["name"] == "notes")["inputSchema"]
        check("notes schema has verdict enum",
              notes_def["properties"]["verdict"].get("enum")
              == ["core", "uncertain", "off"])
        dedup_def = next(t for t in cat["tools"] if t["name"] == "dedup")["inputSchema"]
        check("dedup schema has merge flag", "merge" in dedup_def["properties"])
        export_def = next(t for t in cat["tools"] if t["name"] == "export")["inputSchema"]
        check("export formats include endnote + csljson",
              set(export_def["properties"]["format"]["enum"])
              == {"bib", "ris", "endnote", "csljson"})

        # doctor: a real, offline tool call — bare tool form (no `cli` prefix)
        code, doc = _cli(cfg_path, "doctor")
        check("doctor reports ok and exits 0",
              code == 0 and doc.get("ok") is True, str(doc.get("notes")))
        check("doctor never leaks key values", "sk-" not in json.dumps(doc))
        check("doctor lists env key names", "env_keys_present" in doc)
        check("doctor requires no LLM keys", doc.get("llm_keys_required") == [])

        # the exit-code contract: tool-reported failure -> 1, usage error -> 2
        code, fp = _cli(cfg_path, "fetch")
        check("fetch without doi/title/arxiv: clean error, exit 1",
              code == 1 and fp.get("ok") is False)
        code, bp = _cli(cfg_path, "search", "--topic", "x", "--families", "nope")
        check("unknown family is rejected without spawning a job",
              code == 1 and bp.get("ok") is False
              and "unknown families" in str(bp.get("error")))
        for tool in ("pool", "audit", "screen", "verify", "notes"):
            code, out = _cli(cfg_path, tool)
            check(f"{tool} without required args: clean error, exit 1",
                  code == 1 and out.get("ok") is False)
        code, ep = _cli(cfg_path, "expand", "--topic", "t")
        check("expand without seeds is a clean error",
              code == 1 and ep.get("ok") is False)
        code, up = _cli(cfg_path, "nope")
        check("unknown command: usage error (exit 2) with the tool list",
              code == 2 and "tools" in up)

        code, sp = _cli(cfg_path, "serve")
        check("serve answers with the 2.0 removal note, exit 2",
              code == 2 and "removed" in str(sp.get("error")))
        code, bare = _cli(cfg_path)
        check("bare invocation prints usage + tools + discipline, exit 2",
              code == 2 and set(bare.get("tools") or []) == TOOLS
              and "discipline" in bare)

        # legacy explicit form still dispatches
        code, doc2 = _cli(cfg_path, "cli", "doctor")
        check("explicit `cli <tool>` form still works",
              code == 0 and doc2.get("ok") is True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── install tests ────────────────────────────────────────────────────────────


def _sandbox_home(tmp: Path) -> dict:
    env = dict(os.environ)
    env["USERPROFILE"] = str(tmp)   # Path.home() on Windows
    env["HOME"] = str(tmp)          # Path.home() on POSIX
    env["DSH_HOME"] = str(tmp / ".dsh")
    env["CODEX_HOME"] = str(tmp / ".codex")
    env["ZCODE_HOME"] = str(tmp / ".zcode")
    env.pop("CITLENS_CONFIG", None)
    env.pop("CITLENS_HOME", None)
    env.pop("CITLENS_PYTHON", None)
    env.pop("CITLENS_ENGINE", None)
    return env


def _run_install(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(INSTALL), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=300)


def test_install() -> None:
    print("\n== installer (sandbox HOME, legacy cleanup) ==")
    tmp = Path(tempfile.mkdtemp(prefix="citlens-home-"))
    # seed the sandbox like a REAL 1.x machine: other servers present AND
    # stale citlens MCP entries the 2.0 installer must clean up
    (tmp / ".codex").mkdir(parents=True)
    (tmp / ".codex" / "config.toml").write_text(
        'model = "deepseek-v4-flash"\n\n'
        "[mcp_servers.other]\ncommand = \"x\"\nargs = []\n\n"
        "# >>> citlens mcp (managed by ~/.citlens/install.py) >>>\n"
        "[mcp_servers.citlens]\ncommand = 'old-python'\nargs = ['citlens_mcp.py', 'serve']\n\n"
        "[mcp_servers.citlens.env]\nPYTHONUTF8 = '1'\n"
        "# <<< citlens mcp <<<\n",
        encoding="utf-8")
    (tmp / ".claude.json").write_text(json.dumps(
        {"numStartups": 12, "mcpServers": {
            "web-reader": {"type": "http", "url": "https://example.invalid/mcp"},
            "citlens": {"type": "stdio", "command": "old-python",
                        "args": ["citlens_mcp.py", "serve"]}}},
        ensure_ascii=False), encoding="utf-8")
    (tmp / ".zcode" / "cli").mkdir(parents=True)
    (tmp / ".zcode" / "cli" / "config.json").write_text(json.dumps(
        {"mcp": {"servers": {
            "firecrawl": {"type": "stdio", "command": "npx"},
            "citlens": {"type": "stdio", "command": "old-python"}}}},
        ensure_ascii=False), encoding="utf-8")
    dsh_profile = tmp / ".dsh" / "profiles" / "desktop"
    dsh_profile.mkdir(parents=True)
    (dsh_profile / "package.json").write_text(json.dumps(
        {"name": "dsh-profile-desktop", "private": True,
         "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base"]}}}, indent=2),
        encoding="utf-8")
    env = _sandbox_home(tmp)
    try:
        st0 = _run_install(env, "status")
        check("status flags the stale 1.x registrations",
              st0.stdout.count("stale-mcp") >= 3, st0.stdout[-500:])

        plan = _run_install(env, "plan")
        check("plan runs", plan.returncode == 0, plan.stderr[-400:])
        check("plan writes nothing", not (tmp / ".citlens" / "config.json").exists())
        check("plan previews the legacy cleanup",
              "would remove" in plan.stdout and "would write CLI shim" in plan.stdout)

        apply1 = _run_install(env, "apply", "--no-dsh-auto")
        check("apply runs", apply1.returncode == 0, apply1.stderr[-400:])
        cfg = json.loads((tmp / ".citlens" / "config.json").read_text(encoding="utf-8"))
        check("shared config written with absolute repo paths",
              Path(cfg["python"]).is_file() and Path(cfg["recall_driver"]).is_file()
              and Path(cfg["tools_driver"]).is_file())
        check("apply creates the data home", Path(cfg["home"]).is_dir())
        check("config lists all eight families (policy included)",
              len(cfg.get("families") or []) == 8 and "policy" in cfg["families"])
        check("CLI shim written", (tmp / ".citlens" / "bin" / "citlens.cmd").is_file())
        shim = (tmp / ".citlens" / "bin" / "citlens.cmd").read_text(encoding="utf-8")
        check("shim targets citlens_cli.py with the bare tool form",
              "citlens_cli.py" in shim and " serve" not in shim)

        toml = (tmp / ".codex" / "config.toml").read_text(encoding="utf-8")
        check("codex: pre-existing model line kept", 'model = "deepseek-v4-flash"' in toml)
        check("codex: pre-existing mcp server kept", "[mcp_servers.other]" in toml)
        check("codex: stale citlens block REMOVED",
              "[mcp_servers.citlens]" not in toml and "citlens mcp" not in toml)
        check("codex: backup written", any(p.name.startswith("config.toml.citlens-backup-")
                                           for p in (tmp / ".codex").iterdir()))

        claude = json.loads((tmp / ".claude.json").read_text(encoding="utf-8"))
        check("claude: existing server kept", "web-reader" in claude["mcpServers"])
        check("claude: existing top-level keys kept", claude.get("numStartups") == 12)
        check("claude: stale citlens entry REMOVED",
              "citlens" not in claude["mcpServers"])

        zcode = json.loads((tmp / ".zcode" / "cli" / "config.json").read_text(encoding="utf-8"))
        check("zcode: existing server kept", "firecrawl" in zcode["mcp"]["servers"])
        check("zcode: stale citlens entry REMOVED",
              "citlens" not in zcode["mcp"]["servers"])

        check("dsh: no bundle written (MCP machinery gone)",
              not (tmp / ".citlens" / "dsh-bundle").exists())

        for target in (tmp / ".agents" / "skills" / "citlens",
                       tmp / ".claude" / "skills" / "citlens",
                       tmp / ".zcode" / "skills" / "citlens"):
            check(f"skill distributed -> {target.relative_to(tmp)}",
                  (target / "SKILL.md").is_file()
                  and "name: citlens" in (target / "SKILL.md").read_text(encoding="utf-8"))
        skill_md = (tmp / ".agents" / "skills" / "citlens" / "SKILL.md").read_text(encoding="utf-8")
        check("skill carries the verification chain",
              all(k in skill_md for k in ("six-grade", "verdicts.jsonl",
                                          "verify", "clean", "honesty")))
        check("skill is CLI-only (no MCP surface)",
              "MCP tools" not in skill_md and "mcp__citlens__" not in skill_md)

        # idempotency: a second apply must change nothing and add no new backup
        before = {p: len(list(p.parent.glob(p.name + ".citlens-backup-*")))
                  for p in (tmp / ".codex" / "config.toml",
                            tmp / ".claude.json",
                            tmp / ".zcode" / "cli" / "config.json")}
        apply2 = _run_install(env, "apply", "--no-dsh-auto")
        after = {p: len(list(p.parent.glob(p.name + ".citlens-backup-*"))) for p in before}
        check("second apply is idempotent (no new backups)", before == after, f"{before} -> {after}")
        check("second apply says nothing to do", "Nothing to do" in apply2.stdout,
              apply2.stdout[-900:])

        status = _run_install(env, "status")
        check("status reports everything clean after apply",
              "stale-mcp" not in status.stdout and "clean" in status.stdout,
              status.stdout[-800:])
        check("status reports the shim and the skill hub",
              "shim" in status.stdout and "skill hub" in status.stdout)
        check("status reports per-agent skill dirs", "Per-agent skill dirs:" in status.stdout)

        un = _run_install(env, "uninstall", "--no-dsh-auto")
        check("uninstall runs", un.returncode == 0, un.stderr[-400:])
        check("uninstall: skill dirs removed",
              not (tmp / ".agents" / "skills" / "citlens").exists())
        check("uninstall: config + shim stay (managed assets)",
              (tmp / ".citlens" / "config.json").is_file()
              and (tmp / ".citlens" / "bin" / "citlens.cmd").is_file())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_selftest() -> None:
    """Sandboxed: the old version ran selftest against the REAL HOME, so a
    fresh clone without `install.py apply` failed this one case (2.0 retest
    H1: 99/100) and the run created ~/.citlens dirs on the tester's machine."""
    print("\n== selftest (sandbox HOME) ==")
    tmp = Path(tempfile.mkdtemp(prefix="citlens-selftest-"))
    env = _sandbox_home(tmp)
    try:
        home = tmp / "home"
        (home / "data" / "litdb").mkdir(parents=True)
        jobs = tmp / "jobs"
        jobs.mkdir()
        cfg = {
            "home": str(home),
            "python": sys.executable,
            "recall_driver": str(ROOT / "drivers" / "citlens_recall.py"),
            "tools_driver": str(ROOT / "drivers" / "citlens_tools.py"),
            "jobs_dir": str(jobs),
        }
        cfg_path = tmp / "config.json"
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([sys.executable, str(SERVER), "selftest",
                            "--config", str(cfg_path)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=300)
        check("selftest exits 0 on a healthy (sandbox) install",
              r.returncode == 0, r.stdout[-600:])
        check("selftest lists the thirteen tools",
              all(w in r.stdout for w in ("search", "pool", "fetch", "export", "audit",
                                          "screen", "gaps", "verify", "expand",
                                          "notes", "dedup", "status", "doctor")))
        check("selftest reports the sandbox config, not the real one",
              str(cfg_path) in r.stdout, r.stdout[:200])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_registry() -> None:
    """The point of the registry: a new client is data, not code."""
    print("\n== agent registry (data-driven extension) ==")
    tmp = Path(tempfile.mkdtemp(prefix="citlens-reg-"))
    (tmp / ".codex").mkdir(parents=True)
    (tmp / ".codex" / "config.toml").write_text('model = "x"\n', encoding="utf-8")
    env = _sandbox_home(tmp)
    try:
        listing = _run_install(env, "list")
        check("list runs", listing.returncode == 0, listing.stderr[-300:])
        check("list shows the mainstream clients",
              all(n in listing.stdout for n in ("cursor", "windsurf", "gemini", "opencode",
                                                "cline", "zed", "aider")))

        snip = _run_install(env, "snippet", "zed")
        check("snippet answers with the 2.0 removal note",
              snip.returncode == 2 and "removed" in snip.stdout)

        # drop a brand-new client into ~/.citlens/agents.d and install it:
        # its skill dir is data-driven; no MCP registration exists to write
        (tmp / ".citlens" / "agents.d").mkdir(parents=True)
        (tmp / ".citlens" / "agents.d" / "custom.json").write_text(json.dumps({
            "agents": {"myagent": {
                "label": "My Agent",
                "dialect": "json-map",
                "file": "~/.myagent/mcp.json",
                "container": ["mcpServers"],
                "skillDirs": ["~/.myagent/skills"],
            }}
        }), encoding="utf-8")
        listing2 = _run_install(env, "list")
        check("a user-registered client appears without code changes",
              "myagent" in listing2.stdout)

        applied = _run_install(env, "apply", "--only", "myagent", "--no-dsh-auto")
        target = tmp / ".myagent" / "skills" / "citlens" / "SKILL.md"
        check("apply installs the skill for a custom client",
              applied.returncode == 0 and target.is_file(),
              applied.stdout[-300:])
        check("apply writes NO mcp.json for a custom client",
              not (tmp / ".myagent" / "mcp.json").exists())

        # --only still installs the shared prelude (config + shim + hub): that is
        # shared infrastructure, not per-agent state. It must not touch other agents.
        check("--only still writes the shared prelude", (tmp / ".citlens" / "config.json").is_file())
        codex_after = (tmp / ".codex" / "config.toml").read_text(encoding="utf-8")
        check("--only leaves other agents' configs untouched",
              "citlens" not in codex_after)

        removed = _run_install(env, "uninstall", "--only", "myagent", "--no-dsh-auto")
        check("uninstall removes the custom client's skill",
              removed.returncode == 0 and not target.exists())

        # a config file we cannot parse must never be "repaired" into emptiness
        # (the legacy-cleanup path reads it; failure to parse = leave alone)
        bad = tmp / ".badagent" / "mcp.json"
        bad.parent.mkdir(parents=True)
        bad.write_text('{\n  // json5 comment\n  "mcpServers": {}\n}\n', encoding="utf-8")
        (tmp / ".citlens" / "agents.d" / "bad.json").write_text(json.dumps({
            "agents": {"badagent": {"label": "Bad", "dialect": "json-map",
                                    "file": "~/.badagent/mcp.json",
                                    "container": ["mcpServers"]}}
        }), encoding="utf-8")
        bad_run = _run_install(env, "apply", "--only", "badagent", "--no-dsh-auto")
        check("unparsable client config is left untouched, not overwritten",
              bad_run.returncode == 0 and bad.read_text(encoding="utf-8").startswith("{\n  //"))

        # --all covers every registry entry (skill dirs), never creates configs
        all_run = _run_install(env, "apply", "--all", "--no-dsh-auto")
        check("apply --all writes no absent-client config files",
              all_run.returncode == 0 and not (tmp / ".cursor" / "mcp.json").exists()
              and not (tmp / ".config" / "opencode" / "opencode.json").exists())
        check("apply --all still distributes absent clients' skill dirs",
              (tmp / ".cursor" / "skills" / "citlens" / "SKILL.md").is_file())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_engine_override_and_driver_scoping() -> None:
    print("\n== installer engine/driver scoping (sandbox HOME) ==")
    tmp = Path(tempfile.mkdtemp(prefix="citlens-scope-"))
    # an old, coherent install living elsewhere with its own drivers
    old_engine = tmp / "old-engine"
    (old_engine / "drivers").mkdir(parents=True)
    (old_engine / "drivers" / "citlens_recall.py").write_text("# old", encoding="utf-8")
    (old_engine / "drivers" / "citlens_tools.py").write_text("# old", encoding="utf-8")
    cc = tmp / ".citlens"
    cc.mkdir(parents=True)
    (cc / "config.json").write_text(json.dumps({
        "home": str(tmp / "old-home"),
        "python": sys.executable,
        "engine": str(old_engine),
        "recall_driver": str(old_engine / "drivers" / "citlens_recall.py"),
        "tools_driver": str(old_engine / "drivers" / "citlens_tools.py"),
        "jobs_dir": str(cc / "jobs"),
    }, ensure_ascii=False), encoding="utf-8")
    (tmp / "old-home").mkdir()
    # one detectable client, else apply exits "no agent detected"
    (tmp / ".zcode" / "cli").mkdir(parents=True)
    (tmp / ".zcode" / "cli" / "config.json").write_text(
        '{"mcp": {"servers": {}}}', encoding="utf-8")
    env = _sandbox_home(tmp)
    try:
        # 1) no --engine: a coherent old install is reused verbatim
        r1 = _run_install(env, "apply", "--no-dsh-auto")
        check("plain apply on coherent install runs",
              r1.returncode == 0, r1.stdout[-300:])
        cfg1 = json.loads((cc / "config.json").read_text(encoding="utf-8"))
        check("coherent old install keeps its engine",
              Path(cfg1["engine"]).resolve() == old_engine.resolve())
        check("coherent old install keeps its drivers",
              Path(cfg1["recall_driver"]).resolve()
              == (old_engine / "drivers" / "citlens_recall.py").resolve())

        # 2) explicit --engine <this repo>: engine AND drivers must switch
        # to this tree (measured bug 2026-10-18: --engine was silently
        # ignored against an existing config and old drivers survived)
        r2 = _run_install(env, "apply", "--no-dsh-auto",
                          "--engine", str(ROOT),
                          "--python", sys.executable, "--home", str(tmp))
        check("override apply runs", r2.returncode == 0, r2.stdout[-300:])
        cfg2 = json.loads((cc / "config.json").read_text(encoding="utf-8"))
        check("--engine wins over existing config",
              Path(cfg2["engine"]).resolve() == ROOT.resolve(),
              f"got {cfg2['engine']}")
        check("engine switch carries this tree's drivers",
              Path(cfg2["recall_driver"]).resolve()
              == (ROOT / "drivers" / "citlens_recall.py").resolve()
              and Path(cfg2["tools_driver"]).resolve()
              == (ROOT / "drivers" / "citlens_tools.py").resolve(),
              f"got {cfg2['recall_driver']} / {cfg2['tools_driver']}")

        # 3) --engine pointing at a THIRD tree (not the installer's repo, not
        # the old install): drivers must follow THAT tree. discover() resolves
        # drivers against the tree RUNNING the installer, so pre-H5 this wrote
        # engine=B with the installer-repo's drivers — a mixed config.
        tree_b = tmp / "tree-b"
        (tree_b / "drivers").mkdir(parents=True)
        (tree_b / "drivers" / "citlens_recall.py").write_text("# B", encoding="utf-8")
        (tree_b / "drivers" / "citlens_tools.py").write_text("# B", encoding="utf-8")
        r3 = _run_install(env, "apply", "--no-dsh-auto", "--engine", str(tree_b))
        check("apply --engine <third tree> runs", r3.returncode == 0,
              r3.stdout[-300:])
        cfg3 = json.loads((cc / "config.json").read_text(encoding="utf-8"))
        check("third-tree switch: drivers follow the NEW tree, not the installer's",
              Path(cfg3["recall_driver"]).resolve()
              == (tree_b / "drivers" / "citlens_recall.py").resolve()
              and Path(cfg3["tools_driver"]).resolve()
              == (tree_b / "drivers" / "citlens_tools.py").resolve(),
              f"engine={cfg3['engine']} got {cfg3['recall_driver']} / {cfg3['tools_driver']}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_init_wizard() -> None:
    print("\n== init wizard (tmp home, all keys optional) ==")
    tmp = Path(tempfile.mkdtemp(prefix="citlens-init-"))
    env = _sandbox_home(tmp)
    try:
        # non-interactive on an empty home: NOTHING is required -> rc 0
        r1 = _run_install(env, "init", "--home", str(tmp), "--non-interactive")
        check("init on empty home succeeds (no required keys)",
              r1.returncode == 0 and "MISSING (required)" not in r1.stdout,
              r1.stdout[-300:])
        check("init without sets writes nothing",
              not (tmp / ".env").exists())

        # scripted --set writes keys, never clobbers existing values
        r2 = _run_install(env, "init", "--home", str(tmp), "--non-interactive",
                          "--set", "SERPER_API_KEY=sp-1",
                          "--set", "SEMANTIC_SCHOLAR_API_KEY=s2-1")
        check("init --set records optional keys", r2.returncode == 0, r2.stdout[-300:])
        envp = (tmp / ".env").read_text(encoding="utf-8")
        check("env file holds the set keys", "SERPER_API_KEY=sp-1" in envp
              and "SEMANTIC_SCHOLAR_API_KEY=s2-1" in envp)
        _run_install(env, "init", "--home", str(tmp), "--non-interactive",
                     "--set", "OPENALEX_EMAIL=a@b.c")
        envp2 = (tmp / ".env").read_text(encoding="utf-8")
        check("second init keeps earlier keys", "SERPER_API_KEY=sp-1" in envp2
              and "OPENALEX_EMAIL=a@b.c" in envp2)

        # upsert replaces in place, no duplicates
        _run_install(env, "init", "--home", str(tmp), "--non-interactive",
                     "--set", "SERPER_API_KEY=sp-2")
        envp3 = (tmp / ".env").read_text(encoding="utf-8")
        check("upsert replaces value in place",
              "SERPER_API_KEY=sp-2" in envp3 and "SERPER_API_KEY=sp-1" not in envp3
              and envp3.count("SERPER_API_KEY=") == 1)

        # an LLM key, if present from engine days, is never required nor removed
        r5 = _run_install(env, "init", "--home", str(tmp), "--non-interactive",
                          "--set", "LLM_API_KEY=sk-legacy")
        check("init tolerates legacy LLM keys without requiring them",
              r5.returncode == 0 and "LLM_API_KEY=sk-legacy"
              in (tmp / ".env").read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_arg_parsing() -> None:
    print("\n== CLI arg parsing (multi-value list keys) ==")
    sys.path.insert(0, str(ROOT))
    import citlens_cli  # noqa: PLC0415

    name, args = citlens_cli._parse_cli_args(
        ["screen", "--topic", "t", "--queries", "sparse attention", "long context",
         "--limit", "5"])
    check("multi-value queries collected as a list",
          args.get("queries") == ["sparse attention", "long context"], str(args))
    check("scalar after the list still parsed", args.get("limit") == 5)
    name2, args2 = citlens_cli._parse_cli_args(
        ["search", "--topic", "t", "--families", "raw,web", "--append-pool"])
    check("comma-separated families still accepted",
          args2.get("families") == ["raw,web"] or args2.get("families") == ["raw", "web"])
    check("boolean flag becomes True", args2.get("append_pool") is True)
    name3, args3 = citlens_cli._parse_cli_args(
        ["expand", "--topic", "t", "--seeds", "10.1000/a", "2301.12345",
         "A Great Paper", "--directions", "backward", "recs"])
    check("expand seeds collected as a list",
          args3.get("seeds") == ["10.1000/a", "2301.12345", "A Great Paper"], str(args3))
    check("expand directions collected as a list",
          args3.get("directions") == ["backward", "recs"])
    check("tool name parsed", name == "screen" and name2 == "search"
          and name3 == "expand")


def test_config_migration() -> None:
    print("\n== families migration (engine-era 9-family config) ==")
    tmp = Path(tempfile.mkdtemp(prefix="citlens-migrate-"))
    home = tmp / "home"
    home.mkdir(parents=True)
    cfg_path = tmp / ".citlens" / "config.json"
    cfg_path.parent.mkdir(parents=True)
    nine = ["planned", "raw", "hyde", "pivot", "oa_title", "s2_rec",
            "snowball", "web", "survey"]
    cfg = {
        "home": str(home),
        "python": sys.executable,
        "engine": str(ROOT),
        "recall_driver": str(ROOT / "drivers" / "citlens_recall.py"),
        "tools_driver": str(ROOT / "drivers" / "citlens_tools.py"),
        # round-3 R1: without this, doctor falls back to the DEFAULT
        # ~\.citlens\jobs and mkdirs it on the real machine
        "jobs_dir": str(tmp / "jobs"),
        "families": nine,
        "target": 60,
    }
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    env = _sandbox_home(tmp)
    try:
        r = _run_install(env, "apply", "--only", "zcode")
        check("apply migrates the old config", r.returncode == 0,
              (r.stdout + r.stderr)[-400:])
        migrated = json.loads(cfg_path.read_text(encoding="utf-8"))
        eight = ["agent", "raw", "oa_title", "s2_rec", "snowball", "web",
                 "survey", "policy"]
        check("nine-family list becomes the current eight", migrated.get("families") == eight,
              str(migrated.get("families")))
        check("migration is reported, not silent", "migrated" in r.stdout, r.stdout[-300:])

        # doctor must refuse a config the server would reject
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        doc = subprocess.run(
            [sys.executable, str(SERVER), "cli", "--config", str(cfg_path), "doctor"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            env=env,  # sandboxed: never inherit the real machine's CITLENS_* env
        )
        payload = json.loads(doc.stdout) if doc.stdout.strip().startswith("{") else {}
        check("doctor flags an unsupported family list",
              payload.get("ok") is False and payload.get("families_invalid") ==
              ["planned", "hyde", "pivot"], str(payload)[:300])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print(f"server: {SERVER}")
    test_selftest()
    test_protocol()
    test_install()
    test_registry()
    test_engine_override_and_driver_scoping()
    test_init_wizard()
    test_cli_arg_parsing()
    test_config_migration()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
