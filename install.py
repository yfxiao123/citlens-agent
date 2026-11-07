#!/usr/bin/env python
"""install.py — put the CiteLens CLI where every agent on this machine can use it.

Agent-agnostic by design
------------------------
The interface is a shell command (`citlens.cmd <tool> ...` -> one JSON document
on stdout), and every agent that can run a command already speaks it. There is
no MCP server to register (removed in 2.0 — the CLI always was the primary
interface). What this installer does:

  * writes the shared config (`~/.citlens/config.json`) that points every
    invocation at ONE data home, so an agent that searched can hand its pool
    to an agent that writes the review;
  * writes the CLI shim (`~/.citlens/bin/citlens.cmd`) that agents call;
  * installs the skill (`~/.agents/skills/citlens` + per-client skill dirs
    from `agents.json` / `~/.citlens/agents.d/`) so the *method* travels to
    clients that read skills;
  * CLEANS UP legacy MCP registrations left by 1.x installs (the server file
    they point at no longer exists — a dead entry in a client config).

The declarative registry (`agents.json`) still drives per-client knowledge:
where each client keeps its config (for legacy cleanup) and its skill dirs.
Adding an agent is adding an entry there — or dropping your own JSON into
`~/.citlens/agents.d/` (same schema; your entry wins). No code change.

Usage
-----
    python install.py list                     # every known client, detected or not
    python install.py status                   # CLI assets + stale registrations
    python install.py plan                     # dry run of apply (detected clients)
    python install.py apply                    # shim + config + skill + legacy cleanup
    python install.py apply --only cursor,gemini
    python install.py uninstall                # remove only what this script added

Safety: client config files are only ever edited to REMOVE a legacy citlens
MCP entry, with a `<file>.citlens-backup-<ts>` copy first; TOML edits strip
between `# >>> citlens ...>>>` markers; JSON edits remove only the one
`citlens` key, and a skill dir is only deleted when its SKILL.md says
`name: citlens`. The shim and the skill copy are managed/regenerated files
and are intentionally not backed up; `uninstall` removes this installer's
skill copies and any legacy registrations but leaves `~/.citlens/config.json`,
the shim and the data home in place. No secret is ever written (keys stay in
the data home's `.env`).
"""


from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # the citlens-agent repo root
REPO_ROOT = HERE                                 # this repo IS the retrieval core

SERVER = HERE / "citlens_cli.py"
SKILL_SRC = HERE / "skill" / "citlens"
REGISTRY_FILE = HERE / "agents.json"

USER = Path.home()
CITLENS_DIR = USER / ".citlens"
CONFIG_PATH = CITLENS_DIR / "config.json"
STATE_PATH = CITLENS_DIR / "state.json"
AGENTS_D = CITLENS_DIR / "agents.d"
BUNDLE_DIR = CITLENS_DIR / "dsh-bundle"
JOBS_DIR = CITLENS_DIR / "jobs"
SHIM_PATH = CITLENS_DIR / "bin" / "citlens.cmd"
SKILL_HUB = USER / ".agents" / "skills"

MCP_START = "# >>> citlens mcp (managed by ~/.citlens/install.py) >>>"
MCP_END = "# <<< citlens mcp <<<"
SKILL_START = "# >>> citlens skill (managed by ~/.citlens/install.py) >>>"
SKILL_END = "# <<< citlens skill <<<"

DSH_BUNDLE_NAME = "@local/dsh-citlens-mcp"  # legacy 1.x bundle (cleanup only)
SERVER_NAME = "citlens"   # the legacy MCP key this installer cleans up


# ── registry ─────────────────────────────────────────────────────────────────


def load_registry() -> dict:
    """agents.json (built in) <- ~/.citlens/agents.d/*.json (user additions win)."""
    try:
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"cannot read registry {REGISTRY_FILE}: {e}")
    agents = dict(data.get("builtin") or {})
    if AGENTS_D.is_dir():
        for f in sorted(AGENTS_D.glob("*.json")):
            try:
                extra = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for name, entry in (extra.get("agents") or extra).items():
                if isinstance(entry, dict) and not name.startswith("_"):
                    agents[name] = {**agents.get(name, {}), **entry}
    return agents


