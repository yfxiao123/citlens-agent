#!/usr/bin/env python
"""citlens_cli.py — CiteLens for agents: one CLI, any shell, no LLM key.

Why this file exists
--------------------
The agent-specific half of CiteLens (persona + skill + mode picker) cannot be
shared: Codex reads AGENTS.md, Claude reads CLAUDE.md, DSH reads bundles. What
*can* be shared is the part that actually finds literature. So the split is:

    this repo (retrieval core, LLM-free)  ->  this CLI  ->  {any agent with a shell}

Every agent that can run a command gets the same tools, the same retrieval
method and — because they all point at one CITLENS_HOME — the same literature
pool. An agent that searches here can hand its pool to another agent that
writes the review. (An MCP server used to live here; it was removed in 2.0 —
the CLI was always the primary interface and the protocol layer only ever
re-exported it.)

The deliberate design decision: this CLI makes **zero LLM calls and needs zero
LLM keys**. The calling agent IS the model — it crafts the queries (`queries`),
supplies anchor titles (`title_probes`) and web phrasings (`web_queries`),
judges the relevance of the returned pool, and writes the review under the
skill's verification discipline. What the CLI owns is everything mechanical and
reproducible: the eight recall families, RRF fusion, citation snowball, survey
harvest, full-text fetch, BibTeX/RIS export, the honest health buckets and the
PRISMA exclusion log.

This file deliberately imports **nothing from citens**. It is a stdlib-only
front end that translates command-line arguments into calls on the two drivers
— `citlens_recall.py` (eight-family recall) and `citlens_tools.py`
(fetch / export / audit / screen / verify / ...) — in this repo's own
interpreter. The retrieval method therefore stays exactly where it is measured
and tested; this layer adds no retrieval logic of its own.

Interface contract
------------------
    citlens_cli.py <tool> [--key value ...]     one JSON document on stdout
    cli <tool> ...                              same thing, explicit form
    tools                                       print the tool catalogue
    selftest                                    config + doctor smoke test
    run-job                                     internal: detached job runner
                                                (spawned by search/fetch)

Exit codes are part of the contract: 0 = the tool ran (inspect the JSON for
`ok: false`), 1 = the tool reported failure, 2 = usage error. stdout carries
the JSON document ONLY; every log line goes to stderr.

Config
------
    %USERPROFILE%\\.citlens\\config.json     (written by install.py)
    $CITLENS_CONFIG                          override the file path
    $CITLENS_HOME                            override the data home
    $CITLENS_PYTHON                          override the repo interpreter
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

SERVER_NAME = "citlens"
SERVER_VERSION = "2.0.0"  # 2.0: the MCP server is gone; the CLI is the interface

_REPO_ROOT = Path(__file__).resolve().parent

ALL_FAMILIES = [
    "agent", "raw", "oa_title", "s2_rec", "snowball", "web", "survey", "policy",
]

# The retrieval discipline every interface reminds the model about. These are
# the rules from the CiteLens skill that must survive the trip through an agent
# that never read the skill at all (e.g. one that only ran `tools` or `search`).
# It used to ride the MCP initialize handshake; now `tools` prints it and
# `search` results carry the pointer.
DISCIPLINE = (
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
    "duplicates accumulating pools pick up. Pass `web_queries` (English "
    "verbatim spans + natural Chinese phrasings) for the web bridge, and for "
    "macro/economics/policy topics pass plain-econ `policy_queries`: the "
    "policy family pulls NBER working papers, Fed Board FEDS Notes and IMF "
    "papers directly, and pool records carry doc_type/policy_org so journal "
    "evidence and policy-side framing can be read as two perspectives on one "
    "question, not blended. The "
    "tool runs eight recall families fused by RRF; it does NOT rank by relevance "
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
    "and it computes the honesty block. clean=false means fix, not ship. "
    "Structure the review body as 归→评→找→定: consolidate the consensus across "
    "papers, discriminate the disagreements and why they diverge, locate the "
    "research gap those two movements earn, then position the user's own work "
    "on it (stop at the gaps if the user described no work of their own) — "
    "integrative analysis, never a paper-by-paper listing. Search results may "
    "carry a `discipline` hint (e.g. economics), detected mechanically from "
    "your topic and queries: when present, apply that field's disciplines — "
    "the pointer text arriving with the result states their core rules, and "
    "the skill's discipline layers hold the full versions. Before writing the "
    "找 movement run `gaps`: its coverage matrix exposes concept blocks x "
    "periods the pool never reached, `mine` returns verbatim limitation/"
    "future-work sentences you can cite as span-verifiable gap evidence, and "
    "`check` mechanically rebuts a draft gap statement by finding its "
    "nearest existing work. Prose style, 去AI味: "
    "alternate long and short sentences, no double quotes around concepts, "
    "results stated in the sentence rather than parenthesized, no templated "
    "layered listing, and every sentence carries a clear subject."
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
    # 20, not 45: interactive callers want an answer fast (measured history:
    # MCP clients hard-killed a tool call at 30s and the kill took the freshly
    # spawned runner down with it; same UX applies to a shell). Returning the
    # job_id at ~20s leaves the poll pattern (`status`) as the only contract;
    # raising this per-call via wait_seconds is fine for scripted runs.
    "wait_seconds": 20,
    "max_concurrent_jobs": 3,
}


def _log(msg: str) -> None:
    """stderr only — stdout belongs to the JSON document."""
    try:
        sys.stderr.write(f"[citlens] {msg}\n")
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
    cfg["config_explicit"] = bool(explicit or os.environ.get("CITLENS_CONFIG"))
    cfg["config_found"] = path.is_file()
    cfg["config_error"] = None
    if path.is_file():
        try:
            disk = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(disk, dict):
                cfg.update(disk)
            else:
                cfg["config_error"] = "top-level JSON is not an object"
        except Exception as e:  # noqa: BLE001
            cfg["config_error"] = f"{type(e).__name__}: {e}"
            _log(f"config {path} unreadable ({e}); using defaults")
    elif cfg["config_explicit"]:
        cfg["config_error"] = "explicitly requested config does not exist"
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
    On POSIX, signal 0 is the existence probe: ProcessLookupError means gone,
    but PermissionError means the process EXISTS under another uid — the old
    blanket `except Exception` read that as dead and would reap a live runner
    (caught by review during the POSIX verification pass; mocked-testable).
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
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists — we merely may not signal it
    except Exception:  # noqa: BLE001 — anything else (bad pid type, ...)
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
    reap_dead_jobs(cfg)  # persist lost BEFORE reading — one truth for all callers
    st = _read_json(d / "state.json")
    if not st:
        return {"job_id": job_id, "state": "unknown", "hint": "no such job id"}
    st.setdefault("job_id", job_id)
    st["job_dir"] = str(d)
    st["log_path"] = str(d / "log.txt")
    if st.get("state") == "lost":
        # The runner died without writing a terminal state (client restart,
        # kill, reboot, shell tree cleanup). Never lie about it; the work may
        # still have completed — point at the artifacts.
        st.setdefault("hint", (
            "runner process is gone and wrote no exit state. The work may have "
            "completed: check `run_dir` / the log tail, then call status again "
            "after re-reading the artifacts."
        ))
    return st


def reap_dead_jobs(cfg: dict) -> None:
    """Reap jobs whose runner is dead OR stale, persisting state=lost once so
    no job flaps between running/lost (measured 2026-11-06: the inline
    job_state check only patched the RETURNED dict — doctor kept counting a
    corpse as running; and a recycled Windows pid made _pid_alive lie in
    both directions across polls). Two loss shapes:
    - pid dead: client kill / shell tree cleanup / reboot.
    - pid "alive" but the job went silent: on Windows pids recycle within
      minutes, so a fresh unrelated process can hold the dead runner's pid.
      A running job with NEITHER state.json NOR log.txt touched for 45 min
      is treated as lost-stale (longest legit silence: first-call embedding
      model download, minutes; search/gaps/screen all log or finish well
      inside the window).
    Called from every state-reading path (_running_jobs, tool_status /
    job_state) — status is THE way agents poll, it must not serve stale
    "running" from a corpse. The log keeps the evidence."""
    now = time.time()
    for d in sorted(jobs_root(cfg).iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        if not d.is_dir():
            continue
        st_path = d / "state.json"
        st = _read_json(st_path)
        if st.get("state") != "running":
            continue
        pid = st.get("pid")
        log_path = d / "log.txt"
        try:
            last_touch = max(st_path.stat().st_mtime, log_path.stat().st_mtime)
        except OSError:
            last_touch = d.stat().st_mtime
        silent_min = (now - last_touch) / 60
        if pid and _pid_alive(pid) and silent_min < 45:
            continue
        if not pid and (now - d.stat().st_mtime) < 120:
            # spawned but the runner hasn't written its pid yet — too young
            # to call dead (start_job -> run_job handshake window)
            continue
        st["state"] = "lost"
        st["error"] = (
            f"runner process is dead (silent {silent_min:.0f} min; client kill, "
            "shell tree cleanup, pid reuse or reboot); see log"
        )
        _write_json(st_path, st)


def _running_jobs(cfg: dict) -> list[dict]:
    reap_dead_jobs(cfg)
    out = []
    for d in sorted(jobs_root(cfg).iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        if not d.is_dir():
            continue
        st = _read_json(d / "state.json")
        if st.get("state") == "running":
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
    """Spawn a DETACHED runner so the job survives the calling shell / agent.

    That detachment is the whole point: the user can start a 5-minute recall,
    close the terminal or the agent, and read the pool from another agent a
    minute later.
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
                "is_review", "url", "source", "doc_type", "policy_org",
                "quality_flag")


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
    slug = slugify(topic)
    if not slug:
        # "   " slugifies to "" and `startswith("")` matches EVERY run dir —
        # a blank topic silently read an arbitrary pool (third-party report,
        # offline P2-5).
        return None, f"topic {topic!r} has no usable slug (letters/digits/CJK required)"
    litdb = home / "data" / "litdb" / f"{slug}.jsonl"
    if litdb.is_file():
        return litdb, str(litdb)
    runs = home / "citlens-runs"
    if runs.is_dir():
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
    missing: list[str] = []  # nothing is required; kept for older consumers
    # The guide table (citens.keyguide) is the single source of truth for
    # which free key un-degrades what, in measured-impact order.
    sys.path.insert(0, str(_REPO_ROOT))
    from citens.keyguide import absent as keys_absent
    from citens.keyguide import guide as keys_guide

    key_guide = keys_guide(env_keys)
    recommended = [e["key"] for e in keys_absent(env_keys)]
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
        "config_found": bool(cfg.get("config_found")),
        "config_explicit": bool(cfg.get("config_explicit")),
        "config_error": cfg.get("config_error"),
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
        # per-key {key, present, what, effect, register, cost} — the agent
        # relays one line per absent key to the user (see the skill)
        "key_guide": key_guide,
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
    # A config that was EXPLICITLY requested but is missing/unreadable is a
    # hard failure, not a silent fall back to defaults: the old doctor said
    # ok=true while every tool quietly ran on the default home (third-party
    # report, install-mcp P2-2).
    if cfg.get("config_error"):
        report["ok"] = False
    notes = []
    if cfg.get("config_error"):
        notes.append(
            f"config problem: {cfg['config_error']} — "
            f"path={cfg.get('config_path')}. Tools are running on DEFAULT settings "
            "until this is fixed (run install.py apply, or point --config at a valid file)."
        )
    if not report["ok"] and not families_invalid and not cfg.get("config_error"):
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
              "but the other families still run; NO key is required)"
        )
        # one actionable line per absent key — what improves, where to get it
        for e in keys_absent(env_keys):
            how = (
                f"register free: {e['register']} ({e['cost']})"
                if e["register"] else f"{e['cost']} — no registration"
            )
            notes.append(f"  {e['key']} — {e['effect']} {how}."
                         + (f" Set it in {env_file}." if env_file else ""))
    report["notes"] = notes
    return report


