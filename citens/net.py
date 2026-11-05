"""Network access layer — honors the user's declared access, and makes every
request survive the public APIs' moods.

Two jobs live here.

**Access routing** (unchanged): users often have institutional access the
public sources don't (campus EZproxy, a local proxy, or a VPN). HTTP fetches
(PDFs, landing pages, enrichment APIs) are routed through a configured proxy
and, optionally, only for domains the user says they can reach, with EZproxy
URL-rewriting for campus libraries:

    https://lib.univ.edu.cn/login?url=https%3A%2F%2Fwww.sciencedirect.com%2F...

**Reliability** (added): one retrying transport under every outbound request.
429 / 408 / 5xx and transient transport errors (connect, read timeout, reset)
are retried with the provider's ``Retry-After`` when present (capped),
otherwise equal-jitter exponential backoff. Other 4xx — 401/403/400/404 —
are never retried: a rejected key stays rejected. A named ``RateLimiter``
spaces request starts per provider, shared process-wide across the async
search legs and the sync fulltext legs (S2 counts every endpoint against one
bucket, so the bucket must be shared too).

All retry logging goes to STDERR: stdout of the tool drivers is a single JSON
document, and the MCP protocol frames own the server's stdout.
"""

from __future__ import annotations

import asyncio
import contextlib
import email.utils
import inspect
import random
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

from citens.config import settings

# Hosts that serve open metadata/PDFs — never worth routing through a proxy
# or an EZproxy rewrite (would only add latency and breakage).
_FREE_HOSTS = {
    "arxiv.org",
    "export.arxiv.org",
    "api.unpaywall.org",
    "api.openalex.org",
    "api.crossref.org",
    "api.semanticscholar.org",
}


def domain_allowed(url: str | None) -> bool:
    """True if `url`'s host is in the user's accessible_domains (empty = all)."""
    if not url:
        return True
    allowed = [d.strip().lower() for d in settings.accessible_domains.split(",") if d.strip()]
    if not allowed:
        return True
    host = (urlparse(url).hostname or "").lower()
    return any(host == a or host.endswith("." + a) for a in allowed)


def proxy_url_for(url: str | None) -> str | None:
    """The proxy to use for `url`, or None. Respects accessible_domains."""
    if url and not domain_allowed(url):
        return None
    if not (settings.http_proxy or settings.https_proxy):
        return None
    scheme = urlparse(url).scheme if url else "https"
    if scheme == "http":
        return settings.http_proxy or settings.https_proxy or None
    return settings.https_proxy or settings.http_proxy or None


def rewrite_url(url: str) -> str:
    """Rewrite `url` through the campus EZproxy prefix when appropriate.

    Rules:
      * no prefix configured -> unchanged;
      * free/open hosts (arXiv, OpenAlex, ...) -> unchanged;
      * ACCESSIBLE_DOMAINS set -> rewrite only those hosts;
      * ACCESSIBLE_DOMAINS empty -> rewrite every non-free host (setting a
        prefix means "this is how I reach the web").
    """
    prefix = settings.ezproxy_prefix.strip()
    if not prefix:
        return url
    host = (urlparse(url).hostname or "").lower()
    if not host or host in _FREE_HOSTS:
        return url
    if not domain_allowed(url):
        return url
    if not prefix.endswith("="):
        prefix += "?url="  # tolerate a prefix given without the query param
    return f"{prefix}{quote(url, safe='')}"


# --- TLS through the OS certificate store -------------------------------------

_SSL_PATCHED = False


def _ensure_system_trust() -> None:
    """Validate TLS against the OS certificate store, once per process.

    SSL-inspecting proxies (campus / corporate gateways) inject their own CA
    into every handshake. That CA is installed in the Windows/system store —
    Python's certifi bundle does not carry it, so every inspected host dies
    with CERTIFICATE_VERIFY_FAILED: self-signed certificate in chain
    (measured on the dev machine: api.semanticscholar.org unreachable, all
    other sources fine — the tell that it was local interception, not the
    provider). truststore makes ssl.SSLContext load the OS store; this
    covers httpx AND the arxiv wrapper's urllib client, process-wide.
    """
    global _SSL_PATCHED
    if _SSL_PATCHED or not settings.tls_trust_system_store:
        return
    _SSL_PATCHED = True
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception as e:  # noqa: BLE001 — degrade to certifi, say so once
        _net_log(f"[net] system-trust TLS unavailable ({type(e).__name__}: {e}); using certifi")


# --- rate limiting ------------------------------------------------------------


