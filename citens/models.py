"""Pydantic data models for the whole pipeline.

``ScoredPaper`` enriches ``Paper`` with ranking fields (see citens.ranking).
Grounding models (:class:`Chunk`, :class:`Claim`, :class:`Citation`, …) back
the "verifiable-citations" workflow. Models the engine repo's LLM pipeline
used (ExtractedPaper, themes, synthesis, run metadata) were removed in this
build — the calling agent produces that structure in prose under the skill.
"""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, Field, computed_field, field_validator


def _stable_id(*parts: str) -> str:
    """Deterministic short id from parts (used for paper / chunk identity)."""
    h = hashlib.sha1("\u241F".join(parts).encode("utf-8")).hexdigest()
    return h[:12]


_DOI_URL_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
    "info:doi/",
)


class Paper(BaseModel):
    """Bibliographic metadata for a single paper."""

    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str = ""
    source: str = ""
    citation_count: int = 0
    url: str = ""
    doi: str | None = None
    pdf_url: str | None = None  # open-access full-text PDF, if known
    venue: str = ""  # journal / conference / repository name, when known
    volume: str = ""  # journal volume ("36") — for complete reference entries
    issue: str = ""  # journal issue ("8")
    pages: str = ""  # "4387-4403" (first-last, whichever endpoints are known)
    keywords: list[str] = Field(default_factory=list)  # author/indexer keywords
    subfield: str = ""  # fine-grained field tag (assigned at pool collection)
    # Author-engagement signals (filled by citens collect; 0 = unknown).
    # first_author_works is the author's TOTAL output (merged-author artifact
    # prone); author_field_works counts works matching the TOPIC — the real
    # 深耕此领域 signal, preferred by ranking when present.
    first_author_h_index: int = 0
    first_author_works: int = 0
    author_field_works: int = 0  # in-topic works of first/last author
    # provenance / type flags (filled at collection)
    matched_queries: list[str] = Field(default_factory=list)  # queries that hit this record
    # recall families (agent/raw/oa_title/s2_rec/snowball/web/survey) that
    # surfaced this record — cross-family consensus is a cheap on-topic
    # signal; 2+ independent families beating a single web hit is evidence,
    # not proof (filled by the recall driver; [] on legacy records).
    found_by: list[str] = Field(default_factory=list)
    is_review: bool = False  # indexed as a survey/review (OpenAlex type:review)
    # document-kind tag, stamped over the pool at collection (mechanical, from
    # DOI prefix + venue; "" = unknown). The 学术-vs-政策端 contrast consumes
    # it: journal evidence and a Fed policy note answer the same question with
    # different framings, and a review that cannot tell them apart misreads both.
    doc_type: str = ""  # journal | preprint | working_paper | policy_note | report
    policy_org: str = ""  # issuing institution for policy-corpus records (NBER, Federal Reserve Board, IMF)

    @field_validator("authors", mode="before")
    @classmethod
    def _dedupe_authors(cls, v):
        """Deduplicate author names, order-preserving.

        OpenAlex emits one ``authorships`` entry per (author, affiliation), so a
        single author with three affiliations appears three times — e.g.
        "Bence Toth, Bence Toth, Bence Toth et al." in the rendered references.
        Case-insensitive match on the collapsed name.
        """
        if not v:
            return []
        seen: set[str] = set()
        out: list[str] = []
        for name in v:
            if name is None:
                continue
            s = " ".join(str(name).split())
            key = s.lower()
            if s and key not in seen:
                seen.add(key)
                out.append(s)
        return out

    @field_validator("doi", mode="before")
    @classmethod
    def _normalize_doi(cls, v):
        """Strip URL forms (OpenAlex returns 'https://doi.org/10.x/...') so the
        bare DOI is usable in Unpaywall/Crossref/BibTeX everywhere downstream."""
        if not v:
            return v
        s = str(v).strip()
        low = s.lower()
        for p in _DOI_URL_PREFIXES:
            if low.startswith(p):
                s = s[len(p):]
                break
        return s or None

    @computed_field  # type: ignore[misc]
    @property
    def id(self) -> str:
        return _stable_id(self.doi or "", self.title.lower().strip())

    def brief(self) -> str:
        authors = ", ".join(self.authors[:5])
        if len(self.authors) > 5:
            authors += " et al."
        return (
            f"标题: {self.title}\n"
            f"作者: {authors}\n"
            f"年份: {self.year} | 来源: {self.source} | 引用: {self.citation_count}\n"
            f"摘要: {self.abstract[:300]}..."
        )


class ScoredPaper(Paper):
    """A paper with a relevance score and filtering rationale."""

    relevance_score: int = 0
    filter_reason: str = ""
    venue_quartile: str = ""  # SJR quartile of the venue ("" if unknown)
    rank_score: float = 0.0  # composite retrieval score (see citens.ranking)

    def brief(self) -> str:
        return (
            f"评分: {self.relevance_score}/5 | 理由: {self.filter_reason}\n"
            f"{super().brief()}"
        )


# --- Citation grounding ------------------------------------------------------


class ChunkKind(str, Enum):
    ABSTRACT = "abstract"
    SECTION = "section"
    FULLTEXT = "fulltext"


class Chunk(BaseModel):
    """A unit of source text that a claim can be grounded against."""

    paper_id: str
    chunk_id: str
    text: str
    kind: ChunkKind = ChunkKind.ABSTRACT


class Citation(BaseModel):
    """A reference-table entry rendering as ``[n]`` in the review."""

    index: int
    paper_id: str
    label: str  # human-readable reference string

    @property
    def marker(self) -> str:
        return f"[{self.index}]"


class Claim(BaseModel):
    """A single assertion in the review, tied to one or more citations."""

    text: str
    citation_indices: list[int] = Field(default_factory=list)
    section: str = ""
    intent: str = ""  # what this claim is trying to prove (the review's declared intent)


class Verdict(str, Enum):
    """Five-grade support scale (nature-citation style).

    "background" and "contradictory" split what used to collapse into
    "unsupported": a context-only citation is a *ranking/citation-choice*
    defect (the claim overreaches its evidence), while a contradiction is
    *content* the review must acknowledge, not paper over. Both stay out of
    the precision numerator; the rewriter handles each differently.
    """

    SUPPORTED = "supported"
    PARTIAL = "partial"
    BACKGROUND = "background"  # source backs field context only, not the claim
    CONTRADICTORY = "contradictory"  # source conflicts with / narrows the claim
    UNSUPPORTED = "unsupported"
    UNVERIFIABLE = "unverifiable"  # cited source has no ground text (e.g. no abstract)
