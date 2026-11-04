"""Key guidance — the single source of truth for "which free key un-degrades what".

Nothing here is required: every source runs unauthenticated (rate-limited)
and the build has no LLM key by design. This table exists so the surfaces
that CAN guide a user — `doctor`, the `install.py init` wizard, the recall
report's degradation notes — all say the same thing, concretely: what the
key improves, where to register (free), and where to put it.

Ordered by measured impact: a Semantic Scholar key buys reliability (the
shared anonymous pool 429s constantly), Serper buys an entire family (the
web bridge), OpenAlex's key buys ten times the daily budget, and the two
"email" entries are polite-pool upgrades with no registration at all.
"""

from __future__ import annotations

KEY_GUIDE: list[dict] = [
    {
        "key": "SEMANTIC_SCHOLAR_API_KEY",
        "what": "Semantic Scholar search, recommendations, citation snowball",
        "effect": (
            "guaranteed 1 req/s tier instead of the shared anonymous pool "
            "(3 s spacing today, frequent 429s after retries) — s2_rec / "
            "snowball / survey families stop throttling mid-run"
        ),
        "register": "https://www.semanticscholar.org/product/api",
        "cost": "free, instant (form)",
        "no_registration": False,
    },
    {
        "key": "SERPER_API_KEY",
        "what": "web bridge primary engine (Google SERP)",
        "effect": (
            "the web family runs on Google SERP; without it the bridge falls "
            "back to keyless DuckDuckGo/Bing scraping, which throttles and "
            "fails cells (smoke runs show whole web legs at failed=2/3)"
        ),
        "register": "https://serper.dev",
        "cost": "free 2,500 credits, no card",
        "no_registration": False,
    },
    {
        "key": "OPENALEX_API_KEY",
        "what": "OpenAlex keyed pool + snowball/oa-title throughput",
        "effect": (
            "10,000 credits/day keyed instead of the anonymous 1,000 req/day "
            "pool that dies by mid-morning on heavy days (a works query "
            "costs 10 credits — measured)"
        ),
        "register": "https://openalex.org/premium",
        "cost": "free for individual researchers (request form)",
        "no_registration": False,
    },
    {
        "key": "OPENALEX_EMAIL",
        "what": "OpenAlex polite pool",
        "effect": "faster, fairer rate treatment on the anonymous pool",
        "register": "",
        "cost": "free — any email you own, no registration",
        "no_registration": True,
    },
    {
        "key": "CROSSREF_EMAIL",
        "what": "Crossref polite pool",
        "effect": "polite-pool rate treatment + better metadata availability",
        "register": "",
        "cost": "free — any email you own, no registration",
        "no_registration": True,
    },
]


def guide(env_keys: list[str] | set[str]) -> list[dict]:
    """The guide table annotated with presence, for `doctor` and friends."""
    have = set(env_keys)
    return [
        {**entry, "present": entry["key"] in have}
        for entry in KEY_GUIDE
    ]


def absent(env_keys: list[str] | set[str]) -> list[dict]:
    """Only the missing ones, in impact order (doctor notes, wizard)."""
    have = set(env_keys)
    return [entry for entry in KEY_GUIDE if entry["key"] not in have]