def expand(p: str | None) -> Path | None:
    if not p:
        return None
    return Path(os.path.expandvars(os.path.expanduser(str(p))))


def entry_file(entry: dict) -> Path | None:
    return expand(entry.get("file"))


def is_detected(entry: dict) -> bool:
    for cand in entry.get("detect") or []:
        p = expand(cand)
        if p and p.exists():
            return True
    f = entry_file(entry)
    return bool(f and f.is_file())


def detected_agents(registry: dict) -> list[str]:
    return [n for n, e in registry.items() if is_detected(e)]


# ── discovery of the engine ─────────────────────────────────────────────────


def _first_existing(*cands) -> Path | None:
    for c in cands:
        if not c:
            continue
        p = expand(str(c))
        if p and p.exists():
            return p
    return None


def _existing_config() -> dict:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _drivers() -> tuple[str, str]:
    """The two driver scripts this repo ships."""
    base = HERE / "drivers"
    return str(base / "citlens_recall.py"), str(base / "citlens_tools.py")


def discover() -> dict:
    """Resolve repo / interpreter / drivers / data home.

    Priority: explicit environment, then an existing valid `~/.citlens/config.json`
    (so a fresh clone on an already-configured machine reuses the working
    install instead of writing broken paths), then the on-disk layout.

    This repo IS the retrieval core (`citens/` package at the root, LLM-free),
    so "engine" and the repo are the same thing.
    """
    old = _existing_config()
    env_engine = os.environ.get("CITLENS_ENGINE")
    engine = _first_existing(
        env_engine,
        old.get("engine") if env_engine is None else None,
        HERE if (HERE / "citens").is_dir() else None,
    )
    python = _first_existing(
        os.environ.get("CITLENS_PYTHON"),
        old.get("python") if engine and old.get("engine") and str(engine) == str(old.get("engine")) else None,
        (engine / ".venv" / "Scripts" / "python.exe") if engine else None,
        (engine / ".venv" / "bin" / "python") if engine else None,
        sys.executable,
    )
    home = _first_existing(
        os.environ.get("CITLENS_HOME"),
        old.get("home"),
    ) or (CITLENS_DIR / "home")  # default data home; `apply` creates it
    # Driver choice lives HERE, not in discover(): reuse of an old install's
    # drivers is decided in cmd_apply() once explicit overrides are known.
    recall_drv, tools_drv = _drivers()
    return {
        "home": str(home) if home else None,
        "python": str(python) if python else sys.executable,
        "engine": str(engine) if engine else None,
        "recall_driver": recall_drv,
        "tools_driver": tools_drv,
        "jobs_dir": str(JOBS_DIR),
        "sources": ["arxiv", "semantic_scholar", "openalex", "crossref"],
        "families": ["agent", "raw", "oa_title", "s2_rec", "snowball", "web",
                     "survey", "policy"],
        "target": 60,
        # 20, not 45: interactive callers get the job_id early instead of a
        # held shell (history: MCP clients hard-killed a call at 30s and the
        # kill took the freshly spawned runner with it). Matches
        # citlens_cli.DEFAULT_CONFIG (third-party report flagged the 45/20
        # doc-vs-source mismatch).
        "wait_seconds": 20,
        "max_concurrent_jobs": 3,
    }


# ── planning / io ───────────────────────────────────────────────────────────


class Plan:
    def __init__(self, dry_run: bool):
        self.dry_run = dry_run
        self.changes: list[str] = []
        self.backups: list[str] = []

    def note(self, msg: str) -> None:
        self.changes.append(msg)
        print(("  [plan] " if self.dry_run else "  [done] ") + msg)

    def info(self, msg: str) -> None:
        print("  [info] " + msg)

    def backup(self, path: Path) -> None:
        if self.dry_run or not path.is_file():
            return
        ts = time.strftime("%Y%m%d-%H%M%S")
        bak = path.with_name(path.name + f".citlens-backup-{ts}")
        if bak.exists():
            bak = path.with_name(path.name + f".citlens-backup-{ts}-{len(self.backups)}")
        shutil.copy2(path, bak)
        self.backups.append(str(bak))
        print(f"  [backup] {bak}")

    def write_text(self, path: Path, text: str) -> bool:
        try:
            if path.is_file():
                with path.open(encoding="utf-8", newline="") as fh:
                    if fh.read() == text:
                        return False
        except Exception:  # noqa: BLE001
            pass
        if self.dry_run:
            return True
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".citlens-tmp")
        tmp.write_text(text, encoding="utf-8", newline="")
        os.replace(tmp, path)
        return True


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except Exception:  # noqa: BLE001
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:  # noqa: BLE001
            return ""


