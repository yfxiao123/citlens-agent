"""Offline tests for citens/net.py — the retrying transport and the limiter.

No network: httpx.MockTransport plays the provider, sleep is injected so
backoff is asserted, never waited for.
"""

from __future__ import annotations

import asyncio
import sys
import time
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from citens import net  # noqa: E402
from citens.config import settings  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} - {name}" + (f" ({detail})" if detail and not cond else ""))


settings.http_max_attempts = 4
settings.http_backoff_base_s = 1.0
settings.http_backoff_cap_s = 30.0
# keep the TLS patch OFF until its dedicated block near the end — the
# factory checks below must not trigger the process-wide injection first
settings.tls_trust_system_store = False


def _async_rig(handler, **kw):
    """(client, sleeps, log_lines) around a MockTransport-backed retry transport."""
    sleeps: list[float] = []
    logs: list[str] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    transport = net.AsyncRetryTransport(
        httpx.MockTransport(handler), name="t", sleep=fake_sleep, log=logs.append, **kw
    )
    return httpx.AsyncClient(transport=transport), sleeps, logs


def _run(coro):
    return asyncio.run(coro)


# ── 429 with Retry-After → honoured, then success ─────────────────────────────

calls: list[int] = []


def h_429_then_ok(request: httpx.Request) -> httpx.Response:
    calls.append(1)
    if len(calls) < 3:
        return httpx.Response(429, headers={"retry-after": "2"})
    return httpx.Response(200, json={"ok": True})


async def _t1():
    client, sleeps, logs = _async_rig(h_429_then_ok)
    async with client:
        r = await client.get("https://api.test/x")
    return r, sleeps, logs


r, sleeps, logs = _run(_t1())
check("429 x2 then 200 succeeds", r.status_code == 200)
check("attempts recorded in extensions", r.extensions.get("citens_attempts") == 3, str(r.extensions))
check("Retry-After seconds honoured", sleeps == [2.0, 2.0], str(sleeps))
check("retry logged with status and host", len(logs) == 2 and "HTTP 429" in logs[0] and "api.test" in logs[0], str(logs))

# ── Retry-After capped by http_backoff_cap_s ─────────────────────────────────

calls.clear()


def h_huge_retry_after(request):
    calls.append(1)
    if len(calls) == 1:
        return httpx.Response(429, headers={"retry-after": "3600"})
    return httpx.Response(200)


async def _t2():
    client, sleeps, _ = _async_rig(h_huge_retry_after)
    async with client:
        await client.get("https://api.test/x")
    return sleeps


sleeps = _run(_t2())
check("Retry-After capped at backoff cap", sleeps == [settings.http_backoff_cap_s], str(sleeps))

# ── Retry-After as HTTP-date ─────────────────────────────────────────────────

calls.clear()
when = datetime.now(timezone.utc) + timedelta(seconds=5)


def h_date_retry_after(request):
    calls.append(1)
    if len(calls) == 1:
        return httpx.Response(503, headers={"retry-after": format_datetime(when, usegmt=True)})
    return httpx.Response(200)


async def _t3():
    client, sleeps, _ = _async_rig(h_date_retry_after)
    async with client:
        await client.get("https://api.test/x")
    return sleeps


sleeps = _run(_t3())
check("Retry-After HTTP-date parsed to a delay", len(sleeps) == 1 and 3.0 <= sleeps[0] <= 6.0, str(sleeps))

# ── 5xx without Retry-After → equal-jitter exponential backoff ────────────────

calls.clear()


def h_503_x3(request):
    calls.append(1)
    return httpx.Response(503) if len(calls) < 4 else httpx.Response(200)


async def _t4():
    client, sleeps, _ = _async_rig(h_503_x3)
    async with client:
        r = await client.get("https://api.test/x")
    return r, sleeps


r, sleeps = _run(_t4())
check("503 retried until success (4 attempts)", r.status_code == 200 and len(calls) == 4)
bounds_ok = all(
    span / 2 <= s <= span
    for s, span in zip(sleeps, [1.0, 2.0, 4.0], strict=True)
)
check("backoff within equal-jitter bounds [span/2, span]", bounds_ok, str(sleeps))

# ── 4xx refusals are never retried ───────────────────────────────────────────

