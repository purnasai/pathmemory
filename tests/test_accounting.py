"""Per-run model usage: chooser and base calls are counted, tokens are not counted twice."""

from types import SimpleNamespace

from agentlab.experiments.loop import _aggregate_episode_stats
from pmfakes import FakeBase, FakeChat, FakeGraph, page

from pathmemory.agent import PathMemoryAgent
from pathmemory.evaluation.run import usage

HOME = "http://x/"
REPO = "http://x/primer/design"
CHOICE = '{"target": "/:owner/:repo", "bindings": {"owner": "primer", "repo": "design"}}'


def _agent(calls_per_step=1):
    graph = FakeGraph([("/", "/:owner/:repo", "link", "{owner}/{repo}", "main", [], "e1")], ["/:owner/:repo"])
    chooser = FakeChat([CHOICE], input_tokens=1400, output_tokens=120)
    base = FakeBase(FakeChat([], input_tokens=3000, output_tokens=50), calls_per_step)
    return PathMemoryAgent(base, "graph", "unused", chooser, graph=graph)


def _summary(stats_per_step):
    """What AgentLab writes to summary_info.json for these step stats."""
    agg = _aggregate_episode_stats([SimpleNamespace(stats=s) for s in stats_per_step])
    return {f"stats.{k}": v for k, v in agg.items()}


def test_chooser_and_base_calls_are_counted_without_double_counting_tokens():
    agent = _agent(calls_per_step=2)  # the base agent needed one parse retry on its step
    home = page(HOME, [("10", "link", "primer/design", "main", True, "/primer/design")])
    a0, i0 = agent.get_action(home)
    assert a0 == "click('10')" and i0.extra_info["pathmemory"]["source"] == "graph"
    # step 0: the replayed click; the only model call was the chooser, and AgentLab's total equals it
    assert i0.stats["pm_chooser_calls"] == 1 and i0.stats["pm_base_calls"] == 0
    assert i0.stats["input_tokens"] == i0.stats["pm_chooser_input_tokens"] == 1400
    assert i0.stats["pm_replayed"] == 1

    a1, i1 = agent.get_action(page(REPO))
    assert i1.extra_info["pathmemory"]["source"] == "llm"
    assert i1.stats["pm_chooser_calls"] == 0 and i1.stats["pm_base_calls"] == 2
    assert i1.stats["input_tokens"] == i1.stats["pm_base_input_tokens"] == 6000  # not 6000 + 1400 again

    u = usage(_summary([i0.stats, i1.stats]))
    assert (u["chooser_calls"], u["base_calls"], u["model_calls"]) == (1, 2, 3)
    assert u["input_tokens"] == 7400 and u["output_tokens"] == 220
    assert (u["chooser_input_tokens"], u["base_input_tokens"]) == (1400, 6000)
    assert u["accounting_consistent"]


def test_chooser_in_an_llm_step_is_still_split_out():
    """When nothing can be replayed the chooser and the base call share step 0; the split stays exact."""
    graph = FakeGraph([], ["/:owner/:repo"])
    agent = PathMemoryAgent(
        FakeBase(FakeChat([], 3000, 50)), "graph", "unused", FakeChat([CHOICE], 1400, 120), graph=graph
    )
    _, info = agent.get_action(page(HOME))
    assert info.stats["input_tokens"] == 4400
    assert (info.stats["pm_chooser_input_tokens"], info.stats["pm_base_input_tokens"]) == (1400, 3000)


def test_counts_reset_between_episodes():
    agent = _agent()
    agent.get_action(page(HOME, [("10", "link", "primer/design", "main", True, "/primer/design")]))
    agent.reset()
    agent.mode = "none"
    _, info = agent.get_action(page(HOME))
    assert info.stats["pm_chooser_calls"] == 0 and info.stats["pm_base_calls"] == 1


def test_usage_flags_inconsistent_totals():
    s = _summary(
        [
            {
                "input_tokens": 500,
                "output_tokens": 5,
                "pm_base_calls": 1,
                "pm_base_input_tokens": 400,
                "pm_base_output_tokens": 5,
            }
        ]
    )
    assert usage(s)["accounting_consistent"] is False


def test_replay_metrics_from_event_log():
    from pathmemory.evaluation.run import replay_metrics

    assert replay_metrics([])["route_hops"] == 0  # no-memory runs have no route
    log = [
        {"event": "choose"},
        {"event": "route", "keys": ["/", "/r"], "eids": ["d"], "sources": [["A"]]},
        {"event": "edge_failed", "why": "link '{owner}/{repo}': hidden"},
        {"event": "edge_failed", "why": "link 'X': missing"},
        {"event": "route", "keys": ["/", "/e", "/r"], "eids": ["x", "b"], "sources": [["A", "C"], ["B"]]},
        {"event": "recovered"},
        {"event": "edge_failed", "why": "wrong entity: owner=x (chose y)"},
    ]
    m = replay_metrics(log)
    assert (m["route_hops"], m["source_episodes"], m["recoveries"]) == (2, ["A", "B", "C"], 1)
    assert (m["failed_edge_checks"], m["wrong_target_actions"], m["unsafe_targets_refused"]) == (3, 1, 1)


def test_replay_reached_goal_separates_memory_success_from_llm_fallback():
    from pathmemory.evaluation.compare import replay_reached_goal

    composed = [
        {"event": "route", "keys": ["/", "/r"]},
        {"event": "edge_failed", "why": "x: missing"},
        {"event": "route", "keys": ["/", "/e", "/r"]},
        {"event": "recovered"},
        {"event": "replay"},
        {"event": "replay"},
    ]
    assert replay_reached_goal({"log": composed})
    assert not replay_reached_goal({"log": composed[:-1]})  # stopped one hop short
    assert not replay_reached_goal({"log": composed + [{"event": "edge_failed", "why": "wrong entity: x"}]})
    assert not replay_reached_goal({"log": [{"event": "route", "keys": ["/", "/r"]}, {"event": "no_route"}]})
    assert not replay_reached_goal({"log": []})  # no memory, LLM only