def _run_driver_json(cfg: dict, kind: str, argv: list[str], timeout: int = 240) -> dict:
    """Synchronous, short driver call whose only stdout is one JSON document."""
    python = cfg.get("python")
    driver = cfg.get("recall_driver") if kind == "search" else cfg.get("tools_driver")
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # An explicit --config must reach the driver's OWN config resolution:
    # without this the driver re-reads ~/.citlens/config.json and pools land
    # in the default home while the caller reads the custom one (2.0 retest
    # P1-2: export reported "pool not found", audit silently returned 0).
    if cfg.get("home"):
        env["CITLENS_HOME"] = cfg["home"]
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
        "policy_queries": _as_list(args.get("policy_queries")),
        "pivot": int(args.get("pivot") or 0),
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
    if args.get("force"):
        # bypass the caches (positive fulltext + the 1-day miss negative
        # cache) and re-run every leg — the only escape after an outage-day
        # miss or an upstream fix (third-party addendum P2-12).
        argv += ["--force"]
    if args.get("background"):
        # A fulltext download + PDF conversion can take many minutes and
        # would hold the calling shell hostage. background runs the same
        # driver as a detached job; poll `status` — for tools jobs the
        # log_tail IS the result JSON.
        started = start_job(cfg, "fetch", {"argv": argv})
        if started.get("ok"):
            started["hint"] = (
                "poll `status` with this job_id; the fetch result JSON "
                "arrives in log_tail when state=done"
            )
        return started
    out = _run_driver_json(cfg, "tools", argv, timeout=300)
    if out.get("ok") is False:
        return out  # the driver's error speaks for itself
    out.setdefault("note", "")
    # The prefix must match what ACTUALLY came back: the old blanket "abstract-
    # only" line also fired for records with NO abstract at all, overriding the
    # driver's honest "cannot be cited as evidence" note (2.0 retest P2).
    if out.get("fulltext"):
        prefix = (
            "Use the text (text_path / head) as the ONLY grounding for claims "
            "about this paper; cite locatable page/section when quoting. "
        )
    elif out.get("abstract"):
        prefix = (
            "fulltext=false → abstract-only: claims must stay within what the "
            "abstract states, and the review's honesty block must count it. "
        )
    else:
        prefix = (
            "fulltext=false and NO abstract: this record cannot ground any "
            "claim — do not cite it (fix metadata via another source, or drop). "
        )
    out["note"] = prefix + str(out.get("note") or "")
    return out