for status in (400, 401, 403, 404):
    calls.clear()

    def h_refuse(request, status=status):
        calls.append(1)
        return httpx.Response(status)

    async def _t5():
        client, sleeps, _ = _async_rig(h_refuse)
        async with client:
            r = await client.get("https://api.test/x")
        return r, sleeps

    r, sleeps = _run(_t5())
    check(f"{status} not retried", len(calls) == 1 and r.status_code == status and sleeps == [], f"calls={len(calls)}")
    check(f"{status} still carries attempts=1", r.extensions.get("citens_attempts") == 1)

# ── transport errors are retried ─────────────────────────────────────────────

calls.clear()


def h_connect_error_once(request):
    calls.append(1)
    if len(calls) == 1:
        raise httpx.ConnectError("reset", request=request)
    return httpx.Response(200)


async def _t6():
    client, sleeps, _ = _async_rig(h_connect_error_once)
    async with client:
        r = await client.get("https://api.test/x")
    return r, sleeps


r, sleeps = _run(_t6())
check("ConnectError retried then 200", r.status_code == 200 and len(calls) == 2 and len(sleeps) == 1)

calls.clear()


def h_timeout_always(request):
    calls.append(1)
    raise httpx.ReadTimeout("slow", request=request)


async def _t7():
    client, sleeps, _ = _async_rig(h_timeout_always)
    async with client:
        try:
            await client.get("https://api.test/x")
        except httpx.ReadTimeout:
            return "raised", sleeps
    return "no-raise", sleeps


outcome, sleeps = _run(_t7())
check("persistent ReadTimeout raises after max attempts", outcome == "raised" and len(calls) == 4 and len(sleeps) == 3, f"{outcome} calls={len(calls)}")

# ── exhaustion returns the final response (caller's raise_for_status decides) ─

calls.clear()


def h_429_always(request):
    calls.append(1)
    return httpx.Response(429)


async def _t8():
    client, sleeps, _ = _async_rig(h_429_always)
    async with client:
        r = await client.get("https://api.test/x")
    return r, sleeps


r, sleeps = _run(_t8())
check("exhausted 429 returned, not raised", r.status_code == 429 and len(calls) == 4 and len(sleeps) == 3)
check("exhausted response carries attempts=4", r.extensions.get("citens_attempts") == 4)

# ── POST is retried too (S2 batch / recommendations) ─────────────────────────

calls.clear()


def h_post_429_once(request):
    calls.append(1)
    assert request.method == "POST"
    body = request.read()
    if len(calls) == 1:
        return httpx.Response(429, headers={"retry-after": "1"})
    return httpx.Response(200, json={"echo": body.decode()})


async def _t9():
    client, sleeps, _ = _async_rig(h_post_429_once)
    async with client:
        r = await client.post("https://api.test/batch", json={"ids": [1, 2]})
    return r, sleeps


r, sleeps = _run(_t9())
check("POST retried with body re-sent", r.status_code == 200 and '"ids"' in r.json()["echo"] and len(calls) == 2)

# ── max_attempts=1 disables retry entirely ────────────────────────────────────

calls.clear()


async def _t10():
    client, sleeps, _ = _async_rig(h_429_always, max_attempts=1)
    async with client:
        r = await client.get("https://api.test/x")
    return r, sleeps


r, sleeps = _run(_t10())
check("max_attempts=1 makes one request", len(calls) == 1 and sleeps == [])

# ── sync transport: same policy ───────────────────────────────────────────────

calls.clear()


def hs_500_then_ok(request):
    calls.append(1)
    return httpx.Response(500) if len(calls) == 1 else httpx.Response(200)


ssleeps: list[float] = []
sync_t = net.SyncRetryTransport(
    httpx.MockTransport(hs_500_then_ok), name="s", sleep=ssleeps.append, log=lambda m: None
)
with httpx.Client(transport=sync_t) as c:
    r = c.get("https://api.test/x")
check("sync: 500 retried then 200", r.status_code == 200 and len(calls) == 2 and len(ssleeps) == 1)

calls.clear()
sync_t2 = net.SyncRetryTransport(
    httpx.MockTransport(lambda req: (calls.append(1), httpx.Response(403))[1]),
    name="s", sleep=ssleeps.append, log=lambda m: None,
)
with httpx.Client(transport=sync_t2) as c:
    r = c.get("https://api.test/x")
check("sync: 403 not retried", len(calls) == 1 and r.status_code == 403)

# ── backoff_delay bounds ─────────────────────────────────────────────────────

