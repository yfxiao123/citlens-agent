"""Offline tests for citens/search/expand.py — the judgment feedback loop.

No network: resolve_seed takes an injected fetch; expand_from_seeds is tested
with the snowball/_s2_recommended callables monkeypatched.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from citens.models import Paper  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "expand_mod", ROOT / "citens" / "search" / "expand.py")
expand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(expand)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} - {name}" + (f" ({detail})" if detail and not cond else ""))


def _paper(title: str, doi: str | None = None, cites: int = 10) -> Paper:
    return Paper(title=title, authors=["A Author"], year=2023, doi=doi,
                 citation_count=cites, source="test")


# ── seed classification ───────────────────────────────────────────────────────

cases = [
    ("10.18653/v1/2024.acl-long.1", "doi"),
    ("https://doi.org/10.48550/arxiv.2301.12345", "doi"),
    ("doi:10.1000/xyz123", "doi"),
    ("2301.12345", "arxiv"),
    ("2301.12345v2", "arxiv"),
    ("arxiv:2301.12345", "arxiv"),
    ("https://arxiv.org/abs/2401.00001", "arxiv"),
    ("Dreamer: Mastering Diverse Domains", "title"),
    ("10.1093/notas", "doi"),
]
for seed, want in cases:
    check(f"seed_kind({seed[:34]!r}) == {want}",
          expand.seed_kind(seed) == want, f"got {expand.seed_kind(seed)}")

check("s2 id for arxiv seed strips version",
      expand._s2_lookup_id("2301.12345v2", "arxiv") == "ARXIV:2301.12345")
check("s2 id for doi seed keeps it verbatim",
      expand._s2_lookup_id("10.1/x y".replace(" ", ""), "doi") == "DOI:10.1/xy"
      or expand._s2_lookup_id("10.1/xy", "doi") == "DOI:10.1/xy")


# ── resolve_seed (injected fetch) ─────────────────────────────────────────────

def _fake_item(doi=None, arxiv=None, title="A Seed Paper"):
    ext = {}
    if doi:
        ext["DOI"] = doi
    if arxiv:
        ext["ArXiv"] = arxiv
    return {"title": title, "authors": [{"name": "A Author"}], "year": 2022,
            "abstract": "", "citationCount": 42, "externalIds": ext,
            "venue": "ACL", "url": "https://semanticscholar.org/x", "openAccessPdf": {}}


async def _t():
    # DOI seed: resolved with its own DOI (10.1000-style prefix — the regex
    # requires >=4 digits, matching every real registrant prefix)
    async def f1(url, params):
        assert url.endswith("/paper/DOI:10.1000/seed"), url
        return _fake_item(doi="10.1000/seed")

    p, note = await expand.resolve_seed("10.1000/seed", fetch=f1)
    check("doi seed resolves", p is not None and p.doi == "10.1000/seed", note)
    check("resolve note mentions kind", "doi" in note, note)

    # arXiv-only seed: DataCite DOI synthesized for the citation directions
    async def f2(url, params):
        assert "ARXIV:" in url, url
        return _fake_item(arxiv="2301.12345")

    p2, note2 = await expand.resolve_seed("2301.12345", fetch=f2)
    check("arxiv-only seed synthesizes DataCite DOI",
          p2 is not None and p2.doi == "10.48550/arxiv.2301.12345", str(p2 and p2.doi))

    # title seed: search endpoint, first hit
    async def f3(url, params):
        assert url.endswith("/paper/search"), url
        return {"data": [_fake_item(doi="10.9/hit")]}

    p3, note3 = await expand.resolve_seed("a seed paper about things", fetch=f3)
    check("title seed resolves via search", p3 is not None and p3.doi == "10.9/hit", note3)

    # 404-ish failure: honest None + reason, seed must not raise
    async def f4(url, params):
        raise RuntimeError("s2 404")

    p4, note4 = await expand.resolve_seed("10.1/gone", fetch=f4)
    check("failed seed returns None with reason", p4 is None and "404" in note4, note4)

    # no search hit
    async def f5(url, params):
        return {"data": []}

    p5, note5 = await expand.resolve_seed("zzz nothing", fetch=f5)
    check("title miss reported honestly", p5 is None and note5 == "no search hit", note5)


asyncio.run(_t())


# ── expand_from_seeds (network legs monkeypatched) ────────────────────────────

called = {"snowball": None, "recs": None}


async def _fake_resolve(seed, fetch=None):
    if "bad" in seed:
        return None, "not found"
    return _paper(f"seed:{seed}", doi=f"10.1/{seed.replace(' ', '-')}"), "resolved via doi"


async def _fake_snowball(anchors, existing_ids, **kw):
    called["snowball"] = {a.doi for a in anchors}
    return [_paper("cited-by-neighbor", doi="10.2/nb1"),
            _paper("already-in-pool", doi="10.2/old")]


async def _fake_recs(dois, limit=10):
    called["recs"] = list(dois)
    return [{"title": "recommended neighbor", "authors": [{"name": "B"}],
             "year": 2024, "citationCount": 5, "externalIds": {"DOI": "10.3/rec"},
             "venue": "", "url": "", "openAccessPdf": {}}]


expand.resolve_seed = _fake_resolve
expand.snowball = _fake_snowball
expand._s2_recommended = _fake_recs

existing = {_paper("already-in-pool", doi="10.2/old").id}


def _t2():
    out = expand.expand_from_seeds(
        ["good seed", "bad seed"], existing,
        directions={"backward", "forward", "related", "recs"},
        relevance_terms=["topic"], top=30,
    )
    return out


out = asyncio.run(_t2())
check("unresolved seed reported", len(out["unresolved"]) == 1
      and out["unresolved"][0]["seed"] == "bad seed")
check("snowball got only resolved anchors",
      called["snowball"] == {"10.1/good-seed"}, str(called["snowball"]))
check("recs got article-DOI anchors", called["recs"] == ["10.1/good-seed"])
check("existing ids filtered", all(p.id not in existing for p in out["papers"]))
check("both directions merged",
      {p.title for p in out["papers"]} == {"cited-by-neighbor", "recommended neighbor"},
      str([p.title for p in out["papers"]]))
check("found_by stamped expand", all(p.found_by == ["expand"] for p in out["papers"]))
check("counts honest", out["counts"] == {"seeds": 2, "resolved": 1,
                                         "snowball": 2, "recs": 1, "new": 2},
      str(out["counts"]))

# recs direction off -> recommendations never fire (the fake snowball ignores
# direction flags and returns both its papers; the empty existing set keeps both)
called["recs"] = None
out2 = asyncio.run(expand.expand_from_seeds(
    ["good seed"], set(), directions={"backward"}, top=5))
check("recs disabled not called", called["recs"] is None)
check("snowball-only expansion works", len(out2["papers"]) == 2)

# seed cap: more than 6 seeds -> honest note, only 6 resolved
many = asyncio.run(expand.expand_from_seeds(
    [f"seed {i}" for i in range(8)], set(), directions=set()))
check("seed cap reported", any("cap" in u["reason"] for u in many["unresolved"]),
      str(many["unresolved"]))


# ── summary ──────────────────────────────────────────────────────────────────

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
