#!/usr/bin/env python
"""test_verify.py — offline unit tests for the mechanical verification chain.

Covers citation→pool resolution (DOI + title), honeypot detection of
fabricated/dangling citations, verbatim span checking against fetched full
text and the abstract floor, the six-grade verdict vocabulary, the honesty
arithmetic (citation precision / unverifiable rate / grounding) and the
artifacts. No network, no LLM, no model download.

Run:  python tests/test_verify.py        (standalone, no pytest needed)
      python -m pytest tests/test_verify.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from citens.grounding.fulltext import slugify
from citens.grounding.verify import (
    ground_text,
    norm_space,
    parse_claims,
    resolve_reference,
    split_references,
    verify_review,
)
from citens.models import Paper

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))


def _paper(title: str, doi: str | None, abstract: str = "") -> Paper:
    return Paper(title=title, doi=doi, abstract=abstract, authors=["Ada Lovelace"],
                 year=2024, venue="Journal of Tests")


def _review(claims: list[str], refs: list[str]) -> str:
    body = "## Findings\n\n" + "\n\n".join(claims) + "\n\n## References\n\n"
    body += "\n".join(f"[{i}] {r}" for i, r in enumerate(refs, 1))
    return body


FULLTEXT = (
    "We propose a semantic-ID tokenizer for generative recommendation. "
    "The tokenizer maps item text to discrete codes and reduces the vocabulary. "
    "Our experiments on three benchmarks show a 12% recall gain over the baseline."
)
ABSTRACT = (
    "Semantic identifiers improve generative recommendation. "
    "We report a 12% recall gain over the baseline on three benchmarks."
)


def test_references_and_claims() -> None:
    print("\n== reference/claim parsing ==")
    pool = [_paper("Semantic ID Tokenization for Generative Recommendation", "10.1/aaa")]
    body, refs, _ = split_references(_review(["A claim [1]."], ["Lovelace, A. (2024). Semantic ID Tokenization for Generative Recommendation. *J*."]))
    check("references parsed into a number->text map", refs.get(1, "").startswith("Lovelace"))
    check("body excludes the references section", "Lovelace, A." not in body)
    claims = parse_claims(_review(["A claim [1]. Another [2]."], ["x", "y"]))
    check("claims carry their markers", [c["citations"] for c in claims] == [[1], [2]])
    check("claims get stable 1-based ids", [c["id"] for c in claims] == [1, 2])
    check("no heading still yields claims", len(parse_claims("Plain claim [1].")) == 1)


def test_resolution() -> None:
    print("\n== reference -> pool resolution ==")
    pool = [
        _paper("Semantic ID Tokenization for Generative Recommendation", "10.1234/abc"),
        _paper("A Completely Different Study of Order Flow Imbalance", "10.9999/zzz"),
    ]
    by_doi = resolve_reference("Lovelace, A. (2024). Some title. https://doi.org/10.1234/ABC", pool)
    check("DOI match is case/URL-insensitive", by_doi["how"] == "doi" and by_doi["index"] == 0)
    by_title = resolve_reference(
        "Lovelace, A. (2024). Semantic ID tokenization for generative recommendation. J.", pool
    )
    check("title fallback matches the full title", by_title["how"] == "title" and by_title["index"] == 0)
    missing = resolve_reference("Smith (2024). Nothing to do with the pool.", pool)
    check("unrelated reference does not resolve", missing["index"] is None)


def test_honeypot_and_artifacts() -> None:
    print("\n== honeypot: fabricated / dangling citations ==")
    pool = [_paper("Semantic ID Tokenization for Generative Recommendation", "10.1/aaa")]
    review = _review(
        ["Supported claim [1].", "Fabricated claim [2].", "Dangling claim [9]."],
        [
            "Lovelace, A. (2024). Semantic ID Tokenization for Generative Recommendation.",
            "Ghost, B. (2023). A Paper That Does Not Exist.",
        ],
    )
    with tempfile.TemporaryDirectory() as td:
        res = verify_review(review, pool, review_path="review.md", out_dir=td)
        check("review is parsed", res["ok"] and res["claims"] == 3)
        check("fabricated reference flagged as not in pool",
              res["citations"]["not_in_pool"] == [2], str(res["citations"]["not_in_pool"]))
        check("dangling marker flagged", res["citations"]["markers_without_reference"] == [9])
        check("clean=false on a fabricated citation", res["clean"] is False)
        check("artifacts written",
              Path(res["artifacts"]["verification_jsonl"]).is_file()
              and json.loads(Path(res["artifacts"]["honesty_json"]).read_text())["refs_total"] == 2)


def test_span_checks() -> None:
    print("\n== verbatim span grounding ==")
    pool = [_paper("Semantic ID Tokenization for Generative Recommendation", "10.1/aaa", ABSTRACT)]
    with tempfile.TemporaryDirectory() as td:
        good = _review(
            ["The tokenizer maps item text to discrete codes [1]."],
            ["Lovelace, A. (2024). Semantic ID Tokenization for Generative Recommendation."],
        )
        verdicts = [{"claim": "The tokenizer maps item text to discrete codes [1].",
                     "verdict": "supported",
                     "span": "The tokenizer maps item text to discrete codes"}]
        # abstract-only: the span is NOT in the abstract -> mismatch
        res = verify_review(good, pool, verdicts=verdicts, text_dir=td)
        check("span missing from abstract is a mismatch", res["checks"]["span_mismatch"] == 1)
        check("span mismatch is reported in problems",
              any("not found" in p for p in res["checks"]["problems"]))

        # full text floor makes it pass
        ft = Path(td) / f"{slugify(pool[0].title)[:80]}.txt"
        ft.write_text(FULLTEXT, encoding="utf-8")
        text, is_full = ground_text(pool[0], Path(td))
        check("full-text file is found and preferred", is_full and "discrete codes" in text)
        res2 = verify_review(good, pool, verdicts=verdicts, text_dir=td)
        check("verbatim span in full text passes", res2["checks"]["span_ok"] == 1
              and res2["clean"] is True, json.dumps(res2["checks"], ensure_ascii=False)[:300])
        check("grounding counts the fetched full text",
              res2["honesty"]["with_fulltext"] == 1 and res2["honesty"]["grounding"] == 1.0)


def test_verdict_vocabulary_and_honesty() -> None:
    print("\n== verdicts + honesty arithmetic ==")
    pool = [
        _paper("Semantic ID Tokenization for Generative Recommendation", "10.1234/aaa", FULLTEXT),
        _paper("A Second Study", "10.1234/bbb", ABSTRACT),
    ]
    review = _review(
        [
            "Claim one [1].", "Claim two [2].", "Claim three [1].", "Claim four [2].",
        ],
        [
            "Lovelace, A. (2024). Semantic ID Tokenization for Generative Recommendation.",
            "Lovelace, A. (2024). A Second Study. https://doi.org/10.1234/bbb",
        ],
    )
    verdicts = [
        {"claim": "Claim one [1].", "verdict": "supported", "span": "The tokenizer maps item text to discrete codes"},
        {"claim": "Claim two [2].", "verdict": "partial", "span": "a 12% recall gain"},
        {"claim": "Claim three [1].", "verdict": "unsupported", "span": "does not appear in the source"},
        {"claim": "Claim four [2].", "verdict": "unverifiable", "span": "no ground text"},
    ]
    res = verify_review(review, pool, verdicts=verdicts, text_dir=Path("."))
    h = res["honesty"]
    check("all four verdicts match by claim text", h["verdicts_matched"] == 4, str(h))
    check("six-grade counts are kept", h["verdicts"] == {"partial": 1, "supported": 1,
                                                         "unsupported": 1, "unverifiable": 1})
    check("precision = (supported+partial)/verifiable", h["citation_precision"] == 0.667, str(h))
    check("unverifiable rate over all claims", h["unverifiable_rate"] == 0.25, str(h))
    check("invalid verdict is caught",
          verify_review(review, pool, verdicts=[{"claim": "Claim one [1].", "verdict": "great",
                                                  "span": "x"}], text_dir=Path("."))
          ["checks"]["invalid_verdicts"] == 1)
    check("unverifiable with ground text is a problem",
          verify_review(review, pool, verdicts=[{"claim": "Claim one [1].", "verdict": "unverifiable",
                                                  "span": "x"}], text_dir=Path("."))
          ["honesty"]["unverifiable_with_text"] == 1)
    check("missing verdicts are counted",
          verify_review(review, pool, verdicts=verdicts[:2], text_dir=Path("."))
          ["honesty"]["claims_without_verdict"] == 2)
    check("unmatched verdict text is reported",
          verify_review(review, pool, verdicts=verdicts + [{"claim": "Ghost claim [1].",
                                                             "verdict": "supported", "span": "x"}],
                        text_dir=Path("."))["verdicts"]["unmatched"])


def test_normalization() -> None:
    print("\n== normalization ==")
    check("whitespace/case collapsed", norm_space("  The   TOKENIZER\nmaps ") == "the tokenizer maps")


def main() -> int:
    test_references_and_claims()
    test_resolution()
    test_honeypot_and_artifacts()
    test_span_checks()
    test_verdict_vocabulary_and_honesty()
    test_normalization()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
