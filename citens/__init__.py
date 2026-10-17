"""CiteLens-agent: the LLM-free retrieval core (agent-driven)."""

from __future__ import annotations

try:  # installed package metadata tracks pyproject (the release version)
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("citlens-agent")
except PackageNotFoundError:  # frozen/source-tree fallback
    __version__ = "0.1.0"

__all__ = ["__version__"]
