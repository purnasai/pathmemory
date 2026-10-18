"""Turn BrowserGym observations into reusable states and actions.

A *state* is a route template plus functional query parameters, e.g.
    /byteblaze/dotfiles/settings/collaboration  ->  /:owner/:repo/settings/collaboration
so a route learned on one repo applies to every repo. The concrete values
(owner=byteblaze, repo=dotfiles) are kept separately as *bindings*.

An *action* is identified by what it targets (role + accessible name), never by
BrowserGym's per-page element ids, and entity names are templated: a click on
the link "dotfiles" that lands on /:owner/:repo is stored as link "{repo}".
"""

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlsplit

# Gitea top-level paths that are not an owner name.
RESERVED = {
    "",
    "user",
    "explore",
    "org",
    "repo",
    "admin",
    "notifications",
    "issues",
    "pulls",
    "milestones",
    "api",
    "assets",
    "avatars",
    "-",
    "login",
    "swagger",
    "attachments",
}
# Query parameters that change what the page *is* (kept); everything else is noise.
FUNCTIONAL_PARAMS = {"state", "type", "tab"}
# Segments after which the rest of the path is a git ref / file path.
REF_MARKERS = {"branch", "tag", "commit"}
# Clicks on these roles only navigate; they are safe to replay. Buttons and form fields can change data.
NAV_ROLES = {"link", "tab", "menuitem"}
# Clicks that only reveal more navigation (dropdowns, collapsed menus); replayed as an edge prerequisite.
POPUP_ROLES = {"menu", "button", "combobox", "menubar", "generic"}
ENTITY_KEYS = ("owner", "repo", "org", "user")
LANDMARKS = {"navigation", "main", "banner", "contentinfo", "complementary", "form", "dialog", "menu"}


@dataclass(frozen=True)
class State:
    key: str  # route template + functional query, e.g. "/:owner/:repo/issues?state=closed"
    route: str
    bindings: dict = field(default_factory=dict, hash=False, compare=False)
    title: str = field(default="", hash=False, compare=False)


def route_template(url: str) -> tuple[str, str, dict]:
    """Return (key, route, bindings) for a URL."""
    parts = urlsplit(url)
    segs = [s for s in parts.path.split("/") if s]
    out, bindings = [], {}
    i = 0
    if segs and segs[0] == "org" and len(segs) > 1:
        out, bindings["org"], i = ["org", ":org"], segs[1], 2
    elif segs and segs[0] not in RESERVED:
        bindings["owner"] = segs[0]
        out, i = [":owner"], 1
        if len(segs) > 1 and segs[1] not in RESERVED:
            bindings["repo"] = segs[1]
            out, i = [":owner", ":repo"], 2
    while i < len(segs):
        s = segs[i]
        if s.isdigit():
            out.append(":n")
            bindings.setdefault("n", s)
        else:
            out.append(s)
            if s in REF_MARKERS:
                out.append(":ref")
                break
        i += 1
    route = "/" + "/".join(out)
    query = sorted((k, v) for k, v in parse_qsl(parts.query) if k in FUNCTIONAL_PARAMS)
    key = route + ("?" + "&".join(f"{k}={v}" for k, v in query) if query else "")
    return key, route, bindings


def _nodes(obs):
    return obs.get("axtree_object", {}).get("nodes", [])


def _role(n):
    return (n.get("role") or {}).get("value", "")


def _name(n):
    return " ".join(str((n.get("name") or {}).get("value", "")).split())


def page_title(obs) -> str:
    for n in _nodes(obs):
        if _role(n) == "RootWebArea":
            return _name(n)
    return ""


def open_dialog(obs) -> str | None:
    for n in _nodes(obs):
        if _role(n) in ("dialog", "alertdialog"):
            return _name(n) or _role(n)
    return None


def state_of(obs) -> State:
    key, route, bindings = route_template(obs["url"])
    dialog = open_dialog(obs)
    if dialog:  # a modal is a different state on the same URL
        key += f"#dialog={dialog.lower()}"
    return State(key=key, route=route, bindings=bindings, title=page_title(obs))


ACTION_RE = re.compile(r"^\s*(\w+)\((.*)\)\s*$", re.S)


def parse_action(action: str) -> tuple[str, list[str]]:
    m = ACTION_RE.match(action or "")
    if not m:
        return "", []
    args = re.findall(r"""'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|(\w+)""", m.group(2))
    return m.group(1), [a or b or c for a, b, c in args]


def scope_of(obs, node) -> str:
    by_id = {n.get("nodeId"): n for n in _nodes(obs)}
    cur = by_id.get(node.get("parentId"))
    while cur is not None:
        if _role(cur) in LANDMARKS:
            return f"{_role(cur)}:{_name(cur)}".rstrip(":")
        cur = by_id.get(cur.get("parentId"))
    return ""


def node_by_bid(obs, bid: str) -> dict | None:
    for n in _nodes(obs):
        if n.get("browsergym_id") == bid:
            return n
    return None


