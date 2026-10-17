"""Retrieval evaluation primitives (LLM-free build).

``citens.eval.litsearch`` holds the per-source cell searchers, RRF fusion
and the OpenAlex title-index channel — the measured retrieval half of the
engine's LitSearch bench. The bench harness itself (gold matching, run
loop, LLM legs) lives in the CiteLens engine repo.
"""
