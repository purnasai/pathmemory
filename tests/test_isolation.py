"""Evaluation memory is frozen: in-run bans still reroute, but nothing is written unless live learning
asks for it; every trial starts from the same snapshot; the Gitea fixture is reset to the same state."""

import json

import pytest
import requests

from pathmemory.agent import PathMemoryAgent
from pathmemory.graph import GraphMemory, edge_id
from pathmemory.state import State, Step
from pmfakes import FakeBase, FakeChat, FakeGraph, page

HOME, REPO, EXPLORE = State("/", "/"), State("/:owner/:repo", "/:owner/:repo"), State("/explore/repos", "/explore/repos")
CHOICE = json.dumps({"target": "/:owner/:repo", "bindings": {"owner": "primer", "repo": "design"}})
EDGES = [("/", "/:owner/:repo", "link", "{owner}/{repo}", "main", [], "e-dash"),
         ("/", "/explore/repos", "link", "Explore", "", [], "e-explore"),
         ("/explore/repos", "/:owner/:repo", "link", "{repo}", "main", [], "e-list")]
BROKEN_HOME = page("http://x/", [("7", "link", "Explore", "", True, "/explore/repos")])  # dashboard links hidden


def _run(graph, record_failures):
    agent = PathMemoryAgent(FakeBase(FakeChat([])), "graph", "unused", FakeChat([CHOICE]),
                            record_failures=record_failures, graph=graph)
    action, _ = agent.get_action(BROKEN_HOME)
    return agent, action


def test_eval_bans_and_reroutes_without_writing():
    g = FakeGraph(EDGES, ["/:owner/:repo"])
    agent, action = _run(g, record_failures=False)
    assert action == "click('7')" and agent.banned == ["e-dash"]   # rerouted via Explore within the run
    assert g.failures == []                                          # memory untouched
    assert agent.log[1]["event"] == "route" and not [e for e in agent.log if e.get("recorded")]


def test_live_learning_records_the_failure():
    g = FakeGraph(EDGES, ["/:owner/:repo"])
    agent, _ = _run(g, record_failures=True)
    assert g.failures == ["e-dash"]


def test_agent_args_default_to_not_recording():
    from pathmemory.agent import PathMemoryAgentArgs
    assert PathMemoryAgentArgs(mode="graph").record_failures is False


# --- FalkorDB ----------------------------------------------------------------------------------------
SNAP, WORK = "pm_test_iso_snapshot", "pm_test_iso_work"


def _snapshot():
    for n in (SNAP, WORK):
        GraphMemory(n).clear()
    g = GraphMemory(SNAP)
    g.record_transition(HOME, Step("click", "link", "{owner}/{repo}", scope="main"), REPO)
    g.record_transition(HOME, Step("click", "link", "Explore"), EXPLORE)
    g.record_transition(EXPLORE, Step("click", "link", "{repo}", scope="main"), REPO)
    return g


@pytest.mark.integration
@pytest.mark.falkordb
def test_each_trial_starts_from_the_same_snapshot_and_eval_leaves_it_unchanged():
    snap = _snapshot()
    fp = snap.fingerprint()
    work = GraphMemory(WORK)
    seen = []
    for record in (False, False, True):        # two evaluation trials, then one live-learning run
        work.restore(SNAP)
        seen.append(work.fingerprint())
        _run(work, record_failures=record)
        seen.append(work.fingerprint())
    assert seen[0] == seen[1] == seen[2] == seen[3] == seen[4] == fp   # eval trials wrote nothing
    assert seen[5] != fp                                                 # live learning did write
    assert snap.fingerprint() == fp                                      # snapshot itself never touched
    work.restore(SNAP)
    assert work.fingerprint() == fp                                      # and the next trial is clean again
    for n in (SNAP, WORK):
        GraphMemory(n).clear()


@pytest.mark.integration
@pytest.mark.falkordb
def test_v1_edge_ids_migrate_to_scoped_ids():
    g = _snapshot()
    step = Step("click", "link", "{owner}/{repo}", scope="main")
    legacy = "legacy00000a"
    g.q("MATCH ()-[r:ACT {eid:$e}]->() SET r.eid=$l", e=edge_id("/", step, "/:owner/:repo"), l=legacy)
    assert g.migrate_edge_ids() == 1
    assert g.q("MATCH ()-[r:ACT {eid:$e}]->() RETURN count(r)", e=edge_id("/", step, "/:owner/:repo"))[0][0] == 1
    assert g.migrate_edge_ids() == 0
    GraphMemory(SNAP).clear()


# --- Gitea -------------------------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.gitea
def test_reset_removes_earlier_task_effects():
    from pathmemory.config import settings
    from pathmemory.run import reset_site
    from pathmemory.site.seed import ADMIN, fingerprint

    clean = reset_site()
    r = requests.put(f"{settings.gitea_url}/api/v1/user/starred/primer/design", auth=ADMIN, timeout=10)
    assert r.status_code == 204 and fingerprint() != clean          # an earlier task starred a repo
    assert reset_site(expected=clean) == clean                       # the next trial sees the fixture again
