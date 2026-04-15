"""Tests for NLQ action schema validation."""

from __future__ import annotations

from pydantic import ValidationError
import pytest


def test_seed_graph_action_validates() -> None:
    from api.nlq.actions import parse_action

    action = parse_action({"type": "seed_graph", "entities": [{"name": "Kraftwerk", "entity_type": "artist"}]})
    assert action.type == "seed_graph"
    assert action.entities[0].name == "Kraftwerk"
    assert action.entities[0].entity_type == "artist"


def test_switch_pane_action_validates() -> None:
    from api.nlq.actions import parse_action

    action = parse_action({"type": "switch_pane", "pane": "trends"})
    assert action.type == "switch_pane"
    assert action.pane == "trends"


def test_switch_pane_rejects_unknown_pane() -> None:
    from api.nlq.actions import parse_action

    with pytest.raises(ValidationError):
        parse_action({"type": "switch_pane", "pane": "not_a_real_pane"})


def test_unknown_action_type_raises() -> None:
    from api.nlq.actions import parse_action

    with pytest.raises(ValidationError):
        parse_action({"type": "time_travel", "year": 1999})


def test_seed_graph_entity_name_length_cap() -> None:
    from api.nlq.actions import parse_action

    with pytest.raises(ValidationError):
        parse_action({"type": "seed_graph", "entities": [{"name": "x" * 257, "entity_type": "artist"}]})


def test_parse_action_list_drops_malformed() -> None:
    from api.nlq.actions import parse_action_list

    raw = [
        {"type": "seed_graph", "entities": [{"name": "Kraftwerk", "entity_type": "artist"}]},
        {"type": "nonsense"},
        {"type": "focus_node", "name": "Kraftwerk", "entity_type": "artist"},
    ]
    actions = parse_action_list(raw)
    assert len(actions) == 2
    assert actions[0].type == "seed_graph"
    assert actions[1].type == "focus_node"