class RateLimiter:
    """Minimum spacing between request starts; slots are RESERVED, not held.

    ``_reserve`` hands out successive start slots (now, now+d, now+2d, ...)
    under a cheap thread lock, and callers sleep out only their own slot —
    so one slow request never blocks the queue behind it, and the async and
    sync legs of one provider share the same bucket.
    """

    def __init__(self, min_interval: float) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self._last_start = 0.0
        self._lock = threading.Lock()

    def _reserve(self) -> float:
        """Reserve the next start slot; return how long to wait for it."""
        with self._lock:
            now = time.monotonic()
            start = max(now, self._last_start + self.min_interval)
            self._last_start = start
            return start - now

    async def wait(self) -> None:
        if self.min_interval > 0:
            delay = self._reserve()
            if delay > 0:
                await asyncio.sleep(delay)

    def wait_sync(self) -> None:
        if self.min_interval > 0:
            delay = self._reserve()
            if delay > 0:
                time.sleep(delay)


def _default_interval(name: str) -> float:
    if name == "semantic_scholar":
        if settings.s2_min_interval_s > 0:
            return settings.s2_min_interval_s
        # keyed tier is 1 rps cumulative; the shared unkeyed pool is meaner
        return 1.1 if settings.semantic_scholar_api_key else 3.0
    if name == "openalex":
        return settings.openalex_min_interval_s
    if name == "crossref":
        return settings.crossref_min_interval_s
    return 0.0


_LIMITERS: dict[str, RateLimiter] = {}
_LIMITERS_LOCK = threading.Lock()


def limiter(name: str, min_interval: float | None = None) -> RateLimiter:
    """The process-wide limiter for `name` (created on first use).

    ``min_interval`` None = the configured default for that provider;
    an explicit value overrides whatever the limiter currently holds.
    """
    with _LIMITERS_LOCK:
        lim = _LIMITERS.get(name)
        if lim is None:
            lim = RateLimiter(
                _default_interval(name) if min_interval is None else min_interval
            )
            _LIMITERS[name] = lim
        elif min_interval is not None:
            lim.min_interval = max(0.0, float(min_interval))
        return lim


def reset_limiters() -> None:
    """Drop all named limiters (tests)."""
    with _LIMITERS_LOCK:
        _LIMITERS.clear()


# --- retry policy -------------------------------------------------------------


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Seconds the provider asks us to wait, or None. Handles both the
    delta-seconds and the HTTP-date forms; negative dates clamp to 0."""
    value = (resp.headers.get("retry-after") or "").strip()
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def backoff_delay(
    attempt: int,
    retry_after: float | None = None,
    *,
    base: float | None = None,
    cap: float | None = None,
    rand: Callable[[], float] = random.random,
) -> float:
    """Seconds to sleep before retry `attempt` (0-based = after failure #1).

    Retry-After is honoured but capped; otherwise equal-jitter exponential
    backoff — delay/2 + rand()*delay/2 — so a burst of 429s without headers
    still backs off meaningfully while never doubling the wall time.
    """
    base = settings.http_backoff_base_s if base is None else base
    cap = settings.http_backoff_cap_s if cap is None else cap
    if retry_after is not None:
        return min(cap, retry_after)
    span = min(cap, base * (2**attempt))
    return span / 2.0 + rand() * span / 2.0


# transient by nature: worth another attempt. Everything else (4xx refusals,
# malformed requests) fails fast — retrying a rejected key only burns quota.
_RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_RETRY_EXCEPTIONS = (
    httpx.TimeoutException,       # connect / read / write / pool timeouts
    httpx.NetworkError,           # connect / read / write / close resets
    httpx.RemoteProtocolError,    # server cut the stream mid-response
)


def _net_log(msg: str) -> None:
    """Retry logs go to stderr: driver stdout is a single JSON document and
    the MCP protocol owns the server's stdout. Logging must never fail a
    request (a zh-CN console can choke on provider characters)."""
    with contextlib.suppress(Exception):
        sys.stderr.write(f"{msg}\n")
        sys.stderr.flush()


def _attempts_setting(max_attempts: int | None) -> int:
    return max(1, settings.http_max_attempts if max_attempts is None else max_attempts)


class AsyncRetryTransport(httpx.AsyncBaseTransport):
    """Wraps an inner async transport with throttle + retry, for every request
    made through the client it is mounted on."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        *,
        name: str = "http",
        rate: RateLimiter | None = None,
        max_attempts: int | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        log=None,
    ) -> None:
        self._inner = inner
        self._name = name
        self._rate = rate
        self._max_attempts = _attempts_setting(max_attempts)
        self._sleep = sleep or asyncio.sleep
        self._log = log or _net_log

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        for attempt in range(self._max_attempts):
            if self._rate is not None:
                await self._rate.wait()
            try:
                resp = await self._inner.handle_async_request(request)
            except _RETRY_EXCEPTIONS as e:
                if attempt + 1 >= self._max_attempts:
                    raise
                delay = backoff_delay(attempt)
                self._log(
                    f"[net:{self._name}] {type(e).__name__} on "
                    f"{request.url.host} — retry {attempt + 1}/{self._max_attempts - 1} in {delay:.1f}s"
                )
                await self._sleep(delay)
                continue
            if resp.status_code in _RETRY_STATUS and attempt + 1 < self._max_attempts:
                delay = backoff_delay(attempt, _retry_after_seconds(resp))
                self._log(
                    f"[net:{self._name}] HTTP {resp.status_code} from "
                    f"{request.url.host} — retry {attempt + 1}/{self._max_attempts - 1} in {delay:.1f}s"
                )
                await resp.aclose()
                await self._sleep(delay)
                continue
            resp.extensions["citens_attempts"] = attempt + 1
            return resp
        raise AssertionError("unreachable")  # pragma: no cover

    async def aclose(self) -> None:
        await self._inner.aclose()


