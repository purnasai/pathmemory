"""PathMemory agent: a wrapper around AgentLab's GenericAgent.

mode="none"  base agent, no memory                                   (baseline A)
mode="flat"  top-3 similar past trajectories put in the prompt (AWM)  (baseline B)
mode="flatreplay"  same chooser, matcher, verification and fallback as graph mode, but  (baseline C)
             a route is a contiguous stretch of ONE stored trajectory: no
             composition of steps learned in different episodes.
mode="graph" FalkorDB picks a destination + verified route, replays   (PathMemory)
             the navigation clicks without calling the LLM, verifies
             every state, recovers via an alternative route on failure,
             then hands over with what past tasks did on that page.

Flat retrieval policy (mode "flat"): rank stored successful trajectories by Jaccard similarity of goal words
(stop words removed), take the top k=3, and give each one's goal plus every step ("on <url>: <action>").

flat, flatreplay and graph use the same hint channel (an extra text block in the goal), and in
every mode the LLM performs the actual data-changing actions.
"""

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import bgym
from agentlab.agents.agent_args import AgentArgs
from agentlab.agents.generic_agent.generic_agent import GenericAgentArgs
from agentlab.llm.llm_utils import Discussion, HumanMessage, SystemMessage
from agentlab.llm.tracking import cost_tracker_decorator, set_tracker

from pathmemory.graph import GraphMemory
from pathmemory.learn import FLAT_STORE
from pathmemory.state import Match, find_target, hrefs, instantiate, semantic_step, state_of

# Entity bindings a replayed navigation step must preserve (route templates alone cannot tell
# /primer/design from the fork /byteblaze/design).
CHECKED_BINDINGS = ("owner", "repo", "org", "n")
USAGE_ROLES = ("chooser", "base")
REPLAY_MODES = ("graph", "flatreplay")

def write_json(path, data):
    """Atomic write, so a reader polling the file never sees half of it."""
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


STOP = set("a an the to of in on my for and with as is it i me called named into reply number".split())


def _words(text):
    return {w for w in re.findall(r"[a-z0-9.]+", text.lower()) if w not in STOP}


def flat_hint(goal: str, k: int = 3, store_path=FLAT_STORE) -> str | None:
    store_path = Path(store_path)
    if not store_path.exists():
        return None
    store = json.loads(store_path.read_text())
    g = _words(goal)
    ranked = sorted(store, key=lambda t: -len(g & _words(t["goal"])) / (len(g | _words(t["goal"])) or 1))[:k]
    if not ranked:
        return None
    blocks = []
    for t in ranked:
        lines = [f"  on {s['url']}: {s['action']}" for s in t["steps"]]
        blocks.append(f"Past task: {t['goal']}\n" + "\n".join(lines))
    return "Successful past trajectories on this website (use them if relevant):\n\n" + "\n\n".join(blocks)


class FlatRoutes:
    """Flat-replay memory over the stored trajectories, with GraphMemory's read interface.

    destinations(): every page seen in a stored trajectory, with the goals of tasks whose work happened there
    (what GraphMemory.destinations() lists when built from the same episodes). routes(): contiguous runs of
    navigation steps inside a single trajectory, shortest first; never joins steps of two trajectories.
    """

    def __init__(self, store_path):
        p = Path(store_path)
        self.store = [t for t in (json.loads(p.read_text()) if p.exists() else []) if t.get("nav") is not None]

    def destinations(self) -> list[dict]:
        pages = {}
        for t in self.store:
            for e in t["nav"]:
                pages.setdefault(e["src"], {"goals": [], "steps": []})
                pages.setdefault(e["dst"], {"goals": [], "steps": []})
            if t.get("worksite"):
                site = pages.setdefault(t["worksite"], {"goals": [], "steps": []})
                site["goals"].append(t["goal"])
                site["steps"].append(t.get("work_steps") or [])
        return [{"key": k, "title": k, **v} for k, v in sorted(pages.items())]

    def routes(self, src, dst, banned=(), k=3, max_hops=6):
        if src == dst:
            return [{"keys": [src], "edges": []}]
        found = {}
        for t in self.store:
            nav = t["nav"]
            for i, first in enumerate(nav):
                if first["src"] != src:
                    continue
                for j in range(i, min(len(nav), i + max_hops)):
                    if j > i and nav[j]["src"] != nav[j - 1]["dst"]:
                        break  # the trajectory left the chain (e.g. a form submit moved the page)
                    seg = nav[i:j + 1]
                    if any(e["eid"] in banned for e in seg):
                        break
                    if nav[j]["dst"] == dst:
                        keys = [src] + [e["dst"] for e in seg]
                        edges = [{"eid": e["eid"], "kind": "click", "role": e["role"], "name": e["name"],
                                  "pre": e["pre"], "scope": e["scope"], "sources": [t["episode"]]} for e in seg]
                        found.setdefault(tuple(e["eid"] for e in seg), {"keys": keys, "edges": edges})
                        break
        return sorted(found.values(), key=lambda r: len(r["edges"]))[:k]

    def mark_failure(self, eid):
        raise RuntimeError("flat replay memory is read-only")


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
    # Off for evaluation: a failed replay step is banned for this run only. Live learning turns it on so
    # the failure is also written to memory.
    record_failures: bool = False
    flat_store: str | None = None  # flat-baseline trace file; default learn.FLAT_STORE

    def __post_init__(self):
        self.agent_name = self.agent_name or f"PathMemory-{self.mode}"

    def make_agent(self):
        return PathMemoryAgent(self.base_args.make_agent(), self.mode, self.graph_name,
                               self.base_args.chat_model_args.make_model(), self.live_file,
                               record_failures=self.record_failures, flat_store=self.flat_store)

    def set_benchmark(self, benchmark, demo_mode):
        self.base_args.set_benchmark(benchmark, demo_mode)

    def set_reproducibility_mode(self):
        self.base_args.set_reproducibility_mode()

    def prepare(self):
        return self.base_args.prepare()

    def close(self):
        return self.base_args.close()


