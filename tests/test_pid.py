"""_pid_alive contract on BOTH branches (Windows live-checked, POSIX mocked).

The POSIX branch is unreachable on a Windows dev box, so it is verified by
mocking os.name + os.kill — the review pass found the old blanket except
read PermissionError as dead (POSIX: kill(pid,0) PermissionError MEANS the
process exists, owned by another uid), which would reap live runners.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import citlens_mcp as m  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name} {detail}")


# ── common ───────────────────────────────────────────────────────────────────
check("falsy pid (None/0) -> False", m._pid_alive(None) is False and m._pid_alive(0) is False)

# ── Windows branch (live, we run on it) ──────────────────────────────────────
check("win: own pid alive", m._pid_alive(os.getpid()) is True)
check("win: impossible pid dead", m._pid_alive(9999999) is False)

# ── POSIX branch (mocked) ────────────────────────────────────────────────────
with patch("os.name", "posix"), patch("os.kill") as kill:
    kill.return_value = None  # exists
    check("posix: kill(pid,0) returns -> alive", m._pid_alive(4242) is True)
    kill.assert_called_once_with(4242, 0)
    check("posix: signal is 0 (probe, never a real signal)",
          kill.call_args.args[1] == 0)

    kill.side_effect = ProcessLookupError()
    check("posix: ProcessLookupError -> dead", m._pid_alive(4242) is False)

    kill.side_effect = PermissionError()
    check("posix: PermissionError -> ALIVE (other-uid runner; was read dead)",
          m._pid_alive(4242) is True)

    kill.side_effect = OSError("weird")
    check("posix: other OSError -> dead (fail closed)", m._pid_alive(4242) is False)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