def norm_name(name: str) -> str:
    """Drop badge counts that differ per page, e.g. "Issues 4" -> "Issues"."""
    return re.sub(r"(\s+\d+)+$", "", " ".join(name.split()))


def templatize(text: str, bindings: dict) -> str:
    """Replace entity values with {owner}/{repo}/... placeholders (longest value first)."""
    out = text
    full = f"{bindings.get('owner')}/{bindings.get('repo')}"
    if "owner" in bindings and "repo" in bindings and full.lower() in out.lower():
        out = re.sub(re.escape(full), "{owner}/{repo}", out, flags=re.I)
    for k in sorted((k for k in ENTITY_KEYS if bindings.get(k)), key=lambda k: -len(bindings[k])):
        v = bindings[k]
        if out.lower() == v.lower():
            return "{" + k + "}"
        out = re.sub(rf"(?<![\w.-]){re.escape(v)}(?![\w.-])", "{" + k + "}", out, flags=re.I)
    if bindings.get("n"):
        out = re.sub(rf"#{bindings['n']}\b", "#{n}", out)
    return out


def instantiate(template: str, bindings: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(bindings.get(m.group(1), m.group(0))), template)


@dataclass(frozen=True)
class Step:
    """One semantic action: what was done to which element, with entities templated."""

    kind: str  # click | fill | select_option | send_msg_to_user | ...
    role: str = ""
    name: str = ""
    value: str = ""
    scope: str = ""  # nearest landmark, e.g. "navigation:Navigation Bar" vs "main" (same-named links)

    @property
    def navigational(self) -> bool:
        return self.kind == "click" and self.role in NAV_ROLES and "{" not in self.value

    def text(self) -> str:
        target = f" {self.role} '{self.name}'" if self.role else ""
        value = f" = '{self.value}'" if self.value else ""
        return f"{self.kind}{target}{value}"


def semantic_step(action: str, obs_before, bindings: dict, scope_bindings: dict | None = None) -> Step:
    """bindings template the target's name (it may name the destination, e.g. link "{repo}");
    scope_bindings template the landmark, which belongs to the page the click is made on. They differ when
    learning: the dashboard landmark "main:byteblaze - Dashboard" names the logged-in user, not the repo owner."""
    kind, args = parse_action(action)
    if kind in ("click", "fill", "select_option", "hover", "dblclick", "check", "uncheck") and args:
        node = node_by_bid(obs_before, args[0])
        role, name = (_role(node), _name(node)) if node else ("", "")
        value = args[1] if kind in ("fill", "select_option") and len(args) > 1 else ""
        scope = (
            templatize(scope_of(obs_before, node), bindings if scope_bindings is None else scope_bindings)
            if node
            else ""
        )
        return Step(kind, role, templatize(norm_name(name), bindings)[:120], templatize(value, bindings)[:120], scope)
    return Step(kind, value=(args[0][:120] if args else ""))


@dataclass(frozen=True)
class Match:
    """Result of looking up a remembered target on the current page.

    status: ok | missing | hidden | out_of_scope | ambiguous. Only "ok" carries a bid; replay never guesses.
    """

    status: str
    bid: str | None = None
    candidates: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def hrefs(obs) -> dict[str, str]:
    """bid -> href from the DOM snapshot (the accessibility tree does not carry link targets)."""
    dom = obs.get("dom_object") or {}
    strings = dom.get("strings") or []
    out = {}
    for doc in dom.get("documents") or []:
        for attrs in (doc.get("nodes") or {}).get("attributes") or []:
            a = {strings[attrs[i]]: strings[attrs[i + 1]] for i in range(0, len(attrs) - 1, 2)}
            if "bid" in a and a.get("href"):
                out[a["bid"]] = a["href"]
    return out


def find_target(obs, role: str, name: str, scope: str = "") -> Match:
    """Find the one visible element with this role and name inside the remembered landmark, or say why not.

    Fails closed: an element without visibility data counts as hidden, a remembered scope that matches no
    candidate is not widened to other landmarks, and several matches are accepted only when they are the
    same link (identical href), e.g. a repo listed twice on the dashboard.
    """
    props = obs.get("extra_element_properties") or {}
    want = norm_name(name).lower()
    nodes = [
        n for n in _nodes(obs) if n.get("browsergym_id") and _role(n) == role and norm_name(_name(n)).lower() == want
    ]
    if not nodes:
        return Match("missing")
    if scope:
        in_scope = [n for n in nodes if scope_of(obs, n).lower() == scope.lower()]
        if not in_scope:
            return Match("out_of_scope", candidates=len(nodes))
        nodes = in_scope
    visible = [n["browsergym_id"] for n in nodes if (props.get(n["browsergym_id"]) or {}).get("visibility", 0) > 0.5]
    if not visible:
        return Match("hidden", candidates=len(nodes))
    if len(visible) > 1:
        targets = {hrefs(obs).get(b) for b in visible}
        if len(targets) != 1 or None in targets:
            return Match("ambiguous", candidates=len(visible))
    return Match("ok", visible[0], len(visible))
