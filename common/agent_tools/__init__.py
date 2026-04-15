"""Shared agent tool registry.

Pure async data-fetching functions shared between the NLQ engine and the
MCP server. No framework coupling — just typed params in, typed dicts out.
"""

from __future__ import annotations

from common.agent_tools.graph import find_path


__all__ = ["find_path"]
