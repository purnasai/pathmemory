"""PathMemory agent: a wrapper around AgentLab's GenericAgent.

mode="none"  base agent, no memory                                   (baseline A)
mode="flat"  top-3 similar past trajectories put in the prompt (AWM)  (baseline B)
mode="graph" FalkorDB picks a destination + verified route, replays   (PathMemory)
             the navigation clicks without calling the LLM, verifies
             every state, recovers via an alternative route on failure,
             then hands over with what past tasks did on that page.

B and C use the same hint channel (an extra text block in the goal), and in
every mode the LLM performs the actual data-changing actions.
"""

import json
import os
import re
from dataclasses import dataclass, field

import bgym
from agentlab.agents.agent_args import AgentArgs
from agentlab.agents.generic_agent.generic_agent import GenericAgentArgs
from agentlab.llm.llm_utils import Discussion, HumanMessage, SystemMessage
from agentlab.llm.tracking import cost_tracker_decorator

from pathmemory.graph import GraphMemory
from pathmemory.learn import FLAT_STORE
from pathmemory.state import find_target, instantiate, semantic_step, state_of

def write_json(path, data):
    """Atomic write, so a reader polling the file never sees half of it."""
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


STOP = set("a an the to of in on my for and with as is it i me called named into reply number".split())


def _words(text):
    return {w for w in re.findall(r"[a-z0-9.]+", text.lower()) if w not in STOP}


def flat_hint(goal: str, k: int = 3) -> str | None:
    if not FLAT_STORE.exists():
        return None
    store = json.loads(FLAT_STORE.read_text())
    g = _words(goal)
    ranked = sorted(store, key=lambda t: -len(g & _words(t["goal"])) / (len(g | _words(t["goal"])) or 1))[:k]
    if not ranked:
        return None
    blocks = []
    for t in ranked:
        lines = [f"  on {s['url']}: {s['action']}" for s in t["steps"]]
        blocks.append(f"Past task: {t['goal']}\n" + "\n".join(lines))
    return "Successful past trajectories on this website (use them if relevant):\n\n" + "\n\n".join(blocks)


CHOOSER_PROMPT = """You help a web agent reuse memory of a Gitea website.
Goal: {goal}

Current page: {url}
Visible page text (truncated):
{page}

Known pages of this site (route templates), with tasks that were done there before:
{sites}

Pick the page where this goal's work should happen (or where the answer can be read), and the values
for its placeholders (:owner = account or org owning a repo, :repo = repo name,
:org = organisation). Use names exactly as they appear on the site. Reply with
JSON only: {{"target": "<key or null>", "bindings": {{"owner": "...", "repo": "..."}}}}"""


@dataclass
class PathMemoryAgentArgs(AgentArgs):
    base_args: GenericAgentArgs = None
    mode: str = "graph"
    graph_name: str = "pathmemory"
    agent_name: str = field(default=None)
    live_file: str | None = None  # if set, progress is written here after every step (demo UI "Live" tab)

    def __post_init__(self):
        self.agent_name = self.agent_name or f"PathMemory-{self.mode}"

    def make_agent(self):
        return PathMemoryAgent(self.base_args.make_agent(), self.mode, self.graph_name,
                               self.base_args.chat_model_args.make_model(), self.live_file)

    def set_benchmark(self, benchmark, demo_mode):
        self.base_args.set_benchmark(benchmark, demo_mode)

    def set_reproducibility_mode(self):
        self.base_args.set_reproducibility_mode()

    def prepare(self):
        return self.base_args.prepare()

    def close(self):
        return self.base_args.close()