class CountingLLM:
    """Wraps a chat model to count its completions and their tokens under one role ("chooser" or "base").

    The call runs under a nested AgentLab tracker, which adds its totals to the enclosing tracker on exit,
    so the episode totals AgentLab already records are unchanged (no double counting): the counts here are
    a breakdown of them. API attempts that raised are not completions and add no tokens.
    """

    def __init__(self, inner, usage: dict, role: str):
        self.inner, self.usage, self.role = inner, usage, role

    def __call__(self, *args, **kwargs):
        with set_tracker() as t:
            out = self.inner(*args, **kwargs)
        u = self.usage[self.role]
        u["calls"] += 1
        u["api_attempts"] += getattr(self.inner, "retries", 1) or 1
        u["input_tokens"] += t.input_tokens
        u["output_tokens"] += t.output_tokens
        return out

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _usage():
    return defaultdict(lambda: defaultdict(int))


def _transient(err: str) -> bool:
    """Playwright gave up because the element was moving or covered, not because it was missing."""
    return "Timeout" in err and ("not stable" in err or "intercepts pointer events" in err)


class PathMemoryAgent(bgym.Agent):
    def __init__(self, base, mode, graph_name, chooser_llm, live_file=None, record_failures=False, flat_store=None,
                 graph=None):
        self.usage = _usage()  # per-episode model usage by role, see CountingLLM
        self.base, self.mode = base, mode
        self.llm = CountingLLM(chooser_llm, self.usage, "chooser")
        if hasattr(base, "chat_llm"):
            base.chat_llm = CountingLLM(base.chat_llm, self.usage, "base")
        self.live_file = live_file
        self.record_failures = record_failures
        self.flat_store = flat_store or FLAT_STORE
        self.live_steps: list[dict] = []
        if graph is None and mode == "graph":
            graph = GraphMemory(graph_name)
        elif graph is None and mode == "flatreplay":
            graph = FlatRoutes(self.flat_store)
        self.graph = graph
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
        self.last_item = None  # last replayed navigation click, kept so a transient timeout can be retried once
        self.target, self.bindings = None, {}
        self.banned: list[str] = []
        self.recoveries = 0
        self.usage.clear()

    # --- main loop ------------------------------------------------------------
    @cost_tracker_decorator
    def get_action(self, obs):
        before = {r: dict(self.usage[r]) for r in USAGE_ROLES}
        action, info = self._act(obs)
        # Explicit per-step usage; AgentLab sums every stats key into summary_info as stats.cum_<key>.
        stats = info.stats if isinstance(info.stats, dict) else {}
        for r in USAGE_ROLES:
            for k in ("calls", "api_attempts", "input_tokens", "output_tokens"):
                stats[f"pm_{r}_{k}"] = self.usage[r][k] - before[r].get(k, 0)
        stats["pm_replayed"] = int(((info.extra_info or {}).get("pathmemory") or {}).get("source") == "graph")
        info.stats = stats
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
                self.hint = flat_hint(self._goal(obs), store_path=self.flat_store)
            elif self.mode in REPLAY_MODES:
                self._plan(obs)
        if self.mode in REPLAY_MODES:
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
        self.bindings = {k: str(v) for k, v in (choice.get("bindings") or {}).items() if v}
        self.log.append({"event": "choose", "target": self.target, "bindings": self.bindings})
        if self.target:
            st = state_of(obs)
            self._route_from(st.key, st)

    def _route_from(self, key, st=None) -> bool:
        # From a page about a different entity than the one chosen, every remembered route stays on that
        # entity (links are relative to it), so replay stops here instead of navigating the wrong repo.
        wrong = st is not None and self._binding_mismatch(st)
        routes = [] if wrong else self.graph.routes(key, self.target, banned=self.banned)
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
        self.log.append({"event": "route", "keys": self.route["keys"], "eids": [e["eid"] for e in self.route["edges"]],
                         "sources": [e.get("sources") for e in self.route["edges"]]})
        return True

    def _fail(self, key, why, st=None):
        """The last replayed edge did not do what memory said: ban it for this run and look for another route.
        The failure is written to memory only when record_failures is on (live learning), never in evaluation."""
        if self.last_eid:
            self.banned.append(self.last_eid)
            if self.record_failures:
                self.graph.mark_failure(self.last_eid)
        self.log.append({"event": "edge_failed", "eid": self.last_eid, "at": key, "why": why,
                         "recorded": bool(self.last_eid and self.record_failures)})
        self.expect, self.last_eid = None, None
        if self.recoveries < 2 and self._route_from(key, st):
            self.recoveries += 1
            self.log.append({"event": "recovered", "via": self.route["keys"]})
            return True
        self.queue = []
        return False

    def _binding_mismatch(self, st) -> str | None:
        """Which chosen entity the page contradicts, e.g. landing on the fork byteblaze/design instead of
        primer/design. Only entities present in both the choice and the URL are compared, so pages that
        carry no entity (or a resource that does not exist yet) are not rejected."""
        for k in CHECKED_BINDINGS:
            want, got = self.bindings.get(k), st.bindings.get(k)
            if want and got and want.lower() != got.lower():
                return f"{k}={got} (chose {want})"
        return None

    def _match(self, obs, item, bindings, page_bindings):
        name = instantiate(item["name"], bindings)
        if "{" in name:  # a placeholder the choice did not bind: nothing safe to click
            return None
        # The landmark belongs to the current page, so only the page's own entities fill it.
        scope = instantiate(item["scope"], page_bindings)
        if "{" in scope:
            # Memory learned before p0 templated some landmarks with the destination's entities
            # ("main:{owner} - Dashboard"); such a scope cannot be checked. Visibility and uniqueness still are.
            self.log.append({"event": "scope_unverifiable", "target": item["name"], "scope": item["scope"]})
            scope = ""
        m = find_target(obs, item["role"], name, scope)
        href = m.ok and hrefs(obs).get(m.bid)
        if href and not item["pre"] and urlsplit(href).path.startswith("/"):
            # the link says where it goes: refuse before clicking if that is another entity than the one chosen
            bad = self._binding_mismatch(state_of({"url": href}))
            if bad:
                return Match("wrong_entity", candidates=m.candidates)
        return m

    def _replay_step(self, obs):
        st = state_of(obs)
        key = st.key
        if self.expect and key != self.expect:
            err = obs.get("last_action_error") or ""
            if self.last_item and not self.last_item.get("retried") and _transient(err):
                # the click timed out while the page was still moving: not evidence the step is broken
                self.last_item["retried"] = True
                self.queue.insert(0, self.last_item)
                self.expect, self.last_eid = None, None
                self.log.append({"event": "retry", "target": self.last_item["name"]})
            else:
                self._fail(key, f"expected {self.expect}", st)
        elif self.expect and (bad := self._binding_mismatch(st)):
            self._fail(key, f"wrong entity: {bad}", st)
        elif self.expect:
            self.expect, self.last_eid = None, None
        while self.queue:
            item = self.queue[0]
            b = {**st.bindings, **self.bindings}
            if item["pre"]:
                # A prerequisite (e.g. opening a dropdown) is skipped only when the step it prepares is
                # already clickable and unambiguous; otherwise it must itself be found, or replay stops.
                main = next((i for i in self.queue if not i["pre"]), None)
                m = main and self._match(obs, main, b, st.bindings)
                if m and m.ok:
                    self.queue.pop(0)
                    self.log.append({"event": "skip_pre", "target": item["name"]})
                    continue
            m = self._match(obs, item, b, st.bindings)
            if not (m and m.ok):
                self.last_eid = item["eid"]
                what = "prerequisite " if item["pre"] else ""
                if not self._fail(key, f"{what}{item['role']} '{item['name']}': {m.status if m else 'unbound'}", st):
                    break
                continue
            self.queue.pop(0)
            if not item["pre"]:
                self.expect, self.last_eid, self.last_item = item["dst"], item["eid"], item
            return self._replayed(obs, f"click('{m.bid}')", item)
        if self.target and not self.hint:
            self.hint = self._handover_hint(key, obs["url"], arrived=key == self.target and not self._binding_mismatch(st))
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

    def _handover_hint(self, key, url, arrived):
        site = next((s for s in self.graph.destinations() if s["key"] == self.target), None)
        if not site:
            return None
        # Anchor to the concrete URL: after the agent acts, it may land on another page with the same template
        # (e.g. a fork at /byteblaze/design vs /primer/design) and must not mistake it for the starting point.
        if arrived:
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
