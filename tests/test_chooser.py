"""Malformed destination choices hand control back to the base agent."""

import pytest
from pmfakes import FakeBase, FakeChat, FakeGraph, page

from pathmemory.agent import PathMemoryAgent


@pytest.mark.parametrize(
    "reply",
    [
        "not JSON",
        "[]",
        '{"target": []}',
        '{"target": "/", "bindings": "bad"}',
        '{"target": "/", "bindings": []}',
        '{"target": "/", "bindings": {"repo": ["design"]}}',
        '{"target": "/", "bindings": {"owner": 3}}',
        None,
    ],
)
def test_invalid_chooser_response_falls_back_without_replaying(reply):
    graph = FakeGraph([], ["/"])
    agent = PathMemoryAgent(FakeBase(FakeChat([])), "graph", "unused", FakeChat([reply]), graph=graph)

    action, info = agent.get_action(page("http://x/"))

    assert action == "noop()"
    assert info.extra_info["pathmemory"]["source"] == "llm"
    assert agent.target is None and agent.queue == []
    assert agent.log == [{"event": "invalid_choice"}]
    assert graph.failures == []


def test_null_destination_is_a_valid_choice_to_use_the_base_agent():
    agent = PathMemoryAgent(
        FakeBase(FakeChat([])),
        "graph",
        "unused",
        FakeChat(['{"target": null, "bindings": {}}']),
        graph=FakeGraph([], ["/"]),
    )

    _, info = agent.get_action(page("http://x/"))

    assert info.extra_info["pathmemory"]["source"] == "llm"
    assert agent.log == [{"event": "choose", "target": None, "bindings": {}}]
