"""Deterministic Gitea fixture, modelled on the WebArena GitLab task clusters.

Reset = recreate the container (its /data is tmpfs), then run this again.
"""

import base64
import subprocess
import time

import requests

from pathmemory.config import settings

ADMIN = ("byteblaze", "hackathon123")
USERS = ["alice", "bob", "carol", "dave", "erin"]
ORGS = {"a11yproject": "Accessibility project", "primer": "Design system"}

REPOS = [
    # owner, name, private, description
    ("byteblaze", "dotfiles", False, "My shell and editor configuration"),
    ("byteblaze", "gimmiethat.space", False, "Personal website"),
    ("byteblaze", "metaseq", True, "Experiments with sequence models"),
    ("a11yproject", "a11yproject.com", False, "The A11Y Project website"),
    ("primer", "design", False, "Primer design guidelines"),
]

FILES = {
    "byteblaze/dotfiles": {".bashrc": "export EDITOR=vim\n", ".vimrc": "set number\n"},
    "byteblaze/gimmiethat.space": {"index.html": "<h1>gimmiethat.space</h1>\n"},
    "a11yproject/a11yproject.com": {"CONTRIBUTING.md": "# Contributing\n", "src/checklist.md": "# Checklist\n"},
    "primer/design": {"docs/colors.md": "# Colors\n", "docs/typography.md": "# Typography\n"},
}

LABELS = {"bug": "ee0701", "enhancement": "84b6eb", "documentation": "0075ca", "help wanted": "008672"}

ISSUES = {
    "a11yproject/a11yproject.com": [
        ("Add skip-to-content link", ["enhancement"], False, "alice"),
        ("Contrast too low on footer links", ["bug"], False, "bob"),
        ("Document keyboard traps", ["documentation"], True, None),
        ("Screen reader announces menu twice", ["bug"], False, None),
        ("Translate checklist to Spanish", ["help wanted"], False, "carol"),
        ("Broken link in resources page", ["bug"], True, "alice"),
    ],
    "primer/design": [
        ("Clarify spacing scale", ["documentation"], False, None),
        ("Dark mode color tokens", ["enhancement"], False, "dave"),
        ("Typo in typography guide", ["bug"], True, None),
    ],
    "byteblaze/dotfiles": [
        ("Add tmux config", ["enhancement"], False, None),
    ],
}

MILESTONES = {"a11yproject/a11yproject.com": ["v2 launch"], "primer/design": ["Q4 cleanup"]}
COLLABORATORS = {"byteblaze/gimmiethat.space": {"alice": "write"}}
ORG_MEMBERS = {"a11yproject": ["alice", "bob"], "primer": ["carol"]}


def api(method, path, admin=True, **kw):
    r = requests.request(method, f"{settings.gitea_url}/api/v1{path}", auth=ADMIN if admin else None, timeout=30, **kw)
    if r.status_code >= 400 and r.status_code != 409:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else None


def wait_healthy(timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if requests.get(f"{settings.gitea_url}/api/healthz", timeout=3).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise TimeoutError("gitea not healthy")


def create_admin():
    subprocess.run(
        ["docker", "compose", "exec", "-T", "-u", "git", "gitea", "gitea", "admin", "user", "create",
         "--admin", "--username", ADMIN[0], "--password", ADMIN[1], "--email", f"{ADMIN[0]}@example.com",
         "--must-change-password=false"],
        cwd=settings.root, check=False, capture_output=True,
    )


def seed():
    wait_healthy()
    create_admin()
    for u in USERS:
        api("POST", "/admin/users", json={"username": u, "email": f"{u}@example.com", "password": "password123",
                                          "must_change_password": False})
    for org, desc in ORGS.items():
        api("POST", "/orgs", json={"username": org, "description": desc})
        team = api("GET", f"/orgs/{org}/teams")[0]  # Owners
        for m in ORG_MEMBERS.get(org, []):
            api("PUT", f"/teams/{team['id']}/members/{m}")
    for owner, name, private, desc in REPOS:
        path = "/user/repos" if owner == ADMIN[0] else f"/orgs/{owner}/repos"
        api("POST", path, json={"name": name, "private": private, "description": desc,
                                "auto_init": True, "readme": "Default", "default_branch": "main"})
        full = f"{owner}/{name}"
        for fname, content in FILES.get(full, {}).items():
            api("POST", f"/repos/{full}/contents/{fname}",
                json={"content": base64.b64encode(content.encode()).decode(), "message": f"Add {fname}"})
        for lname, color in LABELS.items():
            api("POST", f"/repos/{full}/labels", json={"name": lname, "color": color})
        for ms in MILESTONES.get(full, []):
            api("POST", f"/repos/{full}/milestones", json={"title": ms})
        for user, perm in COLLABORATORS.get(full, {}).items():
            api("PUT", f"/repos/{full}/collaborators/{user}", json={"permission": perm})
    for full, issues in ISSUES.items():
        label_ids = {l["name"]: l["id"] for l in api("GET", f"/repos/{full}/labels")}
        for title, labels, closed, assignee in issues:
            body = {"title": title, "labels": [label_ids[l] for l in labels]}
            if assignee:
                body["assignees"] = [assignee]
            issue = api("POST", f"/repos/{full}/issues", json=body)
            if closed:
                api("PATCH", f"/repos/{full}/issues/{issue['number']}", json={"state": "closed"})
    # a branch for merge-request style tasks
    api("POST", "/repos/primer/design/branches", json={"new_branch_name": "update-colors", "old_branch_name": "main"})


def reset():
    subprocess.run(["docker", "compose", "up", "-d", "--force-recreate", "gitea"], cwd=settings.root,
                   check=True, capture_output=True)
    seed()


if __name__ == "__main__":
    import sys

    (reset if "--reset" in sys.argv else seed)()
    print("seeded", settings.gitea_url)