def _caller_path(v) -> str:
    """Resolve a path argument against the CALLER's cwd.

    Drivers run with cwd=<data home>, so a relative path forwarded verbatim
    resolves against the home and the caller gets "review not found" for a
    file sitting next to their shell (2.0 retest P2: SKILL's own examples
    `verify --review review.md`, `export --out refs.bib` hit this).
    """
    s = str(v)
    p_ = Path(s)
    return s if p_.is_absolute() else str(p_.resolve())


def tool_export(cfg: dict, args: dict) -> dict:
    argv = ["export", "--format", (args.get("format") or "bib").lower()]
    if args.get("topic"):
        argv += ["--topic", str(args["topic"])]
    if args.get("run_dir"):
        argv += ["--run-dir", str(args["run_dir"])]
    if args.get("out"):
        argv += ["--out", _caller_path(args["out"])]
    if args.get("with_labels"):
        argv += ["--with-labels"]
    return _run_driver_json(cfg, "tools", argv, timeout=120)


def tool_audit(cfg: dict, args: dict) -> dict:
    topic = (args.get("topic") or "").strip()
    if not topic:
        return {"ok": False, "error": "topic is required (byte-identical to the search)"}
    argv = ["audit", "--topic", topic]
    queries = _as_list(args.get("queries"))
    if queries:
        argv += ["--queries", *queries]
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
    run_dir = st.get("run_dir")
    if not run_dir and st.get("state") in ("done", "lost"):
        # "lost" may have finished its work before the runner died; a FAILED
        # job must never inherit the previous run's artifacts by mtime.
        run_dir = _find_run_dir(cfg, "search", float(st.get("started_ts") or 0))
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
        signals = _read_json(rd / "queries.json")
        qj = signals.get("query_feedback") or []
        sat = signals.get("saturation") or {}
        if sat.get("verdict"):
            out["saturation"] = {
                "verdict": sat.get("verdict"),
                "reasons": sat.get("reasons", []),
                "chao_coverage": (sat.get("chao") or {}).get("coverage"),
                "new_share": sat.get("new_share"),
            }
        if qj:
            out["query_feedback"] = [
                {"query": q.get("query", "")[:60], "total": q.get("total", 0),
                 "verdict": q.get("verdict", "?")}
                for q in qj
            ]
            weak = [q for q in qj if q.get("verdict") in ("empty", "thin")]
            if weak:
                out["weak_queries"] = [q.get("query", "")[:60] for q in weak]
        # discipline layer hint (detected mechanically from the topic/queries):
        # carries the matched field's core disciplines as a pointer, so a
        # client that never loaded the skill still receives them
        disc = _read_json(rd / "discipline.json")
        if disc.get("name"):
            out["discipline"] = disc
        by_source: dict[str, int] = {}
        no_doi = no_venue = reviews = 0
        from citens.models import review_title_hint

        for rec in pool:
            by_source[rec.get("source") or "?"] = by_source.get(rec.get("source") or "?", 0) + 1
            no_doi += 0 if rec.get("doi") else 1
            no_venue += 0 if rec.get("venue") else 1
            reviews += 1 if (rec.get("is_review")
                             or review_title_hint(rec.get("title"))) else 0
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


