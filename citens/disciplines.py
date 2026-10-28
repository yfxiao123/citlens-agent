"""Discipline layers — domain-specific writing/evidence disciplines, detected
mechanically and surfaced with the search result.

Why this module exists: rules like separate-statistical-from-economic-
significance are ECONOMICS disciplines, not literature-search mechanics.
Baking one field's rules into the general skill pollutes it (and the next
field would too). The design: each discipline is a layer — a lexicon that
detects it from the topic/queries text plus a short pointer stating its core
rules — and the recall driver stamps the matched layer into the report and
the search result. The FULL layer lives beside the skill
(skill/citlens/disciplines/<name>.md); the pointer here is the compressed
form that travels with the result, so even a client that never read the
skill receives the discipline's core rules.

Detection is lexical and deterministic (zero LLM): a discipline fires when
one of its terms appears in the topic, the agent queries, or the policy
queries. The driver adds a second, structural trigger: policy-corpus records
surviving in the pool imply the economics layer regardless of vocabulary.
"""

from __future__ import annotations

DISCIPLINES: dict[str, dict] = {
    "economics": {
        # terms are matched as lowercase substrings over the combined text;
        # entries must be unambiguous enough to stay silent on, say, an ML
        # topic ("memory bank" must NOT fire — hence no bare "bank")
        "terms": [
            "monetary policy", "inflation", "interest rate", "natural rate",
            "r-star", "federal reserve", "central bank", "fiscal policy",
            "monetary", "unemployment", "gdp", "exchange rate", "tariff",
            "trade war", "labor market", "wage", "recession",
            "economic growth", "deficit", "productivity growth",
            "货币政策", "通胀", "通货膨胀", "利率", "央行", "美联储",
            "财政", "失业率", "汇率", "经济增长", "关税",
        ],
        "pointer": (
            "经济学层已启用：区分统计显著与经济显著——给出效应量级、参照基准"
            "与对应的政策取舍含义，显著但量级微小的效应是政策非事件；政策笔记"
            "（FEDS Notes 等）明说的数据缺口与未解问题是「找」的直接证据；"
            "近一两年的 NBER 工作论文即前沿，开创性工作用前向引文（expand）"
            "追踪；「定」须陈述现实利害。完整层见 skill: disciplines/economics.md"
        ),
    },
}


def detect_discipline(texts: list[str]) -> dict | None:
    """The first discipline whose lexicon matches the given texts.

    Returns {"name", "matched": [terms]} or None. Order of iteration is the
    registry order, so with multiple layers the first hit wins — good enough:
    the hint activates guidance, it never gates retrieval.
    """
    blob = " ".join(t for t in texts if t).lower()
    if not blob.strip():
        return None
    for name, meta in DISCIPLINES.items():
        matched = [t for t in meta["terms"] if t in blob]
        if matched:
            return {"name": name, "matched": matched[:6]}
    return None
