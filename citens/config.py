"""Application configuration, loaded from environment / .env via pydantic-settings.

All settings can be overridden by environment variables (case-insensitive) or a
local ``.env`` file. Run-time knobs (``--max-papers`` etc.) live on the CLI and
the :class:`RunOptions` dataclass, not here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_home() -> str:
    """The data home without touching the process CWD: ``CITLENS_HOME``
    wins, else ~/.citlens/config.json's ``home``, else "" (unconfigured)."""
    home = os.environ.get("CITLENS_HOME", "")
    if home:
        return home
    try:
        data = json.loads(
            (Path.home() / ".citlens" / "config.json").read_text(encoding="utf-8")
        )
        return str(data.get("home") or "")
    except (OSError, ValueError):
        return ""


def _resolve_env_file() -> str:
    """First existing of CWD ``.env`` and the data home ``.env``.

    pydantic resolves a relative ``env_file`` against the process CWD, so a
    driver launched from anywhere but the data home silently ran keyless —
    every source degraded to anonymous pools (measured 2026-11-05: an
    out-of-home launch produced an OpenAlex 429 storm and a false
    "SERPER_API_KEY 未配置" note while the keys sat in ``<home>/.env``).
    The MCP runner sets ``cwd=<home>`` for its jobs (contract,
    citlens_mcp.py), but nothing else has to honor it. An explicit
    ``CITLENS_HOME`` wins over config.json, matching the MCP layer.
    """
    if Path(".env").is_file():
        return ".env"
    home = _resolve_home()
    if home:
        cand = Path(home).expanduser() / ".env"
        if cand.is_file():
            return str(cand)
    return ".env"


def _resolve_litdb_dir() -> str:
    """Anchor the literature pools to the data home, not the CWD — the same
    trap as the env file: an out-of-home launch used to fork a private
    ``data/litdb`` under the repo, silently splitting the shared pool."""
    home = _resolve_home()
    if home:
        return str(Path(home).expanduser() / "data" / "litdb")
    return "data/litdb"


