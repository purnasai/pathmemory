"""Test doubles: a page builder, a chat model that reports usage the way AgentLab's ChatModel does,
a GenericAgent stand-in, and an in-memory route store. No browser, LLM or FalkorDB needed."""

import bgym
from agentlab.llm import tracking
from agentlab.llm.tracking import cost_tracker_decorator


def page(url, elements=(), goal="Do the task."):
    """elements: (bid, role, name, landmark, visible, href); landmark like "main" or "navigation:Navigation Bar"."""
    nodes = [{"nodeId": "root", "role": {"value": "RootWebArea"}, "name": {"value": "Gitea"}}]
    landmarks, attrs, strings, props = {}, [], [], {}

    def sid(s):
        strings.append(s)
        return len(strings) - 1

    for bid, role, name, landmark, visible, href in elements:
        parent = "root"
        if landmark:
            if landmark not in landmarks:
                lrole, _, lname = landmark.partition(":")
                landmarks[landmark] = f"lm{len(landmarks)}"
                nodes.append({"nodeId": landmarks[landmark], "parentId": "root", "role": {"value": lrole},
                              "name": {"value": lname}})
            parent = landmarks[landmark]
        nodes.append({"nodeId": f"n{bid}", "parentId": parent, "browsergym_id": bid, "role": {"value": role},
                      "name": {"value": name}})
        props[bid] = {"visibility": 1.0 if visible else 0.0}
        attrs.append([sid("bid"), sid(bid)] + ([sid("href"), sid(href)] if href else []))
    return {"url": url, "axtree_object": {"nodes": nodes}, "extra_element_properties": props,
            "dom_object": {"strings": strings, "documents": [{"nodes": {"attributes": attrs}}]},
            "goal_object": [{"type": "text", "text": goal}], "axtree_txt": "", "last_action_error": ""}


class FakeChat:
    """Answers with fixed replies and reports token usage to AgentLab's tracker, like ChatModel.__call__."""

    def __init__(self, replies, input_tokens=100, output_tokens=10):
        self.replies, self.input_tokens, self.output_tokens = list(replies), input_tokens, output_tokens
        self.retries = 1

    def __call__(self, messages, *a, **kw):
        if isinstance(getattr(tracking.TRACKER, "instance", None), tracking.LLMTracker):
            tracking.TRACKER.instance(self.input_tokens, self.output_tokens, 0.0)
        return {"role": "assistant", "content": self.replies.pop(0) if self.replies else "noop()"}

    def get_stats(self):
        return {"n_retry_llm": self.retries}


class FakeBase:
    """GenericAgent's surface as PathMemoryAgent uses it. Each get_action makes `calls_per_step` model calls
    (more than one = parse retries) inside its own cost tracker, as GenericAgent does."""

    def __init__(self, chat, calls_per_step=1):
        self.chat_llm, self.calls_per_step = chat, calls_per_step
        self.action_set = None
        self.reset()

    def reset(self, seed=None):
        self.obs_history, self.actions, self.memories, self.thoughts = [], [], [], []

    def obs_preprocessor(self, obs):
        return obs

    @cost_tracker_decorator
    def get_action(self, obs):
        self.obs_history.append(obs)
        for _ in range(self.calls_per_step):
            self.chat_llm([])
        self.actions.append("noop()")
        return "noop()", bgym.AgentInfo(think="", chat_messages=[], stats=self.chat_llm.get_stats())


class FakeGraph:
    """Route store with GraphMemory's read API: edges are (src, dst, role, name, scope, pre, eid)."""

    def __init__(self, edges, sites):
        self.edges, self.sites, self.failures = edges, sites, []

    def destinations(self):
        return [{"key": k, "title": k, "goals": [], "steps": []} for k in self.sites]

    def routes(self, src, dst, banned=(), k=3, max_hops=6):
        if src == dst:
            return [{"keys": [src], "edges": []}]
        out, stack = [], [(src, [src], [])]
        while stack:
            node, keys, path = stack.pop()
            for e in self.edges:
                if e[0] == node and e[6] not in banned and e[1] not in keys and len(path) < max_hops:
                    edge = {"eid": e[6], "kind": "click", "role": e[2], "name": e[3], "scope": e[4], "pre": e[5]}
                    if e[1] == dst:
                        out.append({"keys": keys + [e[1]], "edges": path + [edge]})
                    else:
                        stack.append((e[1], keys + [e[1]], path + [edge]))
        return sorted(out, key=lambda r: len(r["edges"]))[:k]

    def mark_failure(self, eid):
        self.failures.append(eid)
