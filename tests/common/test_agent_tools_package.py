"""Tests that the agent_tools package and its top-level exports load."""

from __future__ import annotations


def test_package_imports_cleanly() -> None:
    import common.agent_tools as at

    assert hasattr(at, "__all__")


def test_schemas_module_imports() -> None:
    from common.agent_tools import schemas

    assert schemas is not None