class Settings(BaseSettings):
    """Global settings. Stable defaults let the app run with a minimal ``.env``."""

    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(), env_file_encoding="utf-8", extra="ignore"
    )

    # NOTE: this build has NO LLM backend by design. The agent (Claude, Codex,
    # zcode, DSH, ...) that drives these tools IS the model: it plans the
    # queries, judges relevance, and writes. Only retrieval keys live here.

    # --- Search sources ------------------------------------------------------
    # Comma-separated subset, or "all". Order does not imply priority.
    search_sources: str = "arxiv,semantic_scholar,openalex,crossref"
    semantic_scholar_api_key: str = ""  # optional, raises rate limits
    openalex_email: str = ""  # optional, polite-pool
    openalex_api_key: str = ""  # premium key: 100k/day + higher rps (api_key param)
    # Daily self-imposed cap on OpenAlex CREDITS (persisted counter, survives
    # process restarts so repeated bench runs share one budget). 0 = off.
    # OpenAlex credit pricing: search= request 10 credits, filter= list 1
    # credit, single-record view free; the free plan includes $1/day =
    # 10000 credits. Default 9000 leaves headroom.
    openalex_daily_budget: int = 9000
    # Serper.dev web-search key (Google SERP; free tier 2500 queries) —
    # the primary engine of the web bridge channel
    serper_api_key: str = ""

    # --- Decision layer (optional; `screen --decide`) ------------------------
    # An OpenAI-compatible chat endpoint used ONLY by the opt-in decision
    # layer: relevance triage is read as a categorical distribution over
    # three bracketed options via next-token logprobs (training-free, no
    # fine-tune). The retrieval core stays LLM-free — without these the
    # tools run exactly as before on the mechanical channels.
    llm_api_base: str = ""  # e.g. https://api.deepseek.com
    llm_api_key: str = ""
    llm_model: str = ""
    # Selective prediction: records whose top band probability reaches
    # decide_auto_band are auto-banded; below it they escalate to the agent's
    # own review (forced uncertain). A record also auto-bands at
    # decide_agree_band when the decision model and the mechanical channels
    # independently agree — agreement is evidence.
    decide_auto_band: float = 0.8
    decide_agree_band: float = 0.6
    # Below this total probability mass on the three option tokens the
    # readout is off-script (the model ignored the format) -> escalate.
    decide_matched_mass_min: float = 0.2
    decide_min_interval_s: float = 0.2

    # --- Access layer (declare what YOU can reach; empty = public web only) ---
    # HTTP(S) proxy used when fetching paywalled PDFs / landing pages (e.g. a
    # campus EZproxy or local SOCKS/HTTP proxy). Lets you reach content the
    # public sources can't.
    http_proxy: str = ""
    https_proxy: str = ""
    # Comma-separated domains you have institutional access to (routed via the
    # proxy). Empty = apply proxy to every fetch when a proxy is set.
    accessible_domains: str = ""
    # Campus EZproxy URL prefix. When set, paywalled fetch URLs are rewritten as
    #   {EZPROXY_PREFIX}url=<urlencoded target>
    # so the request rides YOUR library session (e.g. after SSO login in the
    # same network). Example: https://lib.univ.edu.cn/login?url=
    # Leave empty to disable rewriting.
    ezproxy_prefix: str = ""
    papers_dir: str = "papers"

    # --- Metadata / enrichment API keys (optional) --------------------------
    # Used to fill in missing abstracts and find full text by DOI.
    crossref_email: str = ""  # Crossref polite pool (free, no key needed)
    springer_api_key: str = ""  # api.springernature.com
    elsevier_api_key: str = ""  # dev.elsevier.com
    ieee_api_key: str = ""  # IEEE Xplore
    core_api_key: str = ""  # api.core.ac.uk (free key; OA fulltext aggregator)
    # Chunk retrieval for grounding: "bm25" (default) | "keyword" | "embedding".
    # "embedding" additionally needs EMBEDDING_MODEL and degrades to bm25 on failure.
    retriever: str = "bm25"
    embedding_model: str = ""  # e.g. text-embedding-3-small (OpenAI-compatible)

    # --- Relevance screening (pool triage — the agent stays the judge) ------
    # Local sentence-transformers model for `screen`'s semantic channel.
    # "" disables the channel (lexical + consensus remain). Needs the optional
    # extra:  pip install "citlens-agent[embedding]"  — never an LLM key.
    # bge-*-en-v1.5 needs no retrieval instruction prefix (model card).
    screen_embedding_model: str = "BAAI/bge-base-en-v1.5"
    # Band cutoffs on the composite score: >= core -> "core"; < off ->
    # "likely_off"; between -> "uncertain". Heuristic defaults on the bge
    # cosine scale — provisional until calibrated on the LitSearch labels;
    # every call can override them.
    screen_core_threshold: float = 0.5
    screen_off_threshold: float = 0.32

    # --- Defaults for a run (overridable via CLI / RunOptions) ---------------
    default_max_results: int = 60  # candidate pool target before filtering
    default_max_papers: int = 20  # final papers kept after filtering (0 = no cap)
    # Supporting-reference layer: filtered-relevant papers beyond the core cap
    # that join the bibliography as abstract-only citations (background /
    # comparison cites). This is what separates "papers deep-read" from
    # "papers cited" — a real survey cites far more than it dissects.
    default_support_papers: int = 15
    enrich_abstracts: bool = True  # cross-source DOI enrichment for missing abstracts
    output_dir: str = "runs"
    # Persistent literature pools built by `citens collect` (JSONL per topic).
    # Default anchored to the data home (see _resolve_litdb_dir) so pools
    # stay shared regardless of where the process was launched from.
    litdb_dir: str = Field(default_factory=_resolve_litdb_dir)
    # Domain profile for collect/run (see citens profiles for the list).
    # "" = generic. Example: "finance".
    profile: str = ""
    # Output language of the review prose AND section headings: "en" or "zh".
    # Default Chinese — the primary reader writes Chinese reviews; anything
    # not recognized as Chinese falls back to English.
    review_language: str = "zh"

    # --- Venue-aware ranking -------------------------------------------------
    # Composite retrieval score = w_rel*(relevance/5) + w_cit*citation_factor
    #                        + w_ven*venue_factor(SJR quartile). See ranking.py.
    rank_weight_relevance: float = 0.6
    rank_weight_citations: float = 0.2
    rank_weight_venue: float = 0.2
    # First-author engagement (works/h-index from `citens collect`); excluded
    # from the composite (weights renormalized) when the metadata is unknown.
    rank_weight_author: float = 0.15
    # SCImago journal-rank CSV (semicolon-delimited). Downloaded once via
    # `citens sjr` — CC BY-NC licensed, so it is fetched, not shipped.
    sjr_csv_path: str = "data/sjr/sjr.csv"

    # --- Reliability ---------------------------------------------------------
    cache_enabled: bool = True
    cache_dir: str = ".cache"
    # Max age of cache entries, in days (0 = never expire). Search/enrich
    # results go stale as the indexes move; LLM responses keyed on fixed
    # prompts never do, so namespaces expire at different rates in cache.py.
    cache_ttl_days: int = 30
    # Auto-delete entries older than ttl on put(), throttled to one sweep
    # per N days (marker file). 0 disables sweeping.
    cache_sweep_interval_days: int = 1
    # A failed open-access fulltext fetch is remembered for this many days
    # before the network legs are tried again (0 = retry every run). It
    # used to be cached FOREVER as "" — one proxy/paywall hiccup froze a
    # paper as abstract-only until the cache was wiped by hand.
    fulltext_miss_ttl_days: int = 1

    # --- HTTP retry / throttle (citens.net) ----------------------------------
    # Every outbound request goes through one retrying transport: 429 / 408 /
    # 5xx and transport errors (connect, read timeout, reset) are retried with
    # Retry-After when the provider sends it, exponential backoff with full
    # jitter otherwise. Other 4xx (401/403/400/404) are never retried.
    http_max_attempts: int = 4
    http_backoff_base_s: float = 1.0
    http_backoff_cap_s: float = 30.0  # also caps an honoured Retry-After
    # Per-source minimum spacing between request STARTS, shared process-wide
    # (S2 counts every endpoint against one bucket). 0 for S2 = pick by key
    # presence: 1.1 s with a key (1 rps tier), 3.0 s without.
    s2_min_interval_s: float = 0.0
    openalex_min_interval_s: float = 0.12
    crossref_min_interval_s: float = 0.1
    # Circuit breaker: after this many CONSECUTIVE failed calls a source is
    # skipped for the rest of the process (one recall job = one process) and
    # reported as failed with the reason — instead of 15 queries each waiting
    # out a 90 s arXiv timeout. 401/403 open the circuit immediately.
    source_circuit_failures: int = 3
    # TLS: validate against the OPERATING SYSTEM's certificate store instead
    # of the certifi bundle. SSL-inspecting proxies (campus/corporate) inject
    # their own CA into every handshake — that CA is installed in the OS
    # store but absent from certifi, so requests die with
    # CERTIFICATE_VERIFY_FAILED: self-signed certificate in chain. False
    # restores the certifi-only behaviour.
    tls_trust_system_store: bool = True


settings = Settings()