class SyncRetryTransport(httpx.BaseTransport):
    """The sync twin of AsyncRetryTransport (fulltext / landing-page legs)."""

    def __init__(
        self,
        inner: httpx.BaseTransport,
        *,
        name: str = "http",
        rate: RateLimiter | None = None,
        max_attempts: int | None = None,
        sleep=None,
        log=None,
    ) -> None:
        self._inner = inner
        self._name = name
        self._rate = rate
        self._max_attempts = _attempts_setting(max_attempts)
        self._sleep = sleep or time.sleep
        self._log = log or _net_log

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for attempt in range(self._max_attempts):
            if self._rate is not None:
                self._rate.wait_sync()
            try:
                resp = self._inner.handle_request(request)
            except _RETRY_EXCEPTIONS as e:
                if attempt + 1 >= self._max_attempts:
                    raise
                delay = backoff_delay(attempt)
                self._log(
                    f"[net:{self._name}] {type(e).__name__} on "
                    f"{request.url.host} — retry {attempt + 1}/{self._max_attempts - 1} in {delay:.1f}s"
                )
                self._sleep(delay)
                continue
            if resp.status_code in _RETRY_STATUS and attempt + 1 < self._max_attempts:
                delay = backoff_delay(attempt, _retry_after_seconds(resp))
                self._log(
                    f"[net:{self._name}] HTTP {resp.status_code} from "
                    f"{request.url.host} — retry {attempt + 1}/{self._max_attempts - 1} in {delay:.1f}s"
                )
                resp.close()
                self._sleep(delay)
                continue
            resp.extensions["citens_attempts"] = attempt + 1
            return resp
        raise AssertionError("unreachable")  # pragma: no cover

    def close(self) -> None:
        self._inner.close()


# --- client factories ---------------------------------------------------------


# httpx >= 0.28 renamed `proxies` to `proxy` on both transports — detect once
_HAS_PROXY_KW = "proxy" in inspect.signature(httpx.AsyncHTTPTransport.__init__).parameters


def _proxy_kw(proxy: str | None) -> dict:
    if not proxy:
        return {}
    return {"proxy": proxy} if _HAS_PROXY_KW else {"proxies": proxy}


def async_client(
    name: str = "",
    *,
    timeout: float | httpx.Timeout = 30,
    headers: dict | None = None,
    min_interval: float | None = None,
    url: str | None = None,
    max_attempts: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    **kwargs,
) -> httpx.AsyncClient:
    """An async client with throttle + retry mounted, per `name`.

    `name` selects the process-wide rate limiter ("" = no throttling);
    `url` picks the proxy exactly like sync_client() does. `transport`
    replaces the inner transport entirely (test rig / exotic dial-in).
    """
    kwargs.setdefault("follow_redirects", True)
    _ensure_system_trust()
    proxy = proxy_url_for(url)
    inner = transport if transport is not None else httpx.AsyncHTTPTransport(**_proxy_kw(proxy))
    rate = limiter(name, min_interval) if name else None
    transport = AsyncRetryTransport(
        inner, name=name or "http", rate=rate, max_attempts=max_attempts
    )
    client = httpx.AsyncClient(
        transport=transport, timeout=timeout, headers=headers, **kwargs
    )
    client._citens_throttle = name  # type: ignore[attr-defined]
    return client


def throttled_by(client: httpx.AsyncClient | httpx.Client) -> str:
    """The limiter name a client's transport already waits on ("" for a
    plain httpx client) — so wrappers like S2's _throttled_get can skip
    their own wait instead of spacing every request twice."""
    return getattr(client, "_citens_throttle", "") or ""


def sync_client(url: str | None = None, **kwargs) -> httpx.Client:
    """A sync httpx.Client with throttle + retry, configured with
    timeout/redirects + proxy (if any). Keeps the httpx version difference
    (proxy= vs proxies=) in one place."""
    kwargs.setdefault("timeout", 60)
    kwargs.setdefault("follow_redirects", True)
    _ensure_system_trust()
    name = kwargs.pop("name", "")
    min_interval = kwargs.pop("min_interval", None)
    max_attempts = kwargs.pop("max_attempts", None)
    proxy = proxy_url_for(url)
    inner = httpx.HTTPTransport(**_proxy_kw(proxy))
    rate = limiter(name, min_interval) if name else None
    transport = SyncRetryTransport(
        inner, name=name or "http", rate=rate, max_attempts=max_attempts
    )
    client = httpx.Client(transport=transport, **kwargs)
    client._citens_throttle = name  # type: ignore[attr-defined]
    return client