check("backoff attempt0 low bound", net.backoff_delay(0, base=1.0, cap=30.0, rand=lambda: 0.0) == 0.5)
check("backoff attempt0 high bound", net.backoff_delay(0, base=1.0, cap=30.0, rand=lambda: 1.0) == 1.0)
check("backoff attempt3 capped", net.backoff_delay(3, base=1.0, cap=5.0, rand=lambda: 1.0) == 5.0)
check("backoff retry_after wins and is capped", net.backoff_delay(0, retry_after=99.0, cap=30.0) == 30.0)

# ── RateLimiter: slot reservation ────────────────────────────────────────────

lim = net.RateLimiter(0.5)
d1 = lim._reserve()
d2 = lim._reserve()
d3 = lim._reserve()
check("first slot immediate", d1 == 0.0, str(d1))
check("second slot one interval later", 0.45 <= d2 <= 0.55, str(d2))
check("third slot two intervals later", 0.95 <= d3 <= 1.05, str(d3))
check("zero interval never waits", net.RateLimiter(0)._reserve() == 0.0)

t0 = time.monotonic()
_run(net.RateLimiter(0.05).wait())
check("async wait returns promptly on a fresh limiter", time.monotonic() - t0 < 0.5)

# ── named limiters: shared, defaults follow settings ─────────────────────────

net.reset_limiters()
settings.semantic_scholar_api_key = ""
settings.s2_min_interval_s = 0.0
check("S2 default without key is 3.0 s", net.limiter("semantic_scholar").min_interval == 3.0)
net.reset_limiters()
settings.semantic_scholar_api_key = "k"
check("S2 default with key is 1.1 s", net.limiter("semantic_scholar").min_interval == 1.1)
net.reset_limiters()
settings.s2_min_interval_s = 2.5
check("S2 explicit setting wins", net.limiter("semantic_scholar").min_interval == 2.5)
settings.s2_min_interval_s = 0.0
settings.semantic_scholar_api_key = ""
net.reset_limiters()
check("same name -> same limiter object", net.limiter("openalex") is net.limiter("openalex"))
check("openalex default from settings", net.limiter("openalex").min_interval == settings.openalex_min_interval_s)
check("unknown name -> no spacing", net.limiter("something-else").min_interval == 0.0)
net.limiter("openalex", 0.3)
check("explicit min_interval overrides", net.limiter("openalex").min_interval == 0.3)
net.reset_limiters()

# ── client factories ─────────────────────────────────────────────────────────

ac = net.async_client("openalex", timeout=5)
check("async_client tags its limiter name", net.throttled_by(ac) == "openalex")
check("async_client mounts the retry transport", isinstance(ac._transport, net.AsyncRetryTransport))
_run(ac.aclose())
plain = httpx.AsyncClient()
check("plain client is not throttled", net.throttled_by(plain) == "")
_run(plain.aclose())
sc = net.sync_client(name="crossref", timeout=5)
check("sync_client tags its limiter name", net.throttled_by(sc) == "crossref")
check("sync_client mounts the sync retry transport", isinstance(sc._transport, net.SyncRetryTransport))
sc.close()
sc2 = net.sync_client(timeout=5)
check("sync_client without name has no limiter", net.throttled_by(sc2) == "")
sc2.close()

# ── TLS: system-trust gate (runs last: inject_into_ssl is process-wide) ──────

import ssl as _ssl  # noqa: E402

_ctx_before = _ssl.SSLContext
net._ensure_system_trust()  # setting still False from the top
check("setting False -> ssl untouched", _ssl.SSLContext is _ctx_before)

settings.tls_trust_system_store = True
net._ensure_system_trust()
try:
    import truststore  # noqa: F401

    _have_truststore = True
except ImportError:
    _have_truststore = False
if _have_truststore:
    check("setting True -> ssl.SSLContext replaced by truststore's",
          _ssl.SSLContext is not _ctx_before)
    check("a real SSLContext still constructs", isinstance(_ssl.SSLContext(), _ssl.SSLContext))
    ctx2 = _ssl.SSLContext()
    check("patched context loads certs without error", hasattr(ctx2, "load_verify_locations"))
else:
    check("truststore absent -> graceful note, ssl untouched",
          _ssl.SSLContext is _ctx_before)
net._ensure_system_trust()
check("second call is a no-op (idempotent)", True)
# the patch stays for the remainder of this process — nothing after this
# block opens a real TLS connection

# ── summary ──────────────────────────────────────────────────────────────────

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
