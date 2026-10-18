"""The v2 composition case, checked from the committed evidence (no infrastructure needed) and, when the
v2 graph is loaded in FalkorDB, against the live Cypher query."""

import json

import pytest

from pathmemory.agent import FlatRoutes
from pathmemory.config import settings
from pathmemory.run import RECOVERY, TEST

V2 = settings.root / "docs/evidence/v2"
COMP = json.loads((V2 / "composition.json").read_text())
MANIFEST = json.loads((V2 / "memory/manifest.json").read_text())
FLAT = FlatRoutes(V2 / "memory/flat_memory.json")


def test_composed_route_is_absent_from_every_individual_training_episode():
    eids = COMP["composed_route"]["eids"]
    assert len(FLAT.store) == sum(e["success"] for e in MANIFEST["episodes"])  # every ingested episode checked
    for t in FLAT.store:
        seq = [e["eid"] for e in t["nav"]]
        assert not any(seq[i:i + len(eids)] == eids for i in range(len(seq))), t["episode"]
        assert not set(eids) <= set(seq), t["episode"]


def test_route_needs_at_least_two_episodes_and_every_hop_has_a_training_source():
    hops = COMP["composed_route"]["sources_per_hop"]
    assert all(hops) and len(COMP["composed_route"]["essential_episodes"]) >= 2
    trained = {e["episode"] for e in MANIFEST["episodes"] if e["success"]}
    assert {x for h in hops for x in h} <= trained
    # each hop's claimed source really contains that step in its own trajectory
    nav = {t["episode"]: {e["eid"] for e in t["nav"]} for t in FLAT.store}
    for eid, srcs in zip(COMP["composed_route"]["eids"], hops):
        assert all(eid in nav[s] for s in srcs)


def test_flat_replay_cannot_produce_the_route_but_finds_the_single_episode_one():
    dash = COMP["broken_ui"]["banned"]
    assert FLAT.routes("/", "/:owner/:repo/issues/new", banned=dash) == []
    [normal] = FLAT.routes("/", "/:owner/:repo/issues/new")
    assert normal["keys"] == COMP["normal_ui"]["routes"][0]["keys"]


def test_flat_routes_never_join_two_trajectories(tmp_path):
    store = [{"task_id": "a", "goal": "a", "steps": [], "episode": "A", "worksite": None,
              "nav": [{"eid": "1", "src": "/", "dst": "/x", "role": "link", "name": "X", "scope": "", "pre": []}]},
             {"task_id": "b", "goal": "b", "steps": [], "episode": "B", "worksite": "/y",
              "nav": [{"eid": "2", "src": "/x", "dst": "/y", "role": "link", "name": "Y", "scope": "", "pre": []}]}]
    p = tmp_path / "flat.json"
    p.write_text(json.dumps(store))
    f = FlatRoutes(p)
    assert f.routes("/", "/y") == [] and f.routes("/x", "/y")[0]["edges"][0]["sources"] == ["B"]
    assert {d["key"] for d in f.destinations()} == {"/", "/x", "/y"}


def test_no_held_out_task_in_training_memory():
    held_out = set(TEST) | set(RECOVERY)
    assert not {e["task"] for e in MANIFEST["episodes"]} & held_out
    assert set(MANIFEST["forbidden_tasks"]) >= held_out
    assert not {t["task_id"] for t in FLAT.store} & held_out
    episodes = {e["episode"] for e in MANIFEST["episodes"]}
    assert all(e["sources"] and set(e["sources"]) <= episodes for e in MANIFEST["edges"])


def test_ablation_removes_the_route():
    assert COMP["ablation"]["bridge_present"] is False and COMP["ablation"]["broken_ui_routes"] == []


@pytest.mark.integration
@pytest.mark.falkordb
def test_live_cypher_matches_committed_evidence():
    from pathmemory.composition import evidence
    from pathmemory.graph import GraphMemory
    if "pathmemory_v2" not in GraphMemory("pathmemory_v2").db.list_graphs():
        pytest.skip("BLOCKED: v2 graph not loaded (run build-memory)")
    live = evidence()
    assert live["graph_fingerprint"] == MANIFEST["fingerprint"] == COMP["graph_fingerprint"]
    assert live["composed_route"] == COMP["composed_route"] and live["no_single_episode_contains_route"]


@pytest.mark.skipif(not (settings.root / "results/v1/eval").exists(), reason="saved runs not available")
@pytest.mark.integration
@pytest.mark.falkordb
def test_build_memory_refuses_held_out_and_redefined_episodes():
    from pathmemory.graph import GraphMemory
    from pathmemory.learn import build_memory
    g = GraphMemory("pm_test_build")
    test_run = next((settings.root / "results/v1/eval").glob("*members-2_0"))
    with pytest.raises(ValueError, match="held-out"):
        build_memory([test_run], g, settings.root / "results/pm_test_flat.json", set(TEST))
    old = next((settings.root / "results/v2-train").glob("*17-54-30*explore-3_0"), None)
    if old:  # first explore-3 attempt ran the earlier wording of the task
        with pytest.raises(ValueError, match="current definition"):
            build_memory([old], g, settings.root / "results/pm_test_flat.json", set(TEST))
    g.clear()


def test_flat_prompt_context_audit():
    """What flat mode's top-3 retrieval gives for issues-2, and that pinning gives exactly the named trajectories."""
    from pathmemory.agent import flat_context
    from pathmemory.site.tasks import TASKS_BY_ID
    store = V2 / "memory/flat_memory.json"
    goal = TASKS_BY_ID["issues-2"].goal + " When you are done, send me a short message (include the answer if I asked a question)."
    top = [t["task_id"] for t in flat_context(goal, store_path=store)]  # the goal text the agent ranks with
    assert top == ["repos-1", "issues-3", "explore-2"]  # neither explore-3 nor issues-1: see FAIR_COMPARISON.md
    pinned = [t["task_id"] for t in flat_context("x", store_path=store, only=["explore-1", "explore-3", "issues-1"])]
    assert pinned == ["explore-1", "explore-3", "issues-1"]


@pytest.mark.integration
@pytest.mark.falkordb
def test_committed_dump_reloads_to_the_manifest_fingerprint():
    from pathmemory.graph import GraphMemory
    g = GraphMemory("pm_test_dump")
    dump = json.loads((V2 / "memory/graph_v2.json").read_text())
    assert g.load_dump(dump) == dump["fingerprint"] == MANIFEST["fingerprint"]
    assert [e["eid"] for e in g.edges()] == [e["eid"] for e in MANIFEST["edges"]]
    g.clear()