def _load_json(path: Path, default: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else dict(default)
    except Exception:  # noqa: BLE001
        return dict(default)


def _load_json_checked(path: Path, default: dict) -> tuple[dict, bool]:
    """Read a client config, but never turn "unparsable" into "empty".

    An agent config can be JSON5-with-comments or mid-write. Overwriting it with
    a fresh object would silently destroy the user's settings, so the writers
    abort instead and leave the file (and the backup policy) alone.
    """
    if not path.is_file():
        return dict(default), True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return dict(default), False
    if not isinstance(data, dict):
        return dict(default), False
    return data, True


def _dump_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _strip_block(text: str, start: str, end: str) -> str:
    pat = re.compile(rf"^{re.escape(start)}\s*$.*?^{re.escape(end)}\s*$\n?", re.M | re.S)
    return pat.sub("", text)


def _upsert_block(text: str, start: str, end: str, body: str) -> str:
    text = _strip_block(text, start, end)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + ("\n" if text.strip() else "") + f"{start}\n{body.rstrip()}\n{end}\n"


# ── shared config + CLI shim + skill hub ────────────────────────────────────


def install_config(p: Plan, cfg: dict) -> None:
    existing = {}
    try:
        existing = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        existing = {}
    merged = {**cfg, **{k: v for k, v in existing.items() if v not in (None, "", [], {})}}
    # the six path keys are the machine layout under test — an explicit
    # `--engine/--python/--home` must win over whatever an old config says
    for key in ("home", "python", "engine",
                "recall_driver", "tools_driver", "jobs_dir"):
        merged[key] = cfg[key]
    # Migrate a config written by the engine/portable install: it lists the
    # engine's NINE families, and this build's `search` hard-rejects the three
    # LLM-era names (planned/hyde/pivot). Without this the first search after
    # `apply` fails with "unknown families" while doctor said ok.
    fams = merged.get("families")
    if not isinstance(fams, list) or not fams:
        merged["families"] = list(cfg["families"])
    else:
        kept = [f for f in fams if f in cfg["families"]]
        dropped = [f for f in fams if f not in cfg["families"]]
        if dropped:
            # the engine-era list names three query-generating families
            # (planned/HyDE/pivot) where this build has ONE agent family;
            # an old config therefore migrates to six names — re-add agent.
            if "agent" not in kept:
                kept = ["agent", *kept]
            merged["families"] = kept
            p.note(f"config families: migrated {fams} -> {merged['families']}"
                   f" (dropped unsupported {dropped})")
    # `policy` joined the family list in 0.3.x; configs written before that
    # say seven families while the docs promise eight. It is discipline-gated
    # (only economics topics, or explicit policy_queries), so adding it is
    # safe even for non-economics users.
    fam_list = merged.get("families")
    if isinstance(fam_list, list) and fam_list and "policy" not in fam_list:
        merged["families"] = [*fam_list, "policy"]
        p.note("config families: added discipline-gated `policy` family")
    text = _dump_json(merged)
    if _read_text(CONFIG_PATH) == text:
        return
    if p.dry_run:
        p.note(f"would write shared config {CONFIG_PATH}")
        return
    p.backup(CONFIG_PATH)
    if p.write_text(CONFIG_PATH, text):
        p.note(f"shared config {CONFIG_PATH}")


def install_shim(p: Plan, cfg: dict) -> None:
    body = (
        "@echo off\r\n"
        "rem citlens CLI entry (managed by ~/.citlens/install.py)\r\n"
        "setlocal\r\n"
        'set "PYTHONUTF8=1"\r\n'
        'set "PYTHONIOENCODING=utf-8"\r\n'
        f'"{cfg["python"]}" "{SERVER}" --config "{CONFIG_PATH}" %*\r\n'
    )
    if _read_text(SHIM_PATH) == body:
        return
    if p.dry_run:
        p.note(f"would write CLI shim {SHIM_PATH}")
        return
    SHIM_PATH.parent.mkdir(parents=True, exist_ok=True)
    if p.write_text(SHIM_PATH, body):
        p.note(f"CLI shim {SHIM_PATH}")


def _skill_dir_is_ours(path: Path) -> bool:
    f = path / "SKILL.md"
    if not f.is_file():
        return False
    return bool(re.search(r"^name:\s*citlens\s*$", _read_text(f), re.M))


def _tree_equal(src: Path, dst: Path) -> bool:
    if not dst.is_dir():
        return False
    src_files = {p.relative_to(src): p for p in src.rglob("*") if p.is_file()}
    dst_files = {p.relative_to(dst): p for p in dst.rglob("*") if p.is_file()}
    if set(src_files) != set(dst_files):
        return False
    for rel, sp in src_files.items():
        try:
            if sp.read_bytes() != dst_files[rel].read_bytes():
                return False
        except Exception:  # noqa: BLE001
            return False
    return True


def skill_targets(registry: dict, names: list[str] | None = None) -> list[Path]:
    """The shared hub plus every skill directory of the agents being installed.

    The hub (`~/.agents/skills`) is the cross-agent convention and is always
    written; per-agent directories are only touched for agents actually present,
    so `apply` never litters a machine with skill dirs for absent clients.
    """
    out: list[Path] = [SKILL_HUB / "citlens"]
    wanted = set(names) if names is not None else set(registry)
    for name, entry in registry.items():
        if name not in wanted:
            continue
        for d in entry.get("skillDirs") or []:
            p = expand(d)
            if p:
                target = p / "citlens" if p.name != "citlens" else p
                if target not in out:
                    out.append(target)
    return out


def install_skills(p: Plan, registry: dict, names: list[str] | None = None) -> None:
    if not (SKILL_SRC / "SKILL.md").is_file():
        p.note(f"!! skill source missing: {SKILL_SRC}/SKILL.md")
        return
    for target in skill_targets(registry, names):
        if target.exists() and not _skill_dir_is_ours(target):
            p.note(f"!! refusing to overwrite foreign skill dir {target}")
            continue
        if _tree_equal(SKILL_SRC, target):
            continue
        if p.dry_run:
            p.note(f"would copy skill -> {target}")
            continue
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(SKILL_SRC, target)
        p.note(f"skill -> {target}")


def remove_skills(p: Plan, registry: dict) -> None:
    for target in skill_targets(registry):
        if not target.exists():
            continue
        if not _skill_dir_is_ours(target):
            p.info(f"leaving foreign skill dir alone: {target}")
            continue
        if p.dry_run:
            p.note(f"would remove skill {target}")
            continue
        shutil.rmtree(target)
        p.note(f"removed skill {target}")


# ── dialect writers ─────────────────────────────────────────────────────────


def _container(data: dict, path: list[str], create: bool) -> dict | None:
    node = data
    for key in path:
        nxt = node.get(key)
        if not isinstance(nxt, dict):
            if not create:
                return None
            nxt = {}
            node[key] = nxt
        node = nxt
    return node


def remove_simple(p: Plan, name: str, entry: dict, dry_run: bool) -> None:
    dialect = entry.get("dialect")
    if dialect == "dsh-bundle":
        remove_dsh(p, dry_run)
        return
    path = entry_file(entry)
    if not path or not path.is_file():
        p.info(f"{name}: no config file")
        return
    if dialect == "toml-block":
        text = _read_text(path)
        new = _strip_block(_strip_block(text, SKILL_START, SKILL_END), MCP_START, MCP_END)
        if new == text:
            p.info(f"{name}: nothing to remove")
            return
        if dry_run:
            p.note(f"would strip citlens blocks from {path}")
            return
        p.backup(path)
        p.write_text(path, new)
        p.note(f"{name} removed <- {path}")
        return
    data, ok = _load_json_checked(path, {})
    if not ok:
        p.info(f"{name}: {path} is not plain JSON; not touching it")
        return
    container = _container(data, list(entry.get("container") or ["mcpServers"]), create=False)
    if not container or SERVER_NAME not in container:
        p.info(f"{name}: nothing to remove")
        return
    del container[SERVER_NAME]
    if dry_run:
        p.note(f"would remove {SERVER_NAME} from {path}")
        return
    p.backup(path)
    p.write_text(path, _dump_json(data))
    p.note(f"{name} removed <- {path}")


# ── DSH (bundle-based) ──────────────────────────────────────────────────────


def dsh_home() -> Path:
    return expand(os.environ.get("DSH_HOME") or (USER / ".dsh"))  # type: ignore[return-value]


def _dsh_profile_has_bundle(profile_dir: Path) -> bool:
    try:
        pkg = json.loads((profile_dir / "package.json").read_text(encoding="utf-8"))
        return DSH_BUNDLE_NAME in (pkg.get("dsh", {}).get("profile", {}).get("bundles") or [])
    except Exception:  # noqa: BLE001
        return False


def remove_dsh(p: Plan, dry_run: bool, profile: str = "desktop", auto: bool = True) -> None:
    profile_dir = dsh_home() / "profiles" / profile
    if not _dsh_profile_has_bundle(profile_dir):
        p.info("dsh: nothing to remove")
        return
    if dry_run:
        p.note(f"would run: dsh plugin --profile {profile} remove {DSH_BUNDLE_NAME}")
        return
    dsh = shutil.which("dsh") or shutil.which("dsh.cmd")
    if auto and dsh:
        try:
            subprocess.run([dsh, "plugin", "--profile", profile, "remove", DSH_BUNDLE_NAME],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
        except Exception as e:  # noqa: BLE001
            p.note(f"!! dsh plugin remove failed: {e}")
    if _dsh_profile_has_bundle(profile_dir):
        p.note(f"!! still listed in {profile_dir / 'package.json'}; remove \"{DSH_BUNDLE_NAME}\" "
               "from dsh.profile.bundles by hand")
    else:
        p.note(f"dsh removed from profile '{profile}'")


# ── commands ────────────────────────────────────────────────────────────────


# ── init: interactive .env configuration wizard ─────────────────────────────

# NOTHING here is required: this build has no LLM and every source runs
# unauthenticated (rate-limited). Keys only raise quotas and un-degrade
# families, so the wizard is all-recommended, never blocking. Ordered by
# measured impact (same story as citens.keyguide — the doctor's key_guide).
INIT_KEYS: list[tuple[str, str, bool]] = [
    ("SEMANTIC_SCHOLAR_API_KEY",
     "S2 reliability: guaranteed 1 req/s instead of the shared pool's 3 s spacing + frequent 429s — free key at https://www.semanticscholar.org/product/api", False),
    ("SERPER_API_KEY",
     "web bridge primary engine (Google SERP), free 2,500 credits at https://serper.dev — without it the bridge falls back to keyless DuckDuckGo/Bing scraping that throttles hard", False),
    ("OPENALEX_API_KEY",
     "OpenAlex keyed pool: 10,000 credits/day instead of the anonymous 1,000 req/day that dies by mid-morning — request at https://openalex.org/premium", False),
    ("OPENALEX_EMAIL",
     "OpenAlex polite pool — any email you own, no registration", False),
    ("CROSSREF_EMAIL",
     "Crossref polite pool — any email you own, no registration", False),
]


def _read_env_pairs(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)\s*$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def _upsert_env(path: Path, updates: dict[str, str]) -> None:
    """KEY=value upsert: existing lines replaced in place, new keys appended.
    Existing values are NEVER touched unless the key is in `updates`."""
    lines = (path.read_text(encoding="utf-8", errors="replace").splitlines()
             if path.is_file() else [])
    for k, v in updates.items():
        pat = re.compile(rf"^\s*{re.escape(k)}\s*=")
        for idx, line in enumerate(lines):
            if pat.match(line):
                lines[idx] = f"{k}={v}"
                break
        else:
            lines.append(f"{k}={v}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_init(home: Path, *, non_interactive: bool, sets: list[str]) -> int:
    env_file = home / ".env"
    have = _read_env_pairs(env_file)
    updates: dict[str, str] = {}
    for s in sets:
        k, _, v = s.partition("=")
        if not k or "=" not in s:
            print(f"--set expects KEY=VALUE, got {s!r}")
            return 2
        updates[k.strip()] = v.strip()

    def missing(k: str) -> bool:
        return k not in have and k not in updates

    print(f"configuring {env_file}")
    if non_interactive:
        for k, desc, req in INIT_KEYS:
            state = (("MISSING (required)" if req else "missing (optional)")
                     if missing(k) else "present")
            print(f"  {k:<24} {state:<20} {desc}")
        if updates:
            _upsert_env(env_file, updates)
            print(f"  wrote {len(updates)} key(s)")
        still = [k for k, _, req in INIT_KEYS if req and missing(k)]
        if still:
            print(f"required keys still missing: {', '.join(still)}")
        print("next: `install.py apply` (or `--only <agent>`), then run the "
              "`doctor` tool from your agent")
        return 1 if still else 0
    for k, desc, req in INIT_KEYS:
        if not missing(k):
            print(f"  {k:<24} present — kept")
            continue
        try:
            val = input(f"  {k} ({'required' if req else 'optional'}) — {desc}\n    > ").strip()
        except EOFError:
            val = ""
        if val:
            updates[k] = val
        elif req:
            print(f"    skipped — {k} stays missing")
    if updates:
        _upsert_env(env_file, updates)
        print(f"wrote {len(updates)} key(s) to {env_file} — existing values untouched")
    final = _read_env_pairs(env_file)
    still = [k for k, _, req in INIT_KEYS if req and k not in final]
    if still:
        print(f"still missing required: {', '.join(still)} — the engine cannot run")
        return 1
    print("next: `install.py apply`, then run the doctor check:\n  "
          + str(SHIM_PATH) + " doctor")
    return 0


def cmd_list(registry: dict) -> int:
    det = set(detected_agents(registry))
    print(f"{'agent':<12} {'detected':<9} {'skill dirs':<9} config file / note")
    print("-" * 100)
    for name, entry in registry.items():
        f = entry_file(entry)
        loc = str(f) if f else (entry.get("note") or "")
        print(f"{name:<12} {'yes' if name in det else '-':<9} "
              f"{len(entry.get('skillDirs') or []):<9} {loc}")
    print(f"\n{len(det)} detected of {len(registry)} known. "
          "`apply` installs the shim + config + skill and cleans up 1.x MCP "
          "registrations on the detected ones.")
    print("Add your own client: drop a file into " + str(AGENTS_D) + " shaped like agents.json.")
    return 0


def _stale_registration(entry: dict) -> str:
    """'stale-mcp' when a 1.x citlens MCP entry is still present, else ''."""
    dialect = entry.get("dialect")
    path = entry_file(entry)
    if dialect == "dsh-bundle":
        for prof in ("desktop", "web"):
            pd = dsh_home() / "profiles" / prof
            if pd.is_dir() and _dsh_profile_has_bundle(pd):
                return "stale-mcp"
        return ""
    if not path or not path.is_file():
        return ""
    if dialect == "toml-block":
        return "stale-mcp" if MCP_START in _read_text(path) else ""
    if dialect in ("json-map", "json-opencode"):
        data = _load_json(path, {})
        container = _container(data, list(entry.get("container") or ["mcpServers"]),
                               create=False)
        return "stale-mcp" if container and SERVER_NAME in container else ""
    return ""


def cmd_status(registry: dict) -> int:
    cfg = discover()
    print("CiteLens CLI — installation status\n")
    print(f"cli         {SERVER}")
    print(f"shim        {SHIM_PATH}  ({'present' if SHIM_PATH.is_file() else 'MISSING'})")
    print(f"config      {CONFIG_PATH}  ({'present' if CONFIG_PATH.is_file() else 'MISSING'})")
    print(f"home        {cfg.get('home')}")
    print(f"python      {cfg.get('python')}")
    print(f"skill hub   {SKILL_HUB / 'citlens'}  "
          f"[{'present' if _skill_dir_is_ours(SKILL_HUB / 'citlens') else 'absent'}]")
    print()
    stale = 0
    for name, entry in registry.items():
        det = "detected" if is_detected(entry) else "not installed"
        mark = _stale_registration(entry)
        if mark:
            stale += 1
        path = entry_file(entry)
        print(f"{name:<12} {det:<14} {mark or 'clean':<10} {path or entry.get('note') or ''}")
    print()
    print("Per-agent skill dirs:")
    for t in skill_targets(registry):
        state = "present" if _skill_dir_is_ours(t) else ("FOREIGN" if t.exists() else "absent")
        print(f"  [{state:<7}] {t}")
    if stale:
        print(f"\n{stale} stale 1.x MCP registration(s) — `install.py apply` removes them.")
    print("\nVerify with:  " + str(SHIM_PATH) + " doctor")
    return 0


def _apply_one(p: Plan, registry: dict, cfg: dict, name: str, remove: bool,
               dry_run: bool, profile: str, dsh_auto: bool) -> None:
    """Per-agent work after 2.0: only LEGACY CLEANUP — remove a 1.x MCP
    registration pointing at the deleted server file. The interface itself
    (shim + config + skill) is client-agnostic and handled by the prelude."""
    entry = registry.get(name)
    print(f"\n== {name} ==")
    if not entry:
        p.note(f"!! unknown agent {name!r}; see `install.py list`")
        return
    dialect = entry.get("dialect")
    if dialect == "dsh-bundle":
        remove_dsh(p, dry_run, profile, dsh_auto)
    elif dialect in ("json-map", "json-opencode", "toml-block"):
        remove_simple(p, name, entry, dry_run)
    else:
        p.info(f"{name}: nothing registered (CLI-only client)")


def cmd_apply(registry: dict, names: list[str], *, dry_run: bool, remove: bool,
              profile: str, dsh_auto: bool, prelude: bool = True,
              overrides: dict | None = None) -> int:
    cfg = discover()
    overrides = {k: v for k, v in (overrides or {}).items() if v}
    if overrides:
        if overrides.get("engine") and not overrides.get("python"):
            eng = Path(overrides["engine"]).resolve()
            for venv in (eng / ".venv" / "Scripts" / "python.exe", eng / ".venv" / "bin" / "python"):
                if venv.is_file():
                    overrides.setdefault("python", str(venv))
                    break
        for key in ("engine", "python", "home"):
            if overrides.get(key):
                cfg[key] = str(Path(overrides[key]).expanduser().resolve())
    # Driver reuse is scoped: an already-configured machine keeps its old
    # drivers only when the engine resolves to that SAME old install and
    # nothing explicitly overrides the engine (--engine / CITLENS_ENGINE).
    # An explicit engine switch must carry this tree's own drivers — else a
    # fresh clone silently keeps running a diverged old driver copy
    # (measured 2026-10-18: `--engine .` left config.engine and both
    # drivers pointing at the previous tree while python switched).
    old = _existing_config()
    engine_explicit = bool(
        overrides.get("engine") or os.environ.get("CITLENS_ENGINE")
    )
    if not engine_explicit:
        old_recall = _first_existing(old.get("recall_driver"))
        old_tools = _first_existing(old.get("tools_driver"), old.get("review_driver"))
        if (old_recall and old_tools and cfg.get("engine")
                and str(cfg["engine"]) == str(old.get("engine"))):
            cfg["recall_driver"] = str(old_recall)
            cfg["tools_driver"] = str(old_tools)
    else:
        # An explicit engine switch must carry the NEW tree's drivers —
        # discover() resolved drivers against the tree RUNNING this installer
        # (checkout A), so `A/install.py apply --engine B` wrote engine=B with
        # A's drivers: a mixed config that silently kept executing a diverged
        # copy (third-party report, H5). Only retarget when the new tree
        # actually ships both drivers.
        eng = Path(cfg.get("engine") or "")
        drv_r, drv_t = (eng / "drivers" / "citlens_recall.py",
                        eng / "drivers" / "citlens_tools.py")
        if drv_r.is_file() and drv_t.is_file():
            cfg["recall_driver"] = str(drv_r)
            cfg["tools_driver"] = str(drv_t)
    if cfg.get("home") and not dry_run:
        try:
            Path(cfg["home"]).mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
    p = Plan(dry_run)
    if dry_run:
        print("DRY RUN — nothing will be written.\n")
    if prelude and not remove:
        install_config(p, cfg)
        install_shim(p, cfg)
        install_skills(p, registry, names)
    elif prelude and remove:
        remove_skills(p, registry)
    for name in names:
        _apply_one(p, registry, cfg, name, remove, dry_run, profile, dsh_auto)
    print()
    if p.changes:
        print(("Would change: " if dry_run else "Changed: ") + f"{len(p.changes)} item(s)")
    else:
        print("Nothing to do — already up to date.")
    if not remove:
        print("\nVerify with:\n"
              f'  "{cfg["python"]}" "{SERVER}" selftest\n'
              f"  {SHIM_PATH} doctor")
    if not dry_run:
        state = {"version": 1, "last_run": {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "uninstall" if remove else ("plan" if dry_run else "apply"),
            "agents": names,
        }, "backups": p.backups, "config": str(CONFIG_PATH), "server": str(SERVER)}
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(_dump_json(state), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    only: list[str] = []
    profile = "desktop"
    dsh_auto = True
    all_clients = False
    non_interactive = False
    set_pairs: list[str] = []
    overrides: dict = {}
    dry_run = cmd == "plan"
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == "--only" and i + 1 < len(rest):
            only = [x.strip() for x in rest[i + 1].split(",") if x.strip()]
            i += 2
        elif tok in ("--engine", "--home", "--python") and i + 1 < len(rest):
            overrides[tok[2:]] = rest[i + 1]
            i += 2
        elif tok == "--dsh-profile" and i + 1 < len(rest):
            profile = rest[i + 1]
            i += 2
        elif tok == "--no-dsh-auto":
            dsh_auto = False
            i += 1
        elif tok in ("--all", "-a"):
            all_clients = True
            i += 1
        elif tok == "--non-interactive":
            non_interactive = True
            i += 1
        elif tok == "--set" and i + 1 < len(rest):
            set_pairs.append(rest[i + 1])
            i += 2
        elif tok == "--dry-run":
            dry_run = True
            i += 1
        else:
            i += 1
    registry = load_registry()
    if cmd == "list":
        return cmd_list(registry)
    if cmd == "init":
        home = (Path(overrides["home"]).expanduser().resolve()
                if overrides.get("home")
                else Path(_existing_config().get("home") or (CITLENS_DIR / "home")))
        return cmd_init(home, non_interactive=non_interactive, sets=set_pairs)
    if cmd == "status":
        return cmd_status(registry)
    if cmd == "snippet":
        print("`snippet` was removed with the MCP server (2.0) — there is nothing "
              "to paste: every client uses the CLI shim.\n"
              f'  "{SHIM_PATH}" doctor')
        return 2
    if cmd not in ("plan", "apply", "uninstall"):
        print(f"unknown command {cmd!r}; use list | init | plan | apply | status | uninstall")
        return 2
    if only:
        names = only
        unknown = [n for n in names if n not in registry]
        if unknown:
            print(f"unknown agent(s): {', '.join(unknown)} — see `install.py list`")
            return 2
    elif all_clients:
        names = list(registry)
    else:
        names = detected_agents(registry)
        if not names:
            # No agent client detected is NOT a reason to write nothing: the
            # shared config + shim + skill are what a CLI user needs, and
            # INSTALL.md's first command is `plan` right after install.
            # The old code exited 1 here, so a fresh machine could not even
            # run `doctor` (third-party report, install-mcp P2-1).
            print("No agent client detected on this machine — writing the shared "
                  "config, shim and skill only.\nAdd a client's skill dirs later "
                  "with `install.py apply --only <agent>` (see `list`), or `--all`.")
            names = []
    return cmd_apply(registry, names, dry_run=dry_run or cmd == "plan",
                     remove=cmd == "uninstall", profile=profile, dsh_auto=dsh_auto,
                     overrides=overrides)


if __name__ == "__main__":
    sys.exit(main())
