"""Semantic replay fails closed: it clicks only a visible, unambiguous element in the remembered landmark,
and only keeps going while the pages it reaches are about the entity that was chosen."""

from pmfakes import FakeBase, FakeChat, FakeGraph, page

from pathmemory.agent import PathMemoryAgent
from pathmemory.graph import edge_id
from pathmemory.state import Step, find_target

HOME = "http://x/"


def _agent(edges, target, bindings, record_failures=False):
    import json

    choice = json.dumps({"target": target, "bindings": bindings})
    return PathMemoryAgent(
        FakeBase(FakeChat([])),
        "graph",
        "unused",
        FakeChat([choice]),
        record_failures=record_failures,
        graph=FakeGraph(edges, [target]),
    )


def _events(agent, kind):
    return [e for e in agent.log if e["event"] == kind]


# --- find_target ---------------------------------------------------------------------------------
def test_hidden_element_is_never_a_fallback():
    obs = page(HOME, [("1", "link", "Settings", "main", False, "/a")])
    assert find_target(obs, "link", "Settings").status == "hidden"


def test_missing_visibility_data_counts_as_hidden():
    obs = page(HOME, [("1", "link", "Settings", "main", True, "/a")])
    obs["extra_element_properties"] = {}
    assert find_target(obs, "link", "Settings").status == "hidden"


def test_remembered_scope_is_not_widened():
    obs = page(HOME, [("1", "link", "Settings", "navigation:Navigation Bar", True, "/user/settings")])
    m = find_target(obs, "link", "Settings", scope="main")
    assert m.status == "out_of_scope" and m.bid is None
    assert find_target(obs, "link", "Settings", scope="navigation:Navigation Bar").bid == "1"


def test_same_name_different_targets_is_ambiguous():
    obs = page(
        HOME,
        [
            ("1", "link", "design", "main", True, "/primer/design"),
            ("2", "link", "design", "main", True, "/byteblaze/design"),
        ],
    )
    assert find_target(obs, "link", "design", scope="main").status == "ambiguous"


def test_same_link_listed_twice_is_one_target():
    # the v1 dashboard lists primer/design twice (feed + repo list), both to /primer/design
    obs = page(
        HOME,
        [
            ("163", "link", "primer/design", "main", True, "/primer/design"),
            ("358", "link", "primer/design", "main", True, "/primer/design"),
        ],
    )
    assert find_target(obs, "link", "primer/design", scope="main").bid == "163"


def test_hidden_duplicate_does_not_make_a_visible_target_ambiguous():
    obs = page(HOME, [("1", "link", "Settings", "main", False, "/x"), ("2", "link", "Settings", "main", True, "/y")])
    assert find_target(obs, "link", "Settings", scope="main").bid == "2"


def test_scope_is_part_of_edge_identity():
    a = edge_id("/", Step("click", "link", "Settings", scope="main"), "/user/settings")
    b = edge_id("/", Step("click", "link", "Settings", scope="navigation:Navigation Bar"), "/user/settings")
    assert a != b


# --- replay ----------------------------------------------------------------------------------------
REPO_EDGE = ("/", "/:owner/:repo", "link", "{owner}/{repo}", "main", [], "e-dash")
EXPLORE_EDGE = ("/", "/explore/repos", "link", "Explore", "navigation:Navigation Bar", [], "e-explore")
EXPLORE_REPO = ("/explore/repos", "/:owner/:repo", "link", "{repo}", "main", [], "e-list")
PRIMER = {"owner": "primer", "repo": "design"}


def test_invisible_target_abandons_replay_instead_of_clicking():
    agent = _agent([REPO_EDGE], "/:owner/:repo", PRIMER)
    action, info = agent.get_action(page(HOME, [("5", "link", "primer/design", "main", False, "/primer/design")]))
    assert info.extra_info["pathmemory"]["source"] == "llm"  # handed to the LLM, nothing replayed
    assert "hidden" in _events(agent, "edge_failed")[0]["why"]


def test_ambiguous_target_reroutes_via_alternative():
    agent = _agent([REPO_EDGE, EXPLORE_EDGE, EXPLORE_REPO], "/:owner/:repo", PRIMER)
    home = page(
        HOME,
        [
            ("5", "link", "primer/design", "main", True, "/primer/design"),
            ("6", "link", "primer/design", "main", True, "/primer/design/issues"),
            ("7", "link", "Explore", "navigation:Navigation Bar", True, "/explore/repos"),
        ],
    )
    action, _ = agent.get_action(home)
    assert action == "click('7')" and "ambiguous" in _events(agent, "edge_failed")[0]["why"]
    assert agent.banned == ["e-dash"]


def test_wrong_entity_after_click_stops_replay():
    # Explore lists the fork byteblaze/design and primer/design under the same name "design"; say memory
    # clicks the visible one and lands on the fork: route template matches, entity does not.
    agent = _agent([EXPLORE_EDGE, EXPLORE_REPO], "/:owner/:repo", PRIMER)
    agent.get_action(page(HOME, [("7", "link", "Explore", "navigation:Navigation Bar", True, "/explore/repos")]))
    # no href to inspect beforehand (e.g. a scripted link or redirect): the arrival check is the safety net
    agent.get_action(page("http://x/explore/repos", [("9", "link", "design", "main", True, None)]))
    _, info = agent.get_action(page("http://x/byteblaze/design"))
    assert info.extra_info["pathmemory"]["source"] == "llm"
    [fail] = _events(agent, "edge_failed")
    assert fail["why"].startswith("wrong entity: owner=byteblaze")
    assert not _events(agent, "recovered") and agent.queue == []
    assert "stopped at http://x/byteblaze/design" in agent.hint