def _maybe_background(cfg: dict, args: dict, argv: list, tool_name: str, topic: str):
    """Long tools (screen / gaps / expand) run as DETACHED JOBS by default —
    harness-first (2026-11-06): these operations legitimately take minutes
    (embedding download, decide layer, citation crawls) — long enough that a
    synchronous call would hold the agent's shell hostage for the whole run
    (this class of failure killed screen and expand live in the A股动量机制
    run). Background-by-default makes that class structurally impossible
    instead of patched per-incident; pass
    ``background: false`` to run synchronously (small pools, quick checks).
    Poll `status` — for tools jobs the log_tail IS the result JSON (compact
    view; full records in the artifact files)."""
    if args.get("background") is False:
        return None
    started = start_job(cfg, tool_name, {"argv": argv, "topic": topic or ""})
    if started.get("ok"):
        started["hint"] = (
            "running as a detached job (default for long tools); poll "
            "`status` with this job_id — the result JSON arrives in "
            "log_tail when state=done. Pass background:false for a "
            "synchronous small-pool call."
        )
    return started


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
        val = args.get(key)
        if val is None:
            # harness-CLI aliases: `citlens.cmd screen --core 0.5` parses to
            # the short key, which the tool schema never mentioned and the
            # old lookup silently dropped (third-party report, offline P2-3).
            val = args.get(flag[2:].replace("-", "_"))
        if val is not None:
            argv += [flag, str(val)]
    if args.get("decide"):
        argv += ["--decide"]
        if args.get("decide_limit") is not None:
            argv += ["--decide-limit", str(args["decide_limit"])]
    # first call may download the local model; give it room
    bg = _maybe_background(cfg, args, argv, "screen", topic)
    if bg is not None:
        return bg
    return _run_driver_json(cfg, "tools", argv, timeout=900)


