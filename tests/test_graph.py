"""Clearing scratch memory tolerates absence, but must expose failed operations."""

from unittest.mock import Mock

import pytest

from pathmemory.graph import GraphMemory


def _graph(names):
    graph = GraphMemory.__new__(GraphMemory)
    graph.name = "scratch"
    graph.db, graph.g = Mock(), Mock()
    graph.db.list_graphs.return_value = names
    return graph


def test_clear_does_nothing_for_an_absent_graph():
    graph = _graph([])
    graph.clear()
    graph.g.delete.assert_not_called()


def test_clear_propagates_delete_failures():
    graph = _graph(["scratch"])
    graph.g.delete.side_effect = RuntimeError("server refused deletion")
    with pytest.raises(RuntimeError, match="server refused"):
        graph.clear()


def test_clear_propagates_connection_failures():
    graph = _graph([])
    graph.db.list_graphs.side_effect = ConnectionError("not reachable")
    with pytest.raises(ConnectionError, match="not reachable"):
        graph.clear()