def test_correct_entity_continues():
    agent = _agent([EXPLORE_EDGE, EXPLORE_REPO], "/:owner/:repo", PRIMER)
    agent.get_action(page(HOME, [("7", "link", "Explore", "navigation:Navigation Bar", True, "/explore/repos")]))
    agent.get_action(page("http://x/explore/repos", [("9", "link", "design", "main", True, "/primer/design")]))
    agent.get_action(page("http://x/primer/design"))
    assert not _events(agent, "edge_failed") and "replayed known navigation" in agent.hint


def test_navigation_toward_a_resource_that_does_not_exist_yet_is_allowed():
    # creating "secret-plans": the chosen repo is not in any URL on the way to /repo/create
    edges = [("/", "/repo/create", "menuitem", "New Repository", "", ["button|Create…|"], "e-new")]
    agent = _agent(edges, "/repo/create", {"owner": "byteblaze", "repo": "secret-plans"})
    a0, _ = agent.get_action(
        page(
            HOME,
            [
                ("3", "button", "Create…", "", True, None),
                ("4", "menuitem", "New Repository", "", False, "/repo/create"),
            ],
        )
    )
    a1, _ = agent.get_action(
        page(
            HOME,
            [("3", "button", "Create…", "", True, None), ("4", "menuitem", "New Repository", "", True, "/repo/create")],
        )
    )
    agent.get_action(page("http://x/repo/create"))
    assert (a0, a1) == ("click('3')", "click('4')") and not _events(agent, "edge_failed")


def test_prerequisite_skipped_only_when_next_target_is_available():
    edges = [("/", "/user/settings", "menuitem", "Settings", "", ["button|Profile and Settings…|"], "e-set")]
    # menu already open: the target is visible, so the toggle is skipped (clicking it would close the menu)
    agent = _agent(edges, "/user/settings", {})
    a, _ = agent.get_action(page(HOME, [("8", "menuitem", "Settings", "", True, "/user/settings")]))
    assert a == "click('8')" and _events(agent, "skip_pre")
    # toggle gone and target hidden: not skipped silently, replay fails closed
    agent = _agent(edges, "/user/settings", {})
    _, info = agent.get_action(page(HOME, [("8", "menuitem", "Settings", "", False, "/user/settings")]))
    assert info.extra_info["pathmemory"]["source"] == "llm"
    assert _events(agent, "edge_failed")[0]["why"].startswith("prerequisite button")


def test_unbound_placeholder_is_not_clicked():
    agent = _agent([REPO_EDGE], "/:owner/:repo", {"repo": "design"})  # chooser gave no owner
    _, info = agent.get_action(page(HOME, [("5", "link", "{owner}/design", "main", True, "/x")]))
    assert info.extra_info["pathmemory"]["source"] == "llm"
    assert _events(agent, "edge_failed")[0]["why"].endswith("unbound")


def test_landmark_is_templated_with_the_page_it_is_on_not_the_destination():
    from pathmemory.state import semantic_step

    home = page(HOME, [("5", "link", "byteblaze/dotfiles", "main:byteblaze - Dashboard", True, "/byteblaze/dotfiles")])
    dst = {"owner": "byteblaze", "repo": "dotfiles"}
    step = semantic_step("click('5')", home, dst, scope_bindings={})
    assert step.name == "{owner}/{repo}" and step.scope == "main:byteblaze - Dashboard"


def test_legacy_over_templated_scope_still_requires_a_unique_visible_target():
    legacy = ("/", "/:owner/:repo", "link", "{owner}/{repo}", "main:{owner} - Dashboard", [], "e-dash")
    agent = _agent([legacy], "/:owner/:repo", {"owner": "a11yproject", "repo": "a11yproject.com"})
    a, _ = agent.get_action(
        page(
            HOME,
            [
                (
                    "5",
                    "link",
                    "a11yproject/a11yproject.com",
                    "main:byteblaze - Dashboard",
                    True,
                    "/a11yproject/a11yproject.com",
                )
            ],
        )
    )
    assert a == "click('5')" and _events(agent, "scope_unverifiable")
    agent = _agent([legacy], "/:owner/:repo", {"owner": "a11yproject", "repo": "a11yproject.com"})
    _, info = agent.get_action(
        page(
            HOME,
            [
                ("5", "link", "a11yproject/a11yproject.com", "main:x", True, "/a"),
                ("6", "link", "a11yproject/a11yproject.com", "main:y", True, "/b"),
            ],
        )
    )
    assert info.extra_info["pathmemory"]["source"] == "llm" and "ambiguous" in _events(agent, "edge_failed")[0]["why"]


def test_link_to_another_entity_is_refused_before_clicking():
    agent = _agent([EXPLORE_EDGE, EXPLORE_REPO], "/:owner/:repo", {"owner": "a11yproject", "repo": "design"})
    agent.get_action(page(HOME, [("7", "link", "Explore", "navigation:Navigation Bar", True, "/explore/repos")]))
    a, info = agent.get_action(
        page("http://x/explore/repos", [("9", "link", "design", "main", True, "/primer/design")])
    )
    assert info.extra_info["pathmemory"]["source"] == "llm" and a != "click('9')"
    assert _events(agent, "edge_failed")[0]["why"].endswith("wrong_entity")