def tool_gaps(cfg: dict, args: dict) -> dict:
    """Mechanical substrate for the 找 movement — all channels zero LLM."""
    topic = (args.get("topic") or "").strip()
    run_dir = (args.get("run_dir") or "").strip()
    if not topic and not run_dir:
        return {"ok": False, "error": "pass topic or run_dir"}
    argv = ["gaps"]
    if run_dir:
        argv += ["--run-dir", run_dir]
    if topic:
        argv += ["--topic", topic]
    queries = _as_list(args.get("queries"))
    if queries:
        argv += ["--queries", *queries]
    if args.get("check"):
        argv += ["--check", str(args["check"])]
    if args.get("mine"):
        argv += ["--mine"]
    if args.get("fulltext_dir"):
        argv += ["--fulltext-dir", str(args["fulltext_dir"])]
    if args.get("limit") is not None:
        argv += ["--limit", str(args["limit"])]
    if args.get("model") is not None:
        argv += ["--model", str(args["model"])]
    # embedding model download on first call can be slow; mining is local I/O
    bg = _maybe_background(cfg, args, argv, "gaps", topic)
    if bg is not None:
        return bg
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
    bg = _maybe_background(cfg, args, argv, "expand", topic)
    if bg is not None:
        return bg
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
    # resolve BEFORE argv construction — the driver's cwd is the data home, so
    # a caller-relative review path must anchor to the caller's cwd first
    review = _caller_path(review)
    argv = ["verify", "--review", review]
    # argparse accepts ONLY the hyphenated long options. The old list passed
    # `--run_dir`/`--text_dir` (the tool-argument snake_case names) straight
    # through, so the driver exited 2 with "unrecognized arguments" and MCP
    # surfaced "driver produced no JSON" (found by the 2026-11-06 third-party
    # test, offline-tools P1-1).
    for flag, key, rel in (("--topic", "topic", False), ("--run-dir", "run_dir", True),
                           ("--verdicts", "verdicts", True), ("--text-dir", "text_dir", True),
                           ("--out", "out_dir", True), ("--out", "out", True)):
        if args.get(key):
            argv += [flag, _caller_path(args[key]) if rel else str(args[key])]
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
        st["ok"] = False
        return st
    st["ok"] = True  # the read succeeded — the JOB's own state is in `state`
    if st.get("kind") != "search":
        # tools jobs (fetch/screen/verify via background:true) print their
        # result JSON to the job log — the tail IS the deliverable; the
        # search-view's run-dir scavenging does not apply to them.
        st = dict(st)
        st["log_tail"] = _tail_text(
            Path(st["log_path"]), _clamp(args.get("log_lines", 200), 0, 2000, 200)
        )
        if st.get("state") == "done":
            st["note"] = "job done — the result JSON is in log_tail (raise log_lines if truncated)"
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
    from citens.models import review_title_hint

    def _is_review(rec: dict) -> bool:
        return bool(rec.get("is_review")) or review_title_hint(rec.get("title"))

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
        if want_review is True and not _is_review(rec):
            return False
        if want_review is False and _is_review(rec):
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
    by_doc_type: dict[str, int] = {}
    by_policy_org: dict[str, int] = {}
    for r in matched:
        if r.get("doc_type"):
            by_doc_type[r["doc_type"]] = by_doc_type.get(r["doc_type"], 0) + 1
        if r.get("policy_org"):
            by_policy_org[r["policy_org"]] = by_policy_org.get(r["policy_org"], 0) + 1
    return {
        "ok": True,
        "pool_path": str(path),
        "total": total,
        "matched": len(matched),
        "shown": len(shown),
        "stats": {
            "missing_doi": sum(0 if r.get("doi") else 1 for r in matched),
            "missing_venue": sum(0 if r.get("venue") else 1 for r in matched),
            "reviews": sum(1 for r in matched if _is_review(r)),
            "with_fulltext_hint": sum(1 for r in matched if r.get("pdf_url")),
            "by_source": by_source,
            "by_doc_type": by_doc_type,
            "by_policy_org": by_policy_org,
            "by_year": dict(sorted(by_year.items())),
        },
        "papers": [_compact_paper(r, fields) for r in shown],
        "note": (
            "This reads the pool on disk — no retrieval happened. If the numbers are "
            "thin for your purpose, run `search` with more families/target rather than "
            "claiming coverage from this subset."
        ),
    }


# ── tool catalogue (CLI help / docs; printed by `tools`) ─────────────────────