class PathMemoryAgent(bgym.Agent):
    def __init__(self, base, mode, graph_name, chooser_llm, live_file=None):
        self.base, self.mode, self.llm = base, mode, chooser_llm
        self.live_file = live_file
        self.live_steps: list[dict] = []
        self.graph = GraphMemory(graph_name) if mode == "graph" else None
        self.log: list[dict] = []
        self.reset()

    @property
    def action_set(self):
        return self.base.action_set

    def obs_preprocessor(self, obs):
        return self.base.obs_preprocessor(obs)

    def reset(self, seed=None):
        self.base.reset(seed=seed)
        self.started = False
        self.hint = None
        self.queue: list[dict] = []  # pending replay clicks
        self.route = None  # {"keys": [...], "edges": [...]}, plus position
        self.expect = None  # state key expected after the last replayed click
        self.last_eid = None
        self.target, self.bindings = None, {}
        self.banned: list[str] = []
        self.recoveries = 0

    # --- main loop ------------------------------------------------------------
    @cost_tracker_decorator
    def get_action(self, obs):
        action, info = self._act(obs)
        if self.live_file:
            self._write_live(obs, action, info)
        return action, info

    def _write_live(self, obs, action, info):
        st = state_of(obs)
        pm = (info.extra_info or {}).get("pathmemory") or {}
        self.live_steps.append({"n": len(self.live_steps), "url": obs["url"], "page": st.key,
                                "action": semantic_step(action, obs, st.bindings).text() if action else "",
                                "source": pm.get("source", "llm"), "think": info.think or "",
                                "error": obs.get("last_action_error") or ""})
        write_json(self.live_file, {"status": "running", "mode": self.mode, "steps": self.live_steps,
                                    "events": self.log})

    def _act(self, obs):
        if not self.started:
            self.started = True
            if self.mode == "flat":
                self.hint = flat_hint(self._goal(obs))
            elif self.mode == "graph":
                self._plan(obs)
        if self.mode == "graph":
            action = self._replay_step(obs)
            if action:
                return action
        return self._delegate(obs)

    def _delegate(self, obs):
        if self.hint:
            obs = dict(obs)
            obs["goal_object"] = list(obs["goal_object"]) + [{"type": "text", "text": "\n\n" + self.hint}]
        action, info = self.base.get_action(obs)
        info.extra_info = {**(info.extra_info or {}), "pathmemory": {"source": "llm", "mode": self.mode, "log": list(self.log)}}
        return action, info

    # --- graph mode -----------------------------------------------------------
    def _goal(self, obs):
        return " ".join(m.get("text", "") for m in obs["goal_object"] if m.get("type") == "text")

    def _plan(self, obs):
        sites = self.graph.destinations()
        if not sites:
            return
        listing = "\n".join(f"- key={s['key']}  (example page: {s['title']})"
                            + (f"\n    done here: {'; '.join(s['goals'][:3])}" if s["goals"] else "") for s in sites)
        prompt = CHOOSER_PROMPT.format(goal=self._goal(obs), url=obs["url"], sites=listing,
                                       page=obs.get("axtree_txt", "")[:3000])
        msg = self.llm(Discussion([SystemMessage("Reply with JSON only."), HumanMessage(prompt)]))
        try:
            choice = json.loads(re.search(r"\{.*\}", msg["content"], re.S).group(0))
        except (AttributeError, json.JSONDecodeError):
            choice = {}
        self.target = choice.get("target") if choice.get("target") in {s["key"] for s in sites} else None
        self.bindings = {k: v for k, v in (choice.get("bindings") or {}).items() if v}
        self.log.append({"event": "choose", "target": self.target, "bindings": self.bindings})
        if self.target:
            self._route_from(state_of(obs).key)

    def _route_from(self, key) -> bool:
        routes = self.graph.routes(key, self.target, banned=self.banned)
        if not routes:
            self.route, self.queue = None, []
            self.log.append({"event": "no_route", "from": key})
            return False
        self.route = routes[0]
        self.queue = []
        for e, dst in zip(self.route["edges"], self.route["keys"][1:]):
            for pre in e.get("pre") or []:
                role, name, scope = (pre.split("|") + ["", ""])[:3]
                self.queue.append({"role": role, "name": name, "scope": scope, "pre": True, "eid": e["eid"]})
            self.queue.append({"role": e["role"], "name": e["name"], "scope": e.get("scope") or "", "pre": False,
                               "eid": e["eid"], "dst": dst})
        self.log.append({"event": "route", "keys": self.route["keys"]})
        return True

    def _fail(self, key, why):
        """The last replayed edge did not do what memory said: ban it for this run and look for another route."""
        if self.last_eid:
            self.graph.mark_failure(self.last_eid)
            self.banned.append(self.last_eid)
        self.log.append({"event": "edge_failed", "eid": self.last_eid, "at": key, "why": why})
        self.expect, self.last_eid = None, None
        if self.recoveries < 2 and self._route_from(key):
            self.recoveries += 1
            self.log.append({"event": "recovered", "via": self.route["keys"]})
            return True
        self.queue = []
        return False

    def _replay_step(self, obs):
        key = state_of(obs).key
        if self.expect and key != self.expect:
            self._fail(key, f"expected {self.expect}")
        elif self.expect:
            self.expect, self.last_eid = None, None
        while self.queue:
            item = self.queue[0]
            b = {**state_of(obs).bindings, **self.bindings}
            bid = find_target(obs, item["role"], instantiate(item["name"], b), instantiate(item["scope"], b))
            if bid is None:
                if item["pre"]:  # menu may already be open, or not needed here
                    self.queue.pop(0)
                    continue
                self.last_eid = item["eid"]
                if not self._fail(key, f"no {item['role']} '{item['name']}' on page"):
                    break
                continue
            self.queue.pop(0)
            if not item["pre"]:
                self.expect, self.last_eid = item["dst"], item["eid"]
            return self._replayed(obs, f"click('{bid}')", item)
        if self.target and not self.hint:
            self.hint = self._handover_hint(key, obs["url"])
        return None

    def _replayed(self, obs, action, item):
        """Return a replayed action and keep the base agent's history consistent with it."""
        think = f"PathMemory replay: click {item['role']} '{instantiate(item['name'], self.bindings)}'"
        b = self.base
        b.obs_history.append(obs)
        b.actions.append(action)
        b.memories.append(None)
        b.thoughts.append(think)
        self.log.append({"event": "replay", "action": action, "target": item["name"]})
        return action, bgym.AgentInfo(think=think, chat_messages=[], stats={},
                                      extra_info={"pathmemory": {"source": "graph", "mode": self.mode, "log": list(self.log)}})

    def _handover_hint(self, key, url):
        site = next((s for s in self.graph.destinations() if s["key"] == self.target), None)
        if not site:
            return None
        # Anchor to the concrete URL: after the agent acts, it may land on another page with the same template
        # (e.g. a fork at /byteblaze/design vs /primer/design) and must not mistake it for the starting point.
        if key == self.target:
            lines = [f"Memory note: before your first action, PathMemory replayed known navigation to {url} "
                     f"(page type {self.target}), where this kind of goal is usually done. "
                     "Any page you see after that is the result of your own actions, so check whether the goal "
                     "is already complete before repeating anything."]
        else:
            lines = [f"Memory note: PathMemory tried to navigate to a page of type {self.target} but stopped at {url}. "
                     "Continue from here yourself."]
        if site["goals"]:
            lines.append("Similar past tasks done on this page:")
        for goal, steps in zip(site["goals"], site["steps"]):
            lines.append(f"- {goal}" + (f"  -> steps: {'; '.join(steps)}" if steps else ""))
        lines.append("Treat this as guidance: check the current page and complete the goal yourself.")
        return "\n".join(lines)
