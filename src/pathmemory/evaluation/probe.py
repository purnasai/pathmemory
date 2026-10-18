"""Real-browser checks that replay fails closed, without any LLM: the destination choice is scripted and the
base agent only stops the episode. Each probe runs against the real Gitea in Chromium with the v2 memory.

  wrong_entity  choice binds owner=a11yproject, repo=design. Dashboard has no such link; memory reroutes via
                Explore, where link "design" leads to primer/design. Replay must notice owner=primer after the
                click and stop, without replaying Issues on the wrong repository.
  ambiguous     a fork byteblaze/design exists (created through the API for this probe only), dashboard repo
                links are hidden. On Explore, "design" now names two different repositories; replay must not
                click either.

    uv run python -m pathmemory.evaluation.probe > docs/evidence/v2/probes.jsonl
"""

import json
from dataclasses import dataclass

import bgym
import requests
from agentlab.agents import dynamic_prompting as dp
from agentlab.agents.agent_args import AgentArgs

from pathmemory.agent import PathMemoryAgent
from pathmemory.config import settings
from pathmemory.evaluation.run import EVAL_WORK_GRAPH, RESULTS, base_agent_args, reset_site, run_task
from pathmemory.graph import GraphMemory
from pathmemory.site.seed import ADMIN
from pathmemory.site.tasks import HIDE_DASHBOARD_REPO_LINKS, register_all


class ScriptedChooser:
    def __init__(self, reply):
        self.reply = reply

    def __call__(self, messages, *a, **kw):
        return {"role": "assistant", "content": self.reply}


class StopBase:
    """Stands in for the LLM after replay hands over: ends the episode at once."""

    def __init__(self):
        flags = base_agent_args().flags
        self.action_set = flags.action.action_set.make_action_set()
        self._pre = dp.make_obs_preprocessor(flags.obs)
        self.reset()

    def reset(self, seed=None):
        self.obs_history, self.actions, self.memories, self.thoughts = [], [], [], []

    def obs_preprocessor(self, obs):
        return self._pre(obs)

    def get_action(self, obs):
        return "send_msg_to_user('probe: replay handed over')", bgym.AgentInfo(think="", chat_messages=[], stats={})


@dataclass
class ProbeAgentArgs(AgentArgs):
    choice: str = ""
    graph_name: str = EVAL_WORK_GRAPH
    mode: str = "graph"
    agent_name: str = "PathMemory-probe"

    def make_agent(self):
        return PathMemoryAgent(StopBase(), "graph", self.graph_name, ScriptedChooser(self.choice))


def _probe(name, task, choice, ui_break=None, setup=None, fixture=None):
    GraphMemory(EVAL_WORK_GRAPH).restore("pathmemory_v2")
    fixture = reset_site(fixture)
    if setup:
        setup()
    r = run_task(
        task,
        ProbeAgentArgs(choice=json.dumps(choice)),
        RESULTS / "v2-probes",
        max_steps=8,
        ui_break=ui_break,
        reset=False,
        fixture=fixture,
    )
    reset_site(fixture)  # leave the fixture clean for whatever runs next
    events = [{k: v for k, v in e.items() if k in ("event", "why", "target", "keys", "at")} for e in r["log"]]
    return {
        "probe": name,
        "task": task,
        "choice": choice,
        "ui_break": bool(ui_break),
        "events": events,
        "replayed_steps": r["replayed_steps"],
        "failed_edge_checks": r["failed_edge_checks"],
        "wrong_target_actions": r["wrong_target_actions"],
        "unsafe_targets_refused": r["unsafe_targets_refused"],
        "exp_dir": r["exp_dir"],
    }


def fork_design():
    r = requests.post(f"{settings.gitea_url}/api/v1/repos/primer/design/forks", auth=ADMIN, json={}, timeout=30)
    assert r.status_code in (201, 202), r.text


def main():
    register_all()
    fixture = reset_site()
    rows = [
        _probe(
            "wrong_entity",
            "issues-5",
            {"target": "/:owner/:repo/issues", "bindings": {"owner": "a11yproject", "repo": "design"}},
            fixture=fixture,
        ),
        _probe(
            "ambiguous",
            "issues-5",
            {"target": "/:owner/:repo/issues", "bindings": {"owner": "primer", "repo": "design"}},
            ui_break=HIDE_DASHBOARD_REPO_LINKS,
            setup=fork_design,
            fixture=fixture,
        ),
    ]
    for r in rows:
        print(json.dumps(r))


if __name__ == "__main__":
    main()
