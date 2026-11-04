"""On-disk cache for search results and LLM responses.

Keyed by a stable hash of the logical inputs (namespace + serialized payload),
so identical queries/completions short-circuit on re-runs. Disable via
``CACHE_ENABLED=false``. Cheap by design: one JSON file per entry.

TTL: entries older than ``CACHE_TTL_DAYS`` are treated as misses on read and
deleted by a throttled sweep on write (once per ``CACHE_SWEEP_INTERVAL_DAYS``).
Namespaces decay at different rates — search/enrich results go stale as the
scholarly indexes move; LLM completions keyed on fixed prompts do not.

Empty values are NOT cached unless the caller says so (``allow_empty=True``):
an empty list/dict/string is far more often a throttled or failed provider
than a true negative, and caching one poisons every retry for the TTL
(measured twice: a whole bench rerun served cached zeros; OpenAlex 200-empty
responses frozen for a day). Legitimate negatives go through a dedicated
short-TTL namespace instead (``fulltext.miss``).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
from typing import Any

from citens.config import settings

# Namespace-specific TTL multipliers applied to settings.cache_ttl_days.
# "llm" entries are keyed on (model, prompts, params) and "fulltext*" are
# derived from persisted PDFs (papers/) — hits stay valid, so they never
# expire by default. A stale fulltext miss self-heals: a PDF dropped into
# papers/ is checked before the cache. "fulltext.miss" is the negative
# cache for failed OA fetches — short-lived so a proxy hiccup is retried
# tomorrow, not never.
_TTL_DAYS_BY_NS: dict[str, int] = {
    "llm": 0,
    "fulltext": 0,
    "fulltext_local": 0,
    "fulltext.miss": settings.fulltext_miss_ttl_days,
}

_SWEEP_MARKER = "last_sweep"


def _key(namespace: str, payload: Any) -> str:
    raw = json.dumps({"ns": namespace, "p": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _ttl_seconds(namespace: str) -> float:
    days = _TTL_DAYS_BY_NS.get(namespace, settings.cache_ttl_days)
    return days * 86400.0 if days > 0 else 0.0


def _path(key: str) -> str:
    d = os.path.join(settings.cache_dir, "kv")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{key}.json")


def _age(p: str) -> float:
    try:
        return max(0.0, time.time() - os.path.getmtime(p))
    except OSError:
        return 0.0


def get(namespace: str, payload: Any) -> Any | None:
    if not settings.cache_enabled:
        return None
    p = _path(_key(namespace, payload))
    ttl = _ttl_seconds(namespace)
    if os.path.exists(p):
        if ttl and _age(p) > ttl:
            return None  # stale: miss (the sweep will reclaim the file)
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _sweep(force: bool = False) -> None:
    """Delete expired entries; throttled to one pass per sweep interval."""
    interval = settings.cache_sweep_interval_days
    if interval <= 0 and not force:
        return
    marker = _path(_SWEEP_MARKER)
    if not force and _age(marker) < interval * 86400.0:
        return
    try:
        with open(marker, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time()}, f)
    except OSError:
        return
    d = os.path.dirname(marker)
    try:
        names = os.listdir(d)
    except OSError:
        return
    for name in names:
        if not name.endswith(".json") or name.startswith(_SWEEP_MARKER):
            continue
        p = os.path.join(d, name)
        # ttl unknown per-file here (namespace lives in the key, not the
        # entry); use the longest default — stale-for-any-namespace files
        # whose namespace expired are already misses on read.
        ttl = settings.cache_ttl_days * 86400.0
        if ttl and _age(p) > ttl:
            with contextlib.suppress(OSError):
                os.remove(p)


def is_empty_value(value: Any) -> bool:
    """None or a zero-length str/list/dict/tuple/set. Numbers (0, False)
    are values, not absences."""
    if value is None:
        return True
    return isinstance(value, (str, list, dict, tuple, set)) and len(value) == 0


def put(namespace: str, payload: Any, value: Any, *, allow_empty: bool = False) -> None:
    """Store ``value``; empties are skipped unless ``allow_empty`` (see module
    docstring — an empty result is usually a failed provider, not a fact)."""
    if not settings.cache_enabled:
        return
    if not allow_empty and is_empty_value(value):
        return
    p = _path(_key(namespace, payload))
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False)
    except OSError:
        pass
    _sweep()