TOOL_DEFS = [
    {
        "name": "search",
        "description": (
            "Find literature with CiteLens — and YOU are the query planner. Craft the "
            "English concept-block queries yourself (4-6 concepts x 2-4 synonyms, "
            "combination queries first; see the skill's PRESS discipline) and pass "
            "them as `queries`. The tool runs eight recall families (your queries, "
            "raw topic, OpenAlex title match over `title_probes`, Semantic-Scholar "
            "recommendations, citation snowball, web bridge over `web_queries`, "
            "survey reference harvest, and the policy corpus — NBER / Fed Board / "
            "IMF over `policy_queries`) fused by reciprocal-rank fusion under "
            "per-family seat quotas. It does NOT rank by relevance — judge the "
            "returned pool yourself. Writes pool.jsonl + search_report.md + "
            "exclusions.jsonl + queries.json (per-query hit feedback — rephrase "
            "empty/thin blocks in paper-side vocabulary). Returns a job id; pass "
            "wait_seconds (default 20 from config) or poll `status`. Use this instead of "
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
                "policy_queries": {"type": "array", "items": {"type": "string"},
                                   "description": "Queries for the policy corpus (NBER working papers, Fed Board FEDS Notes/working papers, IMF): plain economist phrasing, not ML-style concept blocks. Default: reuse `queries` or the topic."},
                "target": {"type": "integer", "description": "Max kept papers (0 = no truncation). Default from config."},
                "families": {"type": "array", "items": {"type": "string", "enum": ALL_FAMILIES},
                             "description": "Subset of the eight families to run (default: all)."},
                "sources": {"type": "array", "items": {"type": "string"},
                            "description": "Metadata sources, e.g. arxiv, semantic_scholar, openalex, crossref."},
                "append_pool": {"type": "boolean", "description": "Merge results into the shared per-topic pool (default true)."},
                "pivot": {"type": "integer",
                          "description": "Mechanical pivot expansion (0 = off, default): after the first wave, build up to N queries from the corroborated head records' discriminative terms (LLM-free PRF local analysis; skips when fewer than 3 cross-family-corroborated seeds exist). Use 2 when the topic vocabulary is uncertain."},
                "wait_seconds": {"type": "integer", "description": "Block up to this long before returning with a job id (0-300). Default from config (20, safe for clients that hard-kill calls at 30s); raise it only when the client tolerates long calls."},
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
                           "description": "Subset of title,authors,year,venue,doi,citation_count,is_review,url,source,doc_type,policy_org,quality_flag,abstract,keywords,pdf_url."},
            },
        },
    },
    {
        "name": "fetch",
        "description": (
            "Grounding substrate: fetch one paper's open-access full text (arXiv -> "
            "S2 -> OpenAlex -> Unpaywall -> CORE, PDF converted to text, cached; "
            "optional scansci-pdf last resort). Falls back to the abstract when "
            "there is no OA copy — and to an explicit not-citable note when there "
            "is no abstract either. Use it BEFORE citing claims about a paper's "
            "methods/results."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "doi": {"type": "string"},
                "title": {"type": "string"},
                "arxiv": {"type": "string", "description": "arXiv id, e.g. 2401.12345"},
                "topic": {"type": "string", "description": "Resolve the record from this topic's pool first."},
                "run_dir": {"type": "string", "description": "Resolve the record from this run's pool.jsonl."},
                "force": {"type": "boolean",
                          "description": "Ignore both the fulltext cache and the short-lived failure cache and retry every leg (use after a network/proxy outage)."},
                "background": {"type": "boolean",
                               "description": "DEFAULT FALSE. Pass true to run as a detached job and get a job_id immediately (a fulltext download + PDF conversion can take minutes). Poll `status` — for tools jobs log_tail IS the result JSON. This and `search` are the only detaching tools."},
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
                "queries": {"type": "array", "items": {"type": "string"},
                            "description": "Your concept-block queries: rank survey anchors by topical relevance (default: citation count, which can pick an off-topic highly-cited survey)."},
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
                "core_threshold": {"type": "number", "description": "core band cutoff (default 0.65, LitSearch pilot-calibrated)."},
                "off_threshold": {"type": "number", "description": "likely_off band cutoff (default 0.32)."},
                "limit": {"type": "integer", "description": "Records to return (default 30)."},
                "decide": {"type": "boolean",
                           "description": "Decision layer (opt-in): an LLM logit readout re-bands records with calibrated 3-way probabilities; high-confidence auto-banded, the rest escalate to uncertain for your own review. Needs LLM_API_BASE/LLM_API_KEY/LLM_MODEL in the data home .env; without them the report says so and mechanical bands stand."},
                "decide_limit": {"type": "integer",
                                 "description": "Max records the decision layer processes (0 = all; default 0)."},
                "background": {"type": "boolean",
                               "description": "CLI contract: ALWAYS synchronous — run the command through your shell's own background mechanism when the pool is big. `--background true` is refused with exit 2 (a detached job spawned from a short-lived shell dies with the shell's process tree, measured). Only `search` and `fetch --background true` detach."},
            },
            "required": [],
        },
    },
    {
        "name": "gaps",
        "description": (
            "Mechanical substrate for locating research gaps (找), zero LLM. "
            "Three channels, all opt-in: (1) `queries` → a coverage matrix of "
            "the pool by concept block x time band — empty/sparse cells a "
            "block otherwise populates are STRUCTURAL gap candidates "
            "(evidence-gap-map logic); (2) `mine: true` → verbatim "
            "limitation/future-work sentences extracted from fetched "
            "fulltexts, each with paper+section+cue — quote them as gap "
            "evidence and `verify` checks the span like any other; "
            "(3) `check: \"<draft gap statement>\"` → nearest existing pool "
            "records by statement-term coverage + embedding — a close neighbour "
            "is mechanical refutation that the gap may already be done. Run all three "
            "before writing the 找 movement; cite stated gaps with [n]."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic pool (byte-identical slug)."},
                "run_dir": {"type": "string", "description": "A specific run directory instead."},
                "queries": {"type": "array", "items": {"type": "string"},
                            "description": "Your concept-block queries — build the coverage matrix over them."},
                "check": {"type": "string", "description": "Draft gap statement: nearest existing work is returned as potential refutation."},
                "mine": {"type": "boolean", "description": "Mine limitation/future-work sentences from the fulltext dir (fetch core papers first)."},
                "fulltext_dir": {"type": "string", "description": "Fulltext directory (default 'fulltext')."},
                "limit": {"type": "integer", "description": "Cap for novelty neighbours and stated-gap hits (default 40)."},
                "model": {"type": "string",
                          "description": "Novelty-check embedding model override (empty string disables the semantic channel — use for offline runs)."},
                "background": {"type": "boolean",
                               "description": "CLI contract: ALWAYS synchronous (the embedding download or a big coverage matrix runs for many minutes — wrap in your shell's background mechanism). `--background true` is refused with exit 2."},
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
                "background": {"type": "boolean",
                               "description": "CLI contract: ALWAYS synchronous (citation crawls are throttled and run for many minutes — wrap in your shell's background mechanism). `--background true` is refused with exit 2."},
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
            "signals (exact DOI, arXiv id, normalized title — a specific title "
            "with >=4 tokens stands alone even when authors are missing, which "
            "is common for OpenAlex title-search records; short titles still "
            "need a shared author). "
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
    if name == "gaps":
        return tool_gaps(cfg, args)
    if name == "verify":
        return tool_verify(cfg, args)
    if name == "expand":
        return tool_expand(cfg, args)
    if name == "notes":
        return tool_notes(cfg, args)
    if name == "dedup":
        return tool_dedup(cfg, args)
    return {"ok": False, "error": f"unknown tool {name!r}", "tools": [t["name"] for t in TOOL_DEFS]}


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
        if payload.get("policy_queries"):
            argv += ["--policy-queries", *payload["policy_queries"]]
        if payload.get("append_pool"):
            argv += ["--append-pool"]
        if payload.get("pivot"):
            argv += ["--pivot", str(payload["pivot"])]
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
    state.update(
        state="done" if code == 0 else "failed",
        exit_code=code,
        ended_at=_iso(),
        elapsed_s=round(elapsed, 1),
        runner_pid=os.getpid(),
    )
    if code == 0:
        run_dir = _find_run_dir(cfg, kind, started)
        if run_dir:
            state["run_dir"] = run_dir
    else:
        # A failed driver never owns an artifact directory. Scanning by
        # mtime picked up the PREVIOUS successful run (its pool.jsonl is
        # newer than the job start when the failure happens seconds after
        # the last run), so `status` attributed old artifacts to the failed
        # job (third-party report, live-recall P2-7).
        run_dir = None
        state.pop("run_dir", None)
        state["error"] = f"driver exited {code}; see log"
    _write_json(jd / "state.json", state)
    emit(f"== {'done' if code == 0 else 'FAILED'} code={code} elapsed={elapsed:.0f}s run_dir={run_dir} ==")
    return 0


# ── selftest / CLI ────────────────────────────────────────────────────────────


def selftest(cfg: dict) -> int:
    """Offline checks: config resolution, tool list, doctor, pool reader."""
    problems = []
    # Report the config ACTUALLY in use — `selftest --config X` printed the
    # default ~/.citlens/config.json while loading X (third-party report P3).
    path = Path(cfg.get("config_path") or config_path(None))
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
    print("interface: cli dispatch + doctor exercised by tests/test_portable.py")
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(f" - {p}")
        return 1
    print("\nselftest OK")
    return 0


_LIST_KEYS = ("families", "sources", "fields", "themes",
              "queries", "title_probes", "web_queries", "policy_queries",
              "seeds", "directions")


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
            # enum-ish lists accept both the JSON-array form (`--families a b`)
            # and the comma form the drivers use (`--families a,b`) — the
            # latter used to arrive as ONE value and the tool rejected it
            if key in ("families", "sources", "fields", "directions"):
                vals = [x for v in vals for x in v.split(",") if x]
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


_TOOL_NAMES = [t["name"] for t in TOOL_DEFS]
_META_COMMANDS = ("tools", "selftest", "run-job", "cli")


def _cli_dispatch(cfg: dict, rest: list[str]) -> int:
    """The one and only front end: tool name + flags -> one JSON document."""
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
        print(json.dumps({"ok": False,
                          "error": f"usage: {Path(__file__).name} <tool> [--key value ...] "
                                   "(or: tools | selftest)",
                          "tools": _TOOL_NAMES, "discipline": DISCIPLINE},
                         ensure_ascii=False, indent=1))
        return 2
    if name in ("screen", "gaps", "expand"):
        # A CLI caller HAS a shell — detachment is the caller's job (run the
        # command itself in background). A detached job spawned from a
        # short-lived shell command dies with the shell's process tree anyway
        # (measured 2026-11-06: citlens.cmd screen -> job lost mid-embedding
        # when the shell returned). Run synchronously; `--background true`
        # is refused with a note.
        if args.get("background"):
            print(json.dumps({"ok": False, "error":
                "background is not available on the CLI (a detached job "
                "spawned from a shell command dies with the shell's "
                "process tree). Run this command synchronously, or wrap "
                "it in your shell's own background mechanism "
                "(run_in_background), then read the artifact files."},
                ensure_ascii=False))
            return 2
        args["background"] = False
    try:
        payload = handle_tool(cfg, name, args)
    except Exception as e:  # noqa: BLE001
        payload = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(payload, ensure_ascii=False, indent=1, default=str))
    # harness semantics: the exit code is part of the contract — automation
    # branches on it. This returned 0 unconditionally, so `citlens.cmd pool
    # --topic missing` and unknown tools both read as success (measured
    # 2026-11-06). NOTE: several views (status, doctor) carry no `ok` key —
    # absence must mean success, only an explicit false (or a bare error)
    # fails; the first cut of this rule broke `status` (state=done, exit 1).
    failed = payload.get("ok") is False or (
        payload.get("ok") is None and bool(payload.get("error"))
    )
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    # `--config PATH` may sit before or after the tool name (the shim and
    # hand-typed calls both do this); no tool takes a --config argument
    config = None
    rest = list(argv)
    if "--config" in rest:
        i = rest.index("--config")
        if i + 1 < len(rest):
            config = rest[i + 1]
            del rest[i:i + 2]
    cmd = rest[0] if rest else ""
    rest = rest[1:]
    if cmd == "cli":  # explicit form: `cli search --topic ...`
        return _cli_dispatch(load_config(config), rest)
    if cmd == "tools":
        print(json.dumps({"tools": TOOL_DEFS, "discipline": DISCIPLINE},
                         ensure_ascii=False, indent=1))
        return 0
    if cmd == "serve":
        # 2.0 removed the MCP server — the CLI is the interface. Old client
        # registrations still point here; tell the caller exactly that.
        print(json.dumps({"ok": False,
                          "error": "the MCP server was removed in 2.0 — the CLI is the "
                                   "interface. Run `install.py apply` to clean up this "
                                   "registration, then call the tools as shell commands "
                                   "(citlens.cmd <tool> ...).",
                          "tools": _TOOL_NAMES}, ensure_ascii=False))
        return 2
    if cmd == "selftest":
        return selftest(load_config(config))
    if cmd == "run-job":
        job_dir = None
        kind = "search"
        i = 0
        while i < len(rest):
            if rest[i] == "--job-dir" and i + 1 < len(rest):
                job_dir = rest[i + 1]
                i += 2
            elif rest[i] == "--kind" and i + 1 < len(rest):
                kind = rest[i + 1]
                i += 2
            else:
                i += 1
        if not job_dir:
            _log("run-job needs --job-dir")
            return 2
        # `config` was extracted globally above (it is NOT in `rest` any
        # more). The runner MUST load the SAME config the caller passed —
        # with the default config it spawns the default interpreter and
        # drivers, which on a machine with multiple checkouts silently runs
        # a diverged driver tree (2.0 retest P1-2).
        return run_job(job_dir, config or "", kind)
    if cmd in _TOOL_NAMES:  # bare tool form: `citlens.cmd search --topic ...`
        return _cli_dispatch(load_config(config), [cmd, *rest])
    if not cmd:
        _cli_dispatch(load_config(config), [])  # prints usage + tool list
        return 2
    print(json.dumps({"ok": False, "error": f"unknown command {cmd!r}",
                      "tools": _TOOL_NAMES}, ensure_ascii=False, indent=1))
    return 2


def console_main() -> None:
    """Console entry point (`citlens-agent`). Bare invocation prints usage."""
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
