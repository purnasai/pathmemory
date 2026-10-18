from pathmemory.state import Step, instantiate, parse_action, route_template, templatize


def test_repo_routes_share_a_template():
    a = route_template("http://localhost:3300/byteblaze/dotfiles/settings/collaboration")
    b = route_template("http://localhost:3300/a11yproject/a11yproject.com/settings/collaboration")
    assert a[0] == b[0] == "/:owner/:repo/settings/collaboration"
    assert a[2] == {"owner": "byteblaze", "repo": "dotfiles"}


def test_reserved_paths_and_query():
    assert route_template("http://x/user/settings/keys")[0] == "/user/settings/keys"
    assert route_template("http://x/")[0] == "/"
    key, _, _ = route_template("http://x/primer/design/issues?state=closed&q=foo&page=2")
    assert key == "/:owner/:repo/issues?state=closed"


def test_numbers_and_refs():
    key, _, b = route_template("http://x/primer/design/issues/12")
    assert key == "/:owner/:repo/issues/:n" and b["n"] == "12"
    assert route_template("http://x/primer/design/src/branch/main/docs/colors.md")[0] == "/:owner/:repo/src/branch/:ref"


def test_user_and_org_pages():
    assert route_template("http://x/alice")[0] == "/:owner"
    assert route_template("http://x/org/primer/teams")[0] == "/org/:org/teams"


def test_templatize_round_trip():
    b = {"owner": "byteblaze", "repo": "dotfiles"}
    assert templatize("dotfiles", b) == "{repo}"
    assert templatize("byteblaze/dotfiles", b) == "{owner}/{repo}"
    assert templatize("Settings", b) == "Settings"
    assert instantiate("{owner}/{repo}", {"owner": "primer", "repo": "design"}) == "primer/design"


def test_templatize_does_not_eat_substrings():
    assert templatize("design system", {"repo": "design"}) == "{repo} system"
    assert templatize("redesign", {"repo": "design"}) == "redesign"


def test_parse_action():
    assert parse_action("click('59')") == ("click", ["59"])
    assert parse_action("fill('184', 'bob', True)") == ("fill", ["184", "bob", "True"])
    assert parse_action('send_msg_to_user("It\'s 2")')[0] == "send_msg_to_user"


def test_only_nav_clicks_are_replayable():
    assert Step("click", "link", "Settings").navigational
    assert not Step("click", "button", "Add Collaborator").navigational
    assert not Step("fill", "textbox", "Search user", "bob").navigational


def test_badge_counts_and_issue_numbers():
    from pathmemory.state import norm_name

    assert norm_name("Issues 4") == "Issues" and norm_name("Pull Requests") == "Pull Requests"
    b = {"owner": "a11yproject", "repo": "a11yproject.com", "n": "4"}
    assert templatize("a11yproject/a11yproject.com#4", b) == "{owner}/{repo}#{n}"
