#!/usr/bin/env python
"""citlens_mcp.py — CiteLens for agents: one MCP server, any client, no LLM key.

Why this file exists
--------------------
The agent-specific half of CiteLens (persona + skill + mode picker) cannot be
shared: Codex reads AGENTS.md, Claude reads CLAUDE.md, DSH reads bundles. What
*can* be shared is the part that actually finds literature. So the split is:

    this repo (retrieval core, LLM-free)  ->  this MCP server  ->  {codex, claude, zcode, dsh, ...}

Every one of those clients speaks MCP over stdio, so a single stdio server
gives all of them the same tools, the same retrieval method and — because they
all point at one CITLENS_HOME — the same literature pool. An agent that searches
here can hand its pool to another agent that writes the review.

The deliberate design decision: this server makes **zero LLM calls and needs
zero LLM keys**. The calling agent IS the model — it crafts the queries
(`queries`), supplies anchor titles (`title_probes`) and web phrasings
(`web_queries`), judges the relevance of the returned pool, and writes the
review under the skill's verification discipline. What the server owns is
everything mechanical and reproducible: the seven recall families, RRF fusion,
citation snowball, survey harvest, full-text fetch, BibTeX/RIS export, the
honest health buckets and the PRISMA exclusion log.

This file deliberately imports **nothing from citens**. It is a stdlib-only
supervisor that (a) speaks JSON-RPC 2.0 on stdin/stdout and (b) spawns the two
drivers — `citlens_recall.py` (seven-family recall) and `citlens_tools.py`
(fetch / export / audit / screen / verify) — in this repo's own interpreter. The retrieval method
therefore stays exactly where it is measured and tested; this layer adds no
retrieval logic of its own.

Subcommands
-----------
    serve       MCP stdio server (what the agents launch)
    run-job     internal: detached job runner, spawned by `serve`
    tools       print the tool list (debugging / docs)
    selftest    protocol + config smoke test, no network

Config
------
    %USERPROFILE%\\.citlens\\config.json     (written by install.py)
    $CITLENS_CONFIG                          override the file path
    $CITLENS_HOME                            override the data home
    $CITLENS_PYTHON                          override the repo interpreter

Protocol notes (so this stays maintainable)
-------------------------------------------
MCP stdio transport is newline-delimited JSON-RPC 2.0, one message per line,
UTF-8. stdout carries protocol frames ONLY; every log line goes to stderr. A
notification (no `id`) never gets a response. Unknown methods with an `id` get
-32601. Tool failures are reported as results with `isError: true`, never as
JSON-RPC errors, so the calling model can read the reason.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

SERVER_NAME = "citlens"
SERVER_VERSION = "1.1.0"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

_REPO_ROOT = Path(__file__).resolve().parent

ALL_FAMILIES = [
    "agent", "raw", "oa_title", "s2_rec", "snowball", "web", "survey",
]

# The retrieval discipline each tool result reminds the model about. These are
# the rules from the CiteLens skill that must survive the trip through a client
# that never read the skill at all (e.g. an agent that only sees the tool list).
INSTRUCTIONS = (
    "CiteLens literature search is available. For ANY literature/paper/survey "
    "question, call `search` instead of inventing your own search — and YOU are "
    "the planner: craft the English concept-block queries yourself (4-6 concepts "
    "x 2-4 synonyms, combination queries first) and pass them as `queries`; "
    "write 2-3 HyDE-style `title_probes` — hypothetical TITLES of the ideal "
    "paper in paper-side vocabulary — and check `query_feedback` in the result: "
    "empty/thin blocks mean vocabulary mismatch, rephrase them with "
    "method/dataset/task names. After you judge records core, feed them back: "
    "call `expand` with their DOIs/titles/arXiv ids — citation-chain + "
    "similarity expansion from YOUR seeds is the strongest recall lever (the "
    "bench measured 71% of missed golds unreachable by any query vocabulary). "
    "Record your verdicts with `notes` (core/uncertain/off + one line each) — "
    "they are the judgment memory, and `expand` from_notes=core seeds straight "
    "from them; `dedup` reports (and optionally merges) the preprint/published "
    "duplicates accumulating pools pick up. "
    "optionally `title_probes` (anchor papers you already know) and "
    "`web_queries` (English verbatim spans + natural Chinese phrasings). The "
    "tool runs seven recall families fused by RRF; it does NOT rank by relevance "
    "— band the pool with `screen` (core/uncertain/likely_off triage), then read "
    "the core+uncertain records yourself (title+abstract, paper by paper) before "
    "citing; batch-review the likely_off band and log every exclusion "
    "(PRISMA). Never claim coverage from your own web search. After a "
    "search, quote the numbers the tool reports (pool size, kept count, "
    "per-source ok/empty/failed) and never report a failed source as a zero-hit "
    "source. A search job can take minutes: pass wait_seconds, then poll "
    "`status`. For grounding use `fetch` (open-access full text or abstract "
    "fallback); before declaring a field covered run `audit` (survey-reference "
    "coverage); export citations with `export`. Writing a review is opt-in and "
    "YOUR job under the skill's verification discipline — every claim checked "
    "against the fetched source text, honesty numbers reported. Before "
    "delivering a review, call `verify` with the review path and your verdicts "
    "JSONL: it mechanically checks that every [n] resolves to the pool "
    "(honeypot) and that every quoted span occurs verbatim in the cited source, "
    "and it computes the honesty block. clean=false means fix, not ship."
)

# ── configuration ─────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "home": str(Path.home() / ".citlens" / "home"),
    "python": str((_REPO_ROOT / ".venv" / "Scripts" / "python.exe")
                  if os.name == "nt"
                  else (_REPO_ROOT / ".venv" / "bin" / "python")),
    "recall_driver": str(_REPO_ROOT / "drivers" / "citlens_recall.py"),
    "tools_driver": str(_REPO_ROOT / "drivers" / "citlens_tools.py"),
    "jobs_dir": r"~\.citlens\jobs",
    "sources": ["arxiv", "semantic_scholar", "openalex", "crossref"],
    "families": ALL_FAMILIES,
    "target": 60,
    "wait_seconds": 45,
    "max_concurrent_jobs": 3,
}


def _log(msg: str) -> None:
    """stderr only — stdout belongs to the protocol."""
    try:
        sys.stderr.write(f"[citlens-mcp] {msg}\n")
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass


def _expand(p: str | None) -> str | None:
    if not p:
        return None
    p = os.path.expandvars(os.path.expanduser(str(p)))
    return os.path.abspath(p)


def config_path(explicit: str | None = None) -> Path:
    for cand in (explicit, os.environ.get("CITLENS_CONFIG")):
        if cand:
            return Path(_expand(cand) or cand)
    return Path.home() / ".citlens" / "config.json"


def load_config(explicit: str | None = None) -> dict:
    """DEFAULTS <- config.json <- environment. Environment always wins so a
    per-agent registration can pin its own home without editing the file."""
    cfg = dict(DEFAULT_CONFIG)
    cfg["families"] = list(ALL_FAMILIES)
    path = config_path(explicit)
    if path.is_file():
        try:
            disk = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(disk, dict):
                cfg.update(disk)
        except Exception as e:  # noqa: BLE001
            _log(f"config {path} unreadable ({e}); using defaults")
    for env_key, cfg_key in (
        ("CITLENS_HOME", "home"),
        ("CITLENS_PYTHON", "python"),
        ("CITLENS_RECALL_DRIVER", "recall_driver"),
        ("CITLENS_TOOLS_DRIVER", "tools_driver"),
        ("CITLENS_JOBS_DIR", "jobs_dir"),
        ("CITLENS_WAIT_SECONDS", "wait_seconds"),
    ):
        val = os.environ.get(env_key)
        if val:
            cfg[cfg_key] = int(val) if cfg_key == "wait_seconds" else val
    for key in ("home", "python", "recall_driver", "tools_driver", "jobs_dir"):
        cfg[key] = _expand(cfg.get(key))
    cfg["config_path"] = str(path)
    return cfg


# ── small helpers ─────────────────────────────────────────────────────────────

_NON_ALNUM_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")


def slugify(text: str) -> str:
    """Byte-identical to citens.grounding.fulltext.slugify — pools are keyed by it."""
    return _NON_ALNUM_RE.sub("-", (text or "").lower()).strip("-")


def _iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time(), tz=timezone.utc).isoformat(
        timespec="seconds"
    )


def _pid_alive(pid: int | None) -> bool:
    """True if the process exists.

    On Windows os.kill(pid, 0) would TERMINATE the process (any signal other
    than the two console events is TerminateProcess), so use OpenProcess.
    """
    if not pid:
        return False
    try:
        if os.name == "nt":
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        os.kill(int(pid), 0)
        return True
    except Exception:  # noqa: BLE001
        return False


def _read_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write_json(path: Path, data: dict) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _tail_text(path: Path, n_lines: int = 12, max_chars: int = 4000) -> str:
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    out = "\n".join(lines[-n_lines:])
    return out[-max_chars:]


def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.replace("\n", ",").split(",") if x.strip()]
    return [str(x).strip() for x in v if str(x).strip()]


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except Exception:  # noqa: BLE001
        return default


# ── jobs ──────────────────────────────────────────────────────────────────────


def jobs_root(cfg: dict) -> Path:
    p = Path(cfg["jobs_dir"])
    p.mkdir(parents=True, exist_ok=True)
    return p


def job_state(cfg: dict, job_id: str) -> dict:
    d = jobs_root(cfg) / job_id
    st = _read_json(d / "state.json")
    if not st:
        return {"job_id": job_id, "state": "unknown", "hint": "no such job id"}
    st.setdefault("job_id", job_id)
    st["job_dir"] = str(d)
    st["log_path"] = str(d / "log.txt")
    if st.get("state") == "running" and not _pid_alive(st.get("pid")):
        # The runner died without writing a terminal state (client restart, kill,
        # reboot). Never lie about it: mark lost and point at the artifacts.
        st["state"] = "lost"
        st["hint"] = (
            "runner process is gone and wrote no exit state. The work may have "
            "completed: check `run_dir` / the log tail, then call status again "
            "after re-reading the artifacts."
        )
    return st


def _running_jobs(cfg: dict) -> list[dict]:
    out = []
    for d in sorted(jobs_root(cfg).iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        if not d.is_dir():
            continue
        st = _read_json(d / "state.json")
        if st.get("state") == "running" and _pid_alive(st.get("pid")):
            out.append(st)
    return out


def _find_run_dir(cfg: dict, kind: str, since: float) -> str | None:
    """Newest artifact directory the driver could have written for this job."""
    home = Path(cfg["home"])
    roots = [home / "citlens-runs"] if kind == "search" else [home / "runs"]
    best: tuple[float, str] | None = None
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for d in root.iterdir():
                if not d.is_dir():
                    continue
                m = d.stat().st_mtime
                if m + 5 < since:  # created before this job started
                    continue
                marker = "pool.jsonl" if kind == "search" else "review.md"
                if not ((d / marker).is_file() or (d / "meta.json").is_file()):
                    continue
                if best is None or m > best[0]:
                    best = (m, str(d))
        except OSError:
            continue
    return best[1] if best else None


def start_job(cfg: dict, kind: str, payload: dict) -> dict:
    """Spawn a DETACHED runner so the job survives this MCP server and its client.

    That detachment is the whole point: the user can start a 5-minute recall in
    Claude, close Claude, and read the pool from Codex a minute later.
    """
    python = cfg.get("python") or sys.executable
    driver = cfg.get("recall_driver") if kind == "search" else cfg.get("tools_driver")
    problems = []
    if not Path(python).is_file():
        problems.append(f"engine interpreter missing: {python}")
    if not driver or not Path(driver).is_file():
        problems.append(f"driver missing: {driver}")
    if not cfg.get("home") or not Path(cfg["home"]).is_dir():
        problems.append(f"data home missing: {cfg.get('home')}")
    if problems:
        return {
            "ok": False,
            "state": "rejected",
            "error": "; ".join(problems),
            "hint": "run the `doctor` tool; fix the paths in " + str(cfg.get("config_path")),
        }

    running = _running_jobs(cfg)
    if len(running) >= int(cfg.get("max_concurrent_jobs") or 3):
        return {
            "ok": False,
            "state": "rejected",
            "error": f"too many concurrent jobs ({len(running)}); max_concurrent_jobs="
            f"{cfg.get('max_concurrent_jobs')}",
            "running": [{"job_id": r.get("job_id"), "kind": r.get("kind"),
                         "topic": r.get("topic")} for r in running],
        }

    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    jd = jobs_root(cfg) / job_id
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "log.txt").write_text("", encoding="utf-8")
    started = time.time()
    state = {
        "job_id": job_id,
        "kind": kind,
        "state": "running",
        "topic": payload.get("topic"),
        "args": payload,
        "started_at": _iso(started),
        "started_ts": started,
        "pid": None,
        "home": cfg["home"],
    }
    _write_json(jd / "state.json", state)
    _write_json(jd / "payload.json", payload)

    cmd = [
        python,
        os.path.abspath(__file__),
        "run-job",
        "--job-dir", str(jd),
        "--config", str(cfg.get("config_path") or ""),
        "--kind", kind,
    ]
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["CITLENS_HOME"] = cfg["home"]
    flags = 0
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: no console, own group,
        # survives the client that started it.
        flags = 0x00000008 | 0x00000200
    try:
        with open(jd / "log.txt", "ab") as fh:
            proc = subprocess.Popen(
                cmd,
                cwd=cfg["home"],
                stdin=subprocess.DEVNULL,
                stdout=fh,
                stderr=subprocess.STDOUT,
                env=env,
                close_fds=True,
                creationflags=flags,
                start_new_session=(os.name != "nt"),
            )
    except Exception as e:  # noqa: BLE001
        state.update(state="failed", error=f"spawn failed: {e}", ended_at=_iso())
        _write_json(jd / "state.json", state)
        return {"ok": False, "state": "failed", "error": str(e), "job_id": job_id}
    state["pid"] = proc.pid
    _write_json(jd / "state.json", state)
    return {"ok": True, "state": "running", "job_id": job_id, "pid": proc.pid,
            "job_dir": str(jd), "log_path": str(jd / "log.txt")}


def wait_job(cfg: dict, job_id: str, wait_seconds: int) -> dict:
    deadline = time.time() + max(0, wait_seconds)
    while True:
        st = job_state(cfg, job_id)
        if st.get("state") in ("done", "failed", "lost") or time.time() >= deadline:
            return st
        time.sleep(1.0)


# ── artifact readers ──────────────────────────────────────────────────────────

_POOL_FIELDS = ("title", "authors", "year", "venue", "doi", "citation_count",
                "is_review", "url", "source")


def read_pool_records(path: Path) -> list[dict]:
    out = []
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(rec, dict) and rec.get("title"):
                    out.append(rec)
    except Exception:  # noqa: BLE001
        return []
    return out


def _pool_path_for(cfg: dict, *, run_dir: str | None, topic: str | None) -> tuple[Path | None, str]:
    home = Path(cfg["home"])
    if run_dir:
        cand = Path(run_dir)
        if not cand.is_absolute():
            cand = home / cand
        for p in (cand / "pool.jsonl", cand):
            if p.is_file():
                return p, str(p)
        return None, f"no pool.jsonl under {cand}"
    if not topic:
        return None, "pass run_dir or topic"
    litdb = home / "data" / "litdb" / f"{slugify(topic)}.jsonl"
    if litdb.is_file():
        return litdb, str(litdb)
    runs = home / "citlens-runs"
    if runs.is_dir():
        slug = slugify(topic)
        cands = sorted(
            (d for d in runs.iterdir() if d.is_dir() and d.name.startswith(slug)),
            key=lambda d: d.stat().st_mtime, reverse=True,
        )
        for d in cands:
            if (d / "pool.jsonl").is_file():
                return d / "pool.jsonl", str(d / "pool.jsonl")
    return None, f"no pool for topic {topic!r} (expected {litdb}); run `search` first"


def _compact_paper(rec: dict, fields=None) -> dict:
    fields = fields or _POOL_FIELDS
    out = {}
    for f in fields:
        v = rec.get(f)
        if f == "authors" and isinstance(v, list):
            v = ", ".join(v[:3]) + (" et al." if len(v) > 3 else "")
        if f == "abstract":
            v = (v or "")[:240]
        out[f] = v
    return out


# ── tool implementations ──────────────────────────────────────────────────────


def tool_doctor(cfg: dict) -> dict:
    home = Path(cfg["home"]) if cfg.get("home") else None
    py = Path(cfg["python"]) if cfg.get("python") else None
    drivers = {"recall": cfg.get("recall_driver"), "tools": cfg.get("tools_driver")}
    env_file = home / ".env" if home else None
    env_keys: list[str] = []
    if env_file and env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*=", line)
                if m:
                    env_keys.append(m.group(1))
        except Exception:  # noqa: BLE001
            pass
    # No LLM keys are required in this build — the calling agent is the model.
    # Search keys only raise quotas/breadth when absent; nothing hard-fails.
    missing: list[str] = []
    recommended = [k for k in ("SERPER_API_KEY", "SEMANTIC_SCHOLAR_API_KEY",
                               "OPENALEX_API_KEY", "OPENALEX_EMAIL",
                               "CROSSREF_EMAIL") if k not in env_keys]
    core_version = None
    screen_emb = None
    if py and py.is_file():
        try:
            r = subprocess.run(
                [str(py), "-c", "import citens,sys;print(citens.__version__ if hasattr(citens,'__version__') else '')"],
                cwd=str(_REPO_ROOT),
                capture_output=True, text=True, timeout=30,
            )
            core_version = (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else None
        except Exception:  # noqa: BLE001
            core_version = None
        # `screen`'s semantic channel runs on a LOCAL sentence-transformers
        # model (optional extra) — probe it so the agent knows which channels
        # will fire before calling screen. Never an LLM key either way.
        try:
            r2 = subprocess.run(
                [str(py), "-c", "import sentence_transformers as st;print(st.__version__)"],
                cwd=str(_REPO_ROOT),
                capture_output=True, text=True, timeout=90,
            )
            if r2.returncode == 0 and (r2.stdout or "").strip():
                screen_emb = (r2.stdout or "").strip().splitlines()[-1]
        except Exception:  # noqa: BLE001
            screen_emb = None
    recent = []
    for d in sorted(jobs_root(cfg).iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
        st = _read_json(d / "state.json")
        if st:
            recent.append({"job_id": st.get("job_id"), "kind": st.get("kind"),
                           "state": st.get("state"), "topic": st.get("topic"),
                           "started_at": st.get("started_at")})
    report = {
        "ok": bool(home and home.is_dir() and py and py.is_file()
                   and all(v and Path(v).is_file() for v in drivers.values())),
        "config_path": cfg.get("config_path"),
        "config_found": Path(cfg.get("config_path") or "").is_file(),
        "home": cfg.get("home"),
        "home_exists": bool(home and home.is_dir()),
        "python": cfg.get("python"),
        "python_exists": bool(py and py.is_file()),
        "core_version": core_version,
        "screen_embedding_runtime": screen_emb,  # None -> screen runs lexical+consensus only
        "llm_keys_required": [],
        "drivers": {k: {"path": v, "exists": bool(v and Path(v).is_file())} for k, v in drivers.items()},
        "env_file": str(env_file) if env_file else None,
        "env_keys_present": sorted(env_keys),
        "env_required_missing": missing,
        "api_keys_recommended_absent": recommended,
        "litdb_dir": str(home / "data" / "litdb") if home else None,
        "pool_count": len(list((home / "data" / "litdb").glob("*.jsonl"))) if home and (home / "data" / "litdb").is_dir() else 0,
        "jobs_dir": str(jobs_root(cfg)),
        "running_jobs": len(_running_jobs(cfg)),
        "recent_jobs": recent,
        "sources": cfg.get("sources"),
        "families": cfg.get("families"),
    }
    # A config written by an older implementation lists the engine's nine
    # family names; `search` would reject it. doctor must surface that instead
    # of reporting ok (it did once — the machine searched nothing for a day).
    fams = list(cfg.get("families") or [])
    families_invalid = [f for f in fams if f not in ALL_FAMILIES]
    report["families_invalid"] = families_invalid
    if families_invalid:
        report["ok"] = False
    notes = []
    if not report["ok"] and not families_invalid:
        notes.append("Not ready: fix the missing paths above in the config file.")
    if families_invalid:
        notes.append(
            "config families contains entries this build does not implement: "
            + ", ".join(families_invalid)
            + " — `search` will reject the config. Run `install.py apply` to migrate "
              "the config (or edit ~/.citlens/config.json to the seven families)."
        )
    if screen_emb is None:
        notes.append(
            "screen semantic channel absent: pip install \"citlens-agent[embedding]\" "
            "to add local embeddings (no key needed) — screen still works on its "
            "lexical + consensus channels either way"
        )
    if recommended:
        notes.append(
            "optional breadth keys absent: " + ", ".join(recommended)
            + " (web-bridge / S2 recommendations / OpenAlex polite pool stay degraded "
              "but the other families still run; NO key is required)")
    report["notes"] = notes
    return report


def _run_driver_json(cfg: dict, kind: str, argv: list[str], timeout: int = 240) -> dict:
    """Synchronous, short driver call whose only stdout is one JSON document."""
    python = cfg.get("python")
    driver = cfg.get("recall_driver") if kind == "search" else cfg.get("tools_driver")
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        r = subprocess.run(
            [python, driver, *argv],
            cwd=cfg["home"], capture_output=True, text=True, timeout=timeout, env=env,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"driver timed out after {timeout}s"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"driver launch failed: {e}"}
    raw = (r.stdout or "").strip()
    start = raw.find("{")
    if start < 0:
        return {"ok": False, "error": "driver produced no JSON",
                "exit_code": r.returncode, "stderr_tail": (r.stderr or "")[-800:]}
    try:
        data = json.loads(raw[start:])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"driver JSON unparsable: {e}",
                "stdout_head": raw[:800], "stderr_tail": (r.stderr or "")[-800:]}
    data["ok"] = r.returncode == 0
    if r.returncode != 0:
        data.setdefault("error", f"driver exit {r.returncode}")
        data["stderr_tail"] = (r.stderr or "")[-800:]
    return data


def tool_search(cfg: dict, args: dict) -> dict:
    topic = (args.get("topic") or "").strip()
    if not topic:
        return {"ok": False, "error": "topic is required"}
    families = _as_list(args.get("families")) or list(cfg.get("families") or ALL_FAMILIES)
    bad = [f for f in families if f not in ALL_FAMILIES]
    if bad:
        return {"ok": False, "error": f"unknown families {bad}", "allowed": ALL_FAMILIES}
    payload = {
        "topic": topic,
        "target": int(args.get("target") or cfg.get("target") or 0),
        "append_pool": bool(args.get("append_pool", True)),
        "families": families,
        "queries": _as_list(args.get("queries")),
        "title_probes": _as_list(args.get("title_probes")),
        "web_queries": _as_list(args.get("web_queries")),
    }
    if args.get("sources"):
        payload["sources"] = _as_list(args.get("sources"))
    started = start_job(cfg, "search", payload)
    if not started.get("ok"):
        return started
    wait_s = _clamp(args.get("wait_seconds", cfg.get("wait_seconds")), 0, 300, 45)
    st = wait_job(cfg, started["job_id"], wait_s)
    out = _search_view(cfg, st)
    if not payload["queries"]:
        out["hint"] = (
            "No `queries` were passed — the agent family ran empty and only the raw "
            "topic + expansion families fired. YOU are the planner: craft English "
            "concept-block queries (see the skill) and search again with them. "
            + str(out.get("hint") or "")
        )
    return out


def tool_fetch(cfg: dict, args: dict) -> dict:
    """Grounding substrate: open-access full text, or abstract fallback."""
    if not any((args.get("doi"), args.get("title"), args.get("arxiv"))):
        return {"ok": False, "error": "pass doi, title or arxiv "
                "(plus topic/run_dir to resolve the record from a pool)"}
    argv = ["fetch"]
    for flag, key in (("--doi", "doi"), ("--title", "title"), ("--arxiv", "arxiv"),
                      ("--topic", "topic"), ("--run-dir", "run_dir")):
        if args.get(key):
            argv += [flag, str(args[key])]
    out = _run_driver_json(cfg, "tools", argv, timeout=300)
    out.setdefault("note", "")
    out["note"] = (
        "Use the text (text_path / head) as the ONLY grounding for claims about "
        "this paper. fulltext=false means abstract-only: claims must stay within "
        "what the abstract states, and the review's honesty block must count it. "
        + str(out.get("note") or "")
    )
    return out


def tool_export(cfg: dict, args: dict) -> dict:
    argv = ["export", "--format", (args.get("format") or "bib").lower()]
    if args.get("topic"):
        argv += ["--topic", str(args["topic"])]
    if args.get("run_dir"):
        argv += ["--run-dir", str(args["run_dir"])]
    if args.get("out"):
        argv += ["--out", str(args["out"])]
    if args.get("with_labels"):
        argv += ["--with-labels"]
    return _run_driver_json(cfg, "tools", argv, timeout=120)


def tool_audit(cfg: dict, args: dict) -> dict:
    topic = (args.get("topic") or "").strip()
    if not topic:
        return {"ok": False, "error": "topic is required (byte-identical to the search)"}
    argv = ["audit", "--topic", topic]
    if args.get("top_reviews"):
        argv += ["--top-reviews", str(int(args["top_reviews"]))]
    return _run_driver_json(cfg, "tools", argv, timeout=240)


def _search_view(cfg: dict, st: dict) -> dict:
    """Uniform answer whether the job is still running or finished."""
    out = {
        "job_id": st.get("job_id"),
        "state": st.get("state"),
        "topic": st.get("topic"),
        "elapsed_s": None,
    }
    if st.get("started_ts"):
        out["elapsed_s"] = round(time.time() - float(st["started_ts"]))
    if st.get("state") == "running":
        out["hint"] = (
            f"still running ({out['elapsed_s']}s). Call `status` with this job_id; "
            "a full nine-family search on a rich topic typically takes 2-6 minutes."
        )
        out["log_tail"] = _tail_text(Path(st["log_path"]), 8)
        return out
    run_dir = st.get("run_dir") or _find_run_dir(cfg, "search", float(st.get("started_ts") or 0))
    out.update(exit_code=st.get("exit_code"), error=st.get("error"),
               run_dir=run_dir, job_dir=st.get("job_dir"))
    if st.get("state") == "failed":
        out["log_tail"] = _tail_text(Path(st["log_path"]), 20)
        out["hint"] = "the recall leg failed; fix the reason in log_tail, then retry."
        return out
    if run_dir:
        rd = Path(run_dir)
        pool = read_pool_records(rd / "pool.jsonl")
        out["artifacts"] = {
            "pool_jsonl": str(rd / "pool.jsonl"),
            "search_report": str(rd / "search_report.md"),
            "exclusions": str(rd / "exclusions.jsonl"),
        }
        out["kept"] = len(pool)
        # query-level feedback (see queries.json writer in the recall driver):
        # which concept blocks the sources actually answered. Weak blocks are
        # the agent's rephrase list — vocabulary mismatch, not pool size.
        qj = _read_json(rd / "queries.json").get("query_feedback") or []
        if qj:
            out["query_feedback"] = [
                {"query": q.get("query", "")[:60], "total": q.get("total", 0),
                 "verdict": q.get("verdict", "?")}
                for q in qj
            ]
            weak = [q for q in qj if q.get("verdict") in ("empty", "thin")]
            if weak:
                out["weak_queries"] = [q.get("query", "")[:60] for q in weak]
        by_source: dict[str, int] = {}
        no_doi = no_venue = reviews = 0
        for rec in pool:
            by_source[rec.get("source") or "?"] = by_source.get(rec.get("source") or "?", 0) + 1
            no_doi += 0 if rec.get("doi") else 1
            no_venue += 0 if rec.get("venue") else 1
            reviews += 1 if rec.get("is_review") else 0
        out["pool_stats"] = {
            "kept": len(pool), "reviews": reviews, "missing_doi": no_doi,
            "missing_venue": no_venue, "by_source": by_source,
        }
        top = sorted(pool, key=lambda r: (r.get("citation_count") or 0), reverse=True)[:12]
        out["top_by_citations"] = [_compact_paper(r, ("title", "year", "venue",
                                                      "citation_count", "doi")) for r in top]
        report = rd / "search_report.md"
        if report.is_file():
            head = report.read_text(encoding="utf-8", errors="replace").splitlines()
            out["report_head"] = "\n".join(head[:24])
        out["hint"] = (
            "Order is RRF/family-seat order, NOT a relevance judgment — run "
            "`screen` with your concept-block queries first to band the pool "
            "(core/uncertain/likely_off triage), then read the core+uncertain "
            "records yourself (title+abstract, paper by paper) before citing. "
            "If query_feedback shows empty/thin blocks, REPHRASE those concept "
            "blocks in paper-side vocabulary (method/dataset/task names) and "
            "search again — weak blocks are vocabulary mismatch, not a small "
            "pool. After judging records core, feed them back with `expand` "
            "(citation-chain + similarity neighbors of YOUR seeds). "
            "Read `search_report.md` for per-family seat counts and per-source "
            "ok/empty/failed health, and `exclusions.jsonl` for the PRISMA reasons. "
            "Report failed sources explicitly; never present them as zero hits. "
            "Then use `pool` for filtering, `fetch` for grounding, `audit` before "
            "claiming coverage, and `export` for the bibliography."
        )
    return out


def tool_screen(cfg: dict, args: dict) -> dict:
    topic = (args.get("topic") or "").strip()
    run_dir = (args.get("run_dir") or "").strip()
    if not topic and not run_dir:
        return {"ok": False, "error": "pass topic or run_dir"}
    argv = ["screen"]
    if topic:
        argv += ["--topic", topic]
    if run_dir:
        argv += ["--run-dir", run_dir]
    queries = _as_list(args.get("queries"))
    if queries:
        argv += ["--queries", *queries]
    if args.get("model") is not None:
        argv += ["--model", str(args["model"])]
    for flag, key in (("--core", "core_threshold"), ("--off", "off_threshold"),
                      ("--limit", "limit")):
        if args.get(key) is not None:
            argv += [flag, str(args[key])]
    # first call may download the local model; give it room
    return _run_driver_json(cfg, "tools", argv, timeout=900)


def tool_expand(cfg: dict, args: dict) -> dict:
    """Judgment feedback loop: expand the topic pool around agent-judged seeds."""
    topic = (args.get("topic") or "").strip()
    if not topic:
        return {"ok": False, "error": "topic is required (the pool to expand into)"}
    seeds = _as_list(args.get("seeds"))
    from_notes = (args.get("from_notes") or "").strip()
    if not seeds and not from_notes:
        return {"ok": False, "error": "pass seeds (DOIs / arXiv ids / titles of papers "
                "you judged on-topic) or from_notes=core (expand around your "
                "judged-core reading notes)"}
    argv = ["expand", "--topic", topic]
    if seeds:
        argv += ["--seeds", *seeds]
    if from_notes:
        argv += ["--from-notes", from_notes]
    if args.get("directions"):
        argv += ["--directions", ",".join(_as_list(args.get("directions")))]
    for flag, key in (("--top", "top"), ("--limit-per-paper", "limit_per_paper")):
        if args.get(key) is not None:
            argv += [flag, str(args[key])]
    if args.get("no_write"):
        argv += ["--no-write"]
    out = _run_driver_json(cfg, "tools", argv, timeout=600)
    out.setdefault("note", "")
    out["note"] = (
        "These are citation-chain / similarity neighbors of YOUR seeds — found_by="
        "[expand], still unjudged: band with `screen` and read them yourself before "
        "citing. If the expansion missed the neighborhood you expected, check "
        "`unresolved` seeds and try more/different seeds — seeds ARE the query here. "
        + str(out.get("note") or "")
    )
    return out


def tool_notes(cfg: dict, args: dict) -> dict:
    """Reading notes: record per-paper verdicts, or list them back."""
    topic = (args.get("topic") or "").strip()
    if not topic:
        return {"ok": False, "error": "topic is required"}
    argv = ["notes", "--topic", topic]
    if args.get("doi"):
        argv += ["--doi", str(args["doi"])]
    if args.get("title"):
        argv += ["--title", str(args["title"])]
    if args.get("verdict"):
        argv += ["--verdict", str(args["verdict"])]
    if args.get("note"):
        argv += ["--note", str(args["note"])]
    if args.get("limit") is not None:
        argv += ["--limit", str(args["limit"])]
    return _run_driver_json(cfg, "tools", argv, timeout=120)


def tool_dedup(cfg: dict, args: dict) -> dict:
    """Duplicate report over a pool (report-only unless merge=true)."""
    if not (args.get("topic") or args.get("run_dir")):
        return {"ok": False, "error": "pass topic or run_dir"}
    argv = ["dedup"]
    if args.get("topic"):
        argv += ["--topic", str(args["topic"])]
    if args.get("run_dir"):
        argv += ["--run-dir", str(args["run_dir"])]
    if args.get("merge"):
        argv += ["--merge"]
    if args.get("limit") is not None:
        argv += ["--limit", str(args["limit"])]
    return _run_driver_json(cfg, "tools", argv, timeout=240)


def tool_verify(cfg: dict, args: dict) -> dict:
    """Mechanical verification of a written review (no LLM, no key)."""
    review = str(args.get("review") or "").strip()
    if not review:
        return {"ok": False, "error": "review is required (path to the review markdown)"}
    argv = ["verify", "--review", review]
    for flag, key in (("--topic", "topic"), ("--run_dir", "run_dir"),
                      ("--verdicts", "verdicts"), ("--text_dir", "text_dir"),
                      ("--out", "out_dir"), ("--out", "out")):
        if args.get(key):
            argv += [flag, str(args[key])]
    if args.get("core_papers") not in (None, ""):
        argv += ["--core-papers", str(args["core_papers"])]
    out = _run_driver_json(cfg, "tools", argv, timeout=600)
    out.setdefault("note", "")
    out["note"] = (
        "clean=false must be fixed before delivery: a reference that does not "
        "resolve to the pool is a fabricated/untraceable citation; a span that "
        "does not occur verbatim in the cited source is a guess, not evidence. "
        "Report `honesty` verbatim — it is computed, not estimated. "
        + str(out.get("note") or "")
    )
    return out


def tool_status(cfg: dict, args: dict) -> dict:
    job_id = (args.get("job_id") or "").strip()
    if not job_id:
        return {"ok": False, "error": "job_id is required"}
    st = job_state(cfg, job_id)
    if st.get("state") == "unknown":
        return st
    view = _search_view(cfg, st)
    view["log_tail"] = _tail_text(Path(st["log_path"]), _clamp(args.get("log_lines", 15), 0, 200, 15))
    return view


def tool_pool(cfg: dict, args: dict) -> dict:
    path, where = _pool_path_for(cfg, run_dir=args.get("run_dir"), topic=args.get("topic"))
    if not path:
        return {"ok": False, "error": where}
    records = read_pool_records(path)
    total = len(records)

    def _year(rec):
        y = rec.get("year")
        return y if isinstance(y, int) else 0

    yf, yt = args.get("year_from"), args.get("year_to")
    min_c = args.get("min_citations")
    want_doi = args.get("has_doi")
    want_review = args.get("is_review")
    kw = (args.get("query") or "").strip().lower()

    def keep(rec: dict) -> bool:
        if yf is not None and _year(rec) < int(yf):
            return False
        if yt is not None and _year(rec) > int(yt):
            return False
        if min_c is not None and (rec.get("citation_count") or 0) < int(min_c):
            return False
        if want_doi is True and not rec.get("doi"):
            return False
        if want_doi is False and rec.get("doi"):
            return False
        if want_review is True and not rec.get("is_review"):
            return False
        if want_review is False and rec.get("is_review"):
            return False
        if kw:
            hay = " ".join(str(rec.get(k) or "") for k in
                           ("title", "abstract", "venue", "doi", "keywords")).lower()
            if kw not in hay:
                return False
        return True

    matched = [r for r in records if keep(r)]
    sort_by = (args.get("sort_by") or "citations").lower()
    if sort_by == "year":
        matched.sort(key=lambda r: (_year(r), r.get("citation_count") or 0), reverse=True)
    elif sort_by == "citations":
        matched.sort(key=lambda r: (r.get("citation_count") or 0), reverse=True)
    limit = _clamp(args.get("limit", 30), 1, 200, 30)
    shown = matched[:limit]
    fields = _as_list(args.get("fields")) or list(_POOL_FIELDS)
    fields = [f for f in fields if f in set(_POOL_FIELDS) | {"abstract", "keywords",
                                                             "first_author_h_index",
                                                             "author_field_works", "pdf_url"}]
    by_year: dict[str, int] = {}
    for r in matched:
        y = str(_year(r) or "?")
        by_year[y] = by_year.get(y, 0) + 1
    by_source: dict[str, int] = {}
    for r in matched:
        s = r.get("source") or "?"
        by_source[s] = by_source.get(s, 0) + 1
    return {
        "ok": True,
        "pool_path": str(path),
        "total": total,
        "matched": len(matched),
        "shown": len(shown),
        "stats": {
            "missing_doi": sum(0 if r.get("doi") else 1 for r in matched),
            "missing_venue": sum(0 if r.get("venue") else 1 for r in matched),
            "reviews": sum(1 for r in matched if r.get("is_review")),
            "with_fulltext_hint": sum(1 for r in matched if r.get("pdf_url")),
            "by_source": by_source,
            "by_year": dict(sorted(by_year.items())),
        },
        "papers": [_compact_paper(r, fields) for r in shown],
        "note": (
            "This reads the pool on disk — no retrieval happened. If the numbers are "
            "thin for your purpose, run `search` with more families/target rather than "
            "claiming coverage from this subset."
        ),
    }


# ── MCP protocol ──────────────────────────────────────────────────────────────

TOOL_DEFS = [
    {
        "name": "search",
        "description": (
            "Find literature with CiteLens — and YOU are the query planner. Craft the "
            "English concept-block queries yourself (4-6 concepts x 2-4 synonyms, "
            "combination queries first; see the skill's PRESS discipline) and pass "
            "them as `queries`. The tool runs seven recall families (your queries, "
            "raw topic, OpenAlex title match over `title_probes`, Semantic-Scholar "
            "recommendations, citation snowball, web bridge over `web_queries`, "
            "survey reference harvest) fused by reciprocal-rank fusion under "
            "per-family seat quotas. It does NOT rank by relevance — judge the "
            "returned pool yourself. Writes pool.jsonl + search_report.md + "
            "exclusions.jsonl + queries.json (per-query hit feedback — rephrase "
            "empty/thin blocks in paper-side vocabulary). Returns a job id; pass "
            "wait_seconds (default 45) or poll `status`. Use this instead of "
            "your own web search for any literature question."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Research topic; Chinese or English. Pools are keyed by a slug of this string — reuse it byte-identically."},
                "queries": {"type": "array", "items": {"type": "string"},
                            "description": "English queries you crafted (PRESS concept blocks). This replaces the engine's LLM planner."},
                "title_probes": {"type": "array", "items": {"type": "string"},
                                 "description": "HyDE-style hypothetical TITLES of the ideal paper (paper-side vocabulary, 2-3 of them) or anchor titles, for the OpenAlex title-search family (max 3 used)."},
                "web_queries": {"type": "array", "items": {"type": "string"},
                                "description": "Web-bridge queries: English verbatim spans of the distinctive wording + natural Chinese phrasings (Zhihu-style)."},
                "target": {"type": "integer", "description": "Max kept papers (0 = no truncation). Default from config."},
                "families": {"type": "array", "items": {"type": "string", "enum": ALL_FAMILIES},
                             "description": "Subset of the seven families to run (default: all)."},
                "sources": {"type": "array", "items": {"type": "string"},
                            "description": "Metadata sources, e.g. arxiv, semantic_scholar, openalex, crossref."},
                "append_pool": {"type": "boolean", "description": "Merge results into the shared per-topic pool (default true)."},
                "wait_seconds": {"type": "integer", "description": "Block up to this long before returning with a job id (0-300)."},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "pool",
        "description": (
            "Read and filter the literature pool already on disk for a topic or a run "
            "directory — no new retrieval. Returns totals, source/year stats and "
            "compact records. Use it to iterate (citations, years, reviews, DOIs) "
            "instead of re-searching."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic whose shared pool to read."},
                "run_dir": {"type": "string", "description": "A specific run directory (from search/status)."},
                "query": {"type": "string", "description": "Substring match over title/abstract/venue/doi/keywords."},
                "min_citations": {"type": "integer"},
                "year_from": {"type": "integer"},
                "year_to": {"type": "integer"},
                "has_doi": {"type": "boolean"},
                "is_review": {"type": "boolean", "description": "true = only surveys/reviews."},
                "sort_by": {"type": "string", "enum": ["citations", "year", "none"]},
                "limit": {"type": "integer", "description": "Records to return (default 30)."},
                "fields": {"type": "array", "items": {"type": "string"},
                           "description": "Subset of title,authors,year,venue,doi,citation_count,is_review,url,source,abstract,keywords,pdf_url."},
            },
        },
    },
    {
        "name": "fetch",
        "description": (
            "Grounding substrate: fetch one paper's open-access full text (arXiv -> "
            "S2 -> OpenAlex -> Unpaywall -> CORE, PDF converted to text, cached) or "
            "fall back to the abstract. Use it BEFORE citing claims about a paper's "
            "methods/results; fulltext=false means the paper can only be cited "
            "abstract-only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "doi": {"type": "string"},
                "title": {"type": "string"},
                "arxiv": {"type": "string", "description": "arXiv id, e.g. 2401.12345"},
                "topic": {"type": "string", "description": "Resolve the record from this topic's pool first."},
                "run_dir": {"type": "string", "description": "Resolve the record from this run's pool.jsonl."},
            },
            "description": "Pass doi / title / arxiv (one is enough; with topic or run_dir the record is resolved from the pool).",
        },
    },
    {
        "name": "export",
        "description": (
            "Export a literature pool (topic or run directory) as BibTeX or RIS, via "
            "the same citation table the engine used. Missing fields are left empty, "
            "never invented."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "run_dir": {"type": "string"},
                "format": {"type": "string", "enum": ["bib", "ris", "endnote", "csljson"], "description": "Default bib."},
                "out": {"type": "string", "description": "Output path (default: run dir or exports/references.<fmt>)."},
                "with_labels": {"type": "boolean", "description": "Include the numbered [n] APA label list."},
            },
        },
    },
    {
        "name": "audit",
        "description": (
            "Coverage audit (stage F anchor check): how much of the top surveys' "
            "bibliographies the topic's pool already covers. Run this BEFORE "
            "declaring a field covered; low coverage or reviews_checked=0 means keep "
            "searching, not conclude."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Byte-identical to the search topic."},
                "top_reviews": {"type": "integer", "description": "Top reviews to audit against (default 3)."},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "screen",
        "description": (
            "Relevance TRIAGE over a pool: score every record against YOUR "
            "concept-block queries on explainable channels (local embedding "
            "similarity — optional extra, no LLM key; BM25 lexical; "
            "cross-family consensus from found_by) and band it "
            "core / uncertain / likely_off. Writes screening.jsonl. This is "
            "triage, NOT judgment: nothing is excluded automatically — read "
            "core+uncertain carefully, batch-review likely_off, and log every "
            "final exclusion in exclusions.jsonl (PRISMA). The first call "
            "with the semantic channel may download a local model (~0.4 GB); "
            "without the extra installed it degrades to lexical+consensus "
            "and says so."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic pool to screen (byte-identical topic slug)."},
                "run_dir": {"type": "string", "description": "A specific run directory to screen instead."},
                "queries": {"type": "array", "items": {"type": "string"},
                            "description": "Your English concept-block queries — same ones you gave `search`."},
                "model": {"type": "string",
                          "description": "Local sentence-transformers model override (empty string disables the semantic channel)."},
                "core_threshold": {"type": "number", "description": "core band cutoff (default 0.5)."},
                "off_threshold": {"type": "number", "description": "likely_off band cutoff (default 0.32)."},
                "limit": {"type": "integer", "description": "Records to return (default 30)."},
            },
            "required": [],
        },
    },
    {
        "name": "verify",
        "description": (
            "MECHANICAL verification of a written review — no LLM, no key. Checks "
            "citation truth (every [n] marker resolves to a reference and every "
            "reference to the literature pool: the honeypot), then checks each "
            "agent verdict's quoted `span` verbatim against the cited paper's "
            "fetched full text (abstract floor otherwise). With a verdicts JSONL "
            "it computes the honesty block: citation precision, unverifiable rate, "
            "full-text grounding, papers_cited/pool_size. Use it before delivering "
            "any review; `clean=false` means fix, do not ship."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "review": {"type": "string", "description": "Path to the review markdown (body with [n] markers + a References section)."},
                "topic": {"type": "string", "description": "Topic pool to resolve references against (byte-identical to the search topic)."},
                "run_dir": {"type": "string", "description": "Run directory whose pool.jsonl to resolve against."},
                "verdicts": {"type": "string", "description": "Path to a verdicts JSONL: one {claim, verdict, span, citations} per line."},
                "text_dir": {"type": "string", "description": "Fetched full-text directory (default fulltext under the data home)."},
                "out_dir": {"type": "string", "description": "Artifacts directory (default <review dir>/verification)."},
                "core_papers": {"type": "integer", "description": "Papers deep-read (grounding denominator; default: distinct cited pool papers)."},
            },
            "required": ["review"],
        },
    },
    {
        "name": "expand",
        "description": (
            "Judgment feedback loop for recall: expand the topic pool around papers "
            "YOU judged on-topic (citation chaining backward/forward + OpenAlex "
            "related + Semantic-Scholar recommendations). This is the vocabulary-"
            "mismatch escape hatch — the full-set bench measured that 71% of missed "
            "gold papers share <=2 words with the question, and citation/similarity "
            "neighbors bypass query vocabulary entirely. Seeds may be DOIs, arXiv "
            "ids or titles. Added records carry found_by=[expand]: still unjudged — "
            "screen and read them yourself (PRISMA exclusions still apply)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Pool to expand into (byte-identical topic slug; may be a fresh topic seeded entirely from these)."},
                "seeds": {"type": "array", "items": {"type": "string"},
                          "description": "Papers you judged on-topic: DOIs / arXiv ids / titles (max 6 used)."},
                "from_notes": {"type": "string", "enum": ["core", "uncertain", "off"],
                               "description": "Also seed from the topic's reading notes with this verdict (core = expand around everything you judged core)."},
                "directions": {"type": "array", "items": {"type": "string", "enum": ["backward", "forward", "related", "recs"]},
                               "description": "Expansion directions (default all four)."},
                "top": {"type": "integer", "description": "Records to return/merge (default 30)."},
                "limit_per_paper": {"type": "integer", "description": "Per seed per direction (default 20)."},
                "no_write": {"type": "boolean", "description": "Return without merging into the pool."},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "notes",
        "description": (
            "Reading notes — your per-paper judgment memory. While judging the "
            "pool, record each paper's verdict (core / uncertain / off) plus a "
            "one-line reason; notes persist per topic in data/notes/. They feed "
            "the recall loop: `expand` with from_notes=core seeds the citation "
            "expansion around everything you judged core. Call without doi/title "
            "to list the notes so far."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic slug (byte-identical)."},
                "doi": {"type": "string", "description": "Adding a note: the paper's DOI."},
                "title": {"type": "string", "description": "Adding a note: the paper's title (if no DOI)."},
                "verdict": {"type": "string", "enum": ["core", "uncertain", "off"]},
                "note": {"type": "string", "description": "Your one-line judgment (required when doi/title given)."},
                "limit": {"type": "integer", "description": "List mode: max notes returned."},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "dedup",
        "description": (
            "Duplicate report over a pool: groups suspected duplicates by three "
            "signals (exact DOI, arXiv id, fuzzy title + shared author — the "
            "arXiv preprint and its published version are the classic case). "
            "Report-only by default; merge=true collapses each group into its "
            "DOI-carrying survivor (topic pools only, .bak written first; "
            "pdf_url/abstract/found_by carry over)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "run_dir": {"type": "string"},
                "merge": {"type": "boolean", "description": "Collapse the groups (topic pools only; writes .bak)."},
                "limit": {"type": "integer", "description": "Max groups returned (default 20)."},
            },
        },
    },
    {
        "name": "status",
        "description": "Poll a running search job by id: state, elapsed, log tail, artifacts and stats.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "log_lines": {"type": "integer", "description": "Log lines to include (default 15)."},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "doctor",
        "description": (
            "Health check: interpreter, drivers, data home, .env keys present "
            "(names only, never values — and NO key is required in this build), "
            "shared pool count, running/recent jobs, unsupported config families "
            "(families_invalid). Call it first when a tool fails, and before "
            "blaming the retrieval."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def handle_tool(cfg: dict, name: str, args: dict) -> dict:
    if name == "doctor":
        return tool_doctor(cfg)
    if name == "search":
        return tool_search(cfg, args)
    if name == "status":
        return tool_status(cfg, args)
    if name == "pool":
        return tool_pool(cfg, args)
    if name == "fetch":
        return tool_fetch(cfg, args)
    if name == "export":
        return tool_export(cfg, args)
    if name == "audit":
        return tool_audit(cfg, args)
    if name == "screen":
        return tool_screen(cfg, args)
    if name == "verify":
        return tool_verify(cfg, args)
    if name == "expand":
        return tool_expand(cfg, args)
    if name == "notes":
        return tool_notes(cfg, args)
    if name == "dedup":
        return tool_dedup(cfg, args)
    return {"ok": False, "error": f"unknown tool {name!r}", "tools": [t["name"] for t in TOOL_DEFS]}


def _result(payload: dict, is_error: bool = False) -> dict:
    text = json.dumps(payload, ensure_ascii=False, indent=1, default=str)
    return {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}


class Server:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._initialized = False

    # -- transport ---------------------------------------------------------
    def log(self, msg: str) -> None:
        _log(msg)

    def send(self, msg: dict) -> None:
        data = json.dumps(msg, ensure_ascii=False).encode("utf-8", "replace")
        out = sys.stdout.buffer
        out.write(data + b"\n")
        out.flush()

    def reply(self, msg_id, result: dict) -> None:
        self.send({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def error(self, msg_id, code: int, message: str) -> None:
        if msg_id is None:
            return
        self.send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})

    # -- dispatch ----------------------------------------------------------
    def dispatch(self, msg: dict) -> None:
        msg_id = msg.get("id")
        method = msg.get("method") or ""
        params = msg.get("params") or {}
        if msg_id is None and method.startswith("notifications/"):
            return  # notifications never get a response
        try:
            if method == "initialize":
                asked = params.get("protocolVersion") or ""
                version = asked if asked in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
                self._initialized = True
                self.reply(msg_id, {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "instructions": INSTRUCTIONS,
                })
            elif method == "ping":
                self.reply(msg_id, {})
            elif method == "tools/list":
                self.reply(msg_id, {"tools": TOOL_DEFS})
            elif method == "tools/call":
                name = params.get("name") or ""
                args = params.get("arguments") or {}
                try:
                    payload = handle_tool(self.cfg, name, args)
                except Exception as e:  # noqa: BLE001 — a tool bug must not kill the session
                    self.log(f"tool {name} raised: {e}")
                    payload = {"ok": False, "error": f"tool raised: {type(e).__name__}: {e}"}
                ok = payload.get("ok", True) is not False and payload.get("state") not in ("failed", "rejected", "refused")
                self.reply(msg_id, _result(payload, is_error=not ok))
            elif method in ("resources/list",):
                self.reply(msg_id, {"resources": []})
            elif method in ("resources/templates/list",):
                self.reply(msg_id, {"resourceTemplates": []})
            elif method in ("prompts/list",):
                self.reply(msg_id, {"prompts": []})
            elif method in ("shutdown", "exit"):
                self.reply(msg_id, {})
                raise SystemExit(0)
            else:
                self.error(msg_id, -32601, f"method not found: {method}")
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            self.log(f"dispatch failed for {method}: {e}")
            self.error(msg_id, -32603, f"internal error: {e}")

    def serve(self) -> int:
        self.log(f"ready · server={SERVER_NAME} v{SERVER_VERSION} · config={self.cfg.get('config_path')}"
                 f" · home={self.cfg.get('home')}")
        stdin = sys.stdin.buffer
        while True:
            try:
                raw = stdin.readline()
            except Exception:  # noqa: BLE001
                break
            if not raw:
                break
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8", "replace"))
            except Exception as e:  # noqa: BLE001
                self.send({"jsonrpc": "2.0", "id": None,
                           "error": {"code": -32700, "message": f"parse error: {e}"}})
                continue
            if isinstance(msg, list):  # JSON-RPC batch
                for item in msg:
                    if isinstance(item, dict):
                        self.dispatch(item)
            elif isinstance(msg, dict):
                self.dispatch(msg)
        return 0


# ── detached job runner ───────────────────────────────────────────────────────


def _driver_argv(cfg: dict, kind: str, payload: dict) -> list[str]:
    if kind == "search":
        argv = ["--topic", payload["topic"]]
        target = payload.get("target") or 0
        if target:
            argv += ["--target", str(target)]
        fams = payload.get("families") or []
        if fams and set(fams) != set(ALL_FAMILIES):
            argv += ["--families", ",".join(fams)]
        if payload.get("sources"):
            argv += ["--sources", ",".join(payload["sources"])]
        if payload.get("queries"):
            argv += ["--queries", *payload["queries"]]
        if payload.get("title_probes"):
            argv += ["--title-probes", *payload["title_probes"]]
        if payload.get("web_queries"):
            argv += ["--web-queries", *payload["web_queries"]]
        if payload.get("append_pool"):
            argv += ["--append-pool"]
        return argv
    return list(payload.get("argv") or [])


def run_job(job_dir: str, config: str, kind: str) -> int:
    """Detached entry point: run one driver, keep the state file truthful."""
    cfg = load_config(config or None)
    jd = Path(job_dir)
    payload = _read_json(jd / "payload.json")
    state = _read_json(jd / "state.json")
    state.update(state="running", pid=os.getpid(), runner_started=_iso())
    _write_json(jd / "state.json", state)
    log_path = jd / "log.txt"

    def emit(line: str) -> None:
        try:
            with open(log_path, "a", encoding="utf-8", errors="replace") as fh:
                fh.write(line + "\n")
        except Exception:  # noqa: BLE001
            pass

    emit(f"== citlens job {state.get('job_id')} kind={kind} runner_pid={os.getpid()} ==")
    emit(f"home={cfg.get('home')}")
    python = cfg.get("python")
    driver = cfg.get("recall_driver") if kind == "search" else cfg.get("tools_driver")
    argv = _driver_argv(cfg, kind, payload)
    cmd = [python, driver, *argv]
    emit("cmd: " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd))
    started = time.time()
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["CITLENS_HOME"] = cfg.get("home") or ""
    code = -1
    try:
        with open(log_path, "a", encoding="utf-8", errors="replace") as fh:
            proc = subprocess.run(
                cmd, cwd=cfg.get("home") or None, stdin=subprocess.DEVNULL,
                stdout=fh, stderr=subprocess.STDOUT, env=env,
            )
        code = proc.returncode
    except Exception as e:  # noqa: BLE001
        emit(f"runner failed to launch driver: {e}")
        code = -2
    elapsed = time.time() - started
    run_dir = _find_run_dir(cfg, kind, started)
    state.update(
        state="done" if code == 0 else "failed",
        exit_code=code,
        ended_at=_iso(),
        elapsed_s=round(elapsed, 1),
        runner_pid=os.getpid(),
    )
    if run_dir:
        state["run_dir"] = run_dir
    if code != 0:
        state["error"] = f"driver exited {code}; see log"
    _write_json(jd / "state.json", state)
    emit(f"== {'done' if code == 0 else 'FAILED'} code={code} elapsed={elapsed:.0f}s run_dir={run_dir} ==")
    return 0


# ── selftest / CLI ────────────────────────────────────────────────────────────


def selftest(cfg: dict) -> int:
    """Offline checks: config resolution, tool list, doctor, pool reader."""
    problems = []
    path = config_path(None)
    print(f"config: {path} ({'found' if path.is_file() else 'MISSING — using defaults'})")
    print(f"home:   {cfg.get('home')}")
    print(f"python: {cfg.get('python')}")
    for key in ("home", "python", "recall_driver", "tools_driver"):
        p = cfg.get(key)
        if not p or not Path(p).exists():
            problems.append(f"{key} does not exist: {p}")
    if problems and not Path(cfg["python"]).is_file():
        problems.append("repo interpreter missing — create .venv and re-run install.py apply")
    print(f"tools:  {', '.join(t['name'] for t in TOOL_DEFS)}")
    doc = tool_doctor(cfg)
    print(f"doctor: ok={doc['ok']} core={doc.get('core_version')} "
          f"pools={doc.get('pool_count')} running={doc.get('running_jobs')}")
    for n in doc.get("notes") or []:
        print(f"  note: {n}")
    for k, v in (doc.get("drivers") or {}).items():
        if not v.get("exists"):
            problems.append(f"{k} driver missing: {v.get('path')}")
    print("protocol: tools/list + tools/call(doctor) exercised by tests/test_portable.py")
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(f" - {p}")
        return 1
    print("\nselftest OK")
    return 0


_LIST_KEYS = ("families", "sources", "fields", "themes",
              "queries", "title_probes", "web_queries", "seeds", "directions")


def _parse_cli_args(rest: list[str]) -> tuple[str, dict]:
    """`cli search --topic X --target 80 --is_review true` -> (tool, args)."""
    if not rest:
        return "", {}
    name, rest = rest[0], rest[1:]
    args: dict = {}
    i = 0
    while i < len(rest):
        tok = rest[i]
        if not tok.startswith("--"):
            i += 1
            continue
        key = tok[2:].replace("-", "_")
        # list-valued keys take ALL consecutive non-flag tokens ("--queries a b c"),
        # not just the first — the drivers' argparse semantics, which the MCP
        # path gets natively from JSON arrays
        if key in _LIST_KEYS:
            vals: list[str] = []
            j = i + 1
            while j < len(rest) and not rest[j].startswith("--"):
                vals.append(rest[j])
                j += 1
            args[key] = vals
            i = j
            continue
        nxt = rest[i + 1] if i + 1 < len(rest) else None
        if nxt is None or nxt.startswith("--"):
            args[key] = True
            i += 1
            continue
        low = nxt.lower()
        if low in ("true", "false"):
            args[key] = low == "true"
        elif re.fullmatch(r"-?\d+", nxt):
            args[key] = int(nxt)
        else:
            args[key] = nxt
        i += 2
    return name, args


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "serve"
    rest = argv[1:]
    config = None
    for i, a in enumerate(rest):
        if a == "--config" and i + 1 < len(rest):
            config = rest[i + 1]
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    if cmd == "serve":
        return Server(load_config(config)).serve()
    if cmd == "tools":
        print(json.dumps(TOOL_DEFS, ensure_ascii=False, indent=1))
        return 0
    if cmd == "cli":
        # Portable fallback for an agent whose client speaks no MCP: same tools,
        # same JSON, one JSON document on stdout. `citlens.cmd search --topic ...`
        cfg = load_config(config)
        rest2: list[str] = []
        i = 0
        while i < len(rest):  # drop the global --config pair before tool parsing
            if rest[i] == "--config" and i + 1 < len(rest):
                i += 2
                continue
            rest2.append(rest[i])
            i += 1
        name, args = _parse_cli_args(rest2)
        if not name:
            print(json.dumps({"ok": False, "error": "usage: cli <tool> [--key value ...]",
                              "tools": [t["name"] for t in TOOL_DEFS]}, ensure_ascii=False, indent=1))
            return 2
        try:
            payload = handle_tool(cfg, name, args)
        except Exception as e:  # noqa: BLE001
            payload = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        print(json.dumps(payload, ensure_ascii=False, indent=1, default=str))
        return 0
    if cmd == "selftest":
        return selftest(load_config(config))
    if cmd == "run-job":
        job_dir = config_kind = None
        kind = "search"
        i = 0
        while i < len(rest):
            if rest[i] == "--job-dir" and i + 1 < len(rest):
                job_dir = rest[i + 1]
                i += 2
            elif rest[i] == "--kind" and i + 1 < len(rest):
                kind = rest[i + 1]
                i += 2
            elif rest[i] == "--config" and i + 1 < len(rest):
                config_kind = rest[i + 1]
                i += 2
            else:
                i += 1
        if not job_dir:
            _log("run-job needs --job-dir")
            return 2
        return run_job(job_dir, config_kind or "", kind)
    print(f"usage: {Path(__file__).name} [serve|tools|selftest|cli|run-job] [--config PATH]")
    return 2


def console_main() -> None:
    """Console entry point (`citlens-mcp`). Defaults to `serve` so an MCP client
    can point at the command with no arguments."""
    argv = list(sys.argv[1:])
    if not argv:
        argv = ["serve"]
    sys.exit(main(argv))


if __name__ == "__main__":
    sys.exit(main())
