"""Live learning: the diff shown in the demo UI, and backup/restore of the experiments' memory (needs FalkorDB)."""

from pathmemory.graph import GraphMemory
from pathmemory.learn import memory_diff
from pathmemory.state import State, Step

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.falkordb]

GRAPH, COPY = "pm_test_live", "pm_test_live_backup"
HOME, REPO, EXPLORE = State("/", "/"), State("/:owner/:repo", "/:owner/:repo"), State("/explore/repos", "/explore/repos")


def _fresh():
    for name in (GRAPH, COPY):
        GraphMemory(name).clear()
    g = GraphMemory(GRAPH)
    dash = g.record_transition(HOME, Step("click", "link", "{owner}/{repo}"), REPO)
    g.record_transition(HOME, Step("click", "link", "Explore"), EXPLORE)
    return g, dash


def test_diff_reports_new_reinforced_and_failed_steps():
    g, dash = _fresh()
    before = g.snapshot()
    g.mark_failure(dash)                                                          # replay hit the broken dashboard link
    g.record_transition(HOME, Step("click", "link", "Explore"), EXPLORE)          # known step used again
    new = g.record_transition(EXPLORE, Step("click", "link", "{repo}"), REPO)     # the detour, learned live
    g.record_worksite("members-4", "add a collaborator", "members", REPO, ["click Settings"])
    d = memory_diff(before, g.snapshot())

    assert [e["eid"] for e in d["new_steps"]] == [new] and d["new_steps"][0]["name"] == "{repo}"
    assert [(e["name"], e["by"], e["successes"]) for e in d["reinforced"]] == [("Explore", 1, 2)]
    assert [(e["eid"], e["by"]) for e in d["failures"]] == [(dash, 1)]
    assert d["new_pages"] == [] and d["new_tasks"] == ["members-4"]
    # the learned detour is immediately usable as a route around the failed step
    assert [e["name"] for e in g.routes("/", "/:owner/:repo", banned=[dash])[0]["edges"]] == ["Explore", "{repo}"]


def test_backup_is_taken_once_and_restore_undoes_live_writes():
    g, _ = _fresh()
    assert g.backup(COPY) is True
    g.record_transition(EXPLORE, Step("click", "link", "{repo}"), REPO)
    assert g.backup(COPY) is False          # a later backup must not overwrite the original copy
    assert g.stats()["edges"] == 3
    g.restore(COPY)
    assert g.stats() == {"states": 3, "edges": 2, "tasks": 0}
    for name in (GRAPH, COPY):
        GraphMemory(name).clear()
