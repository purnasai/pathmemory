"""Gitea tasks for BrowserGym, grouped into clusters that share navigation prefixes.

Each task is checked deterministically:
  navigate -> final page URL matches a pattern
  retrieve -> agent's final message contains the expected answer
  mutate   -> Gitea API shows the expected state after the agent finishes
"""

import re
from dataclasses import dataclass, field
from typing import Callable

import playwright.sync_api
import requests
from browsergym.core.registration import register_task
from browsergym.core.task import AbstractBrowserTask

from pathmemory.config import settings
from pathmemory.site.seed import ADMIN


def _get(path):
    return requests.get(f"{settings.gitea_url}/api/v1{path}", auth=ADMIN, timeout=10)


def _json(path):
    r = _get(path)
    return r.json() if r.ok else None


def collaborator(repo, user, perm=None):
    def check():
        if _get(f"/repos/{repo}/collaborators/{user}").status_code != 204:
            return False
        if perm is None:
            return True
        return (_json(f"/repos/{repo}/collaborators/{user}/permission") or {}).get("permission") == perm
    return check


def issue_exists(repo, title, **want):
    def check():
        for i in _json(f"/repos/{repo}/issues?state=all&type=issues&limit=50") or []:
            if i["title"].strip() != title:
                continue
            if "assignee" in want and want["assignee"] not in [a["login"] for a in i.get("assignees") or []]:
                continue
            if "state" in want and i["state"] != want["state"]:
                continue
            if "label" in want and want["label"] not in [l["name"] for l in i.get("labels") or []]:
                continue
            return True
        return False
    return check


def repo_exists(full, **want):
    def check():
        r = _json(f"/repos/{full}")
        return bool(r) and all(r.get(k) == v for k, v in want.items())
    return check


def user_field(field_name, value):
    return lambda: (_json("/user") or {}).get(field_name) == value


def milestone_exists(repo, title):
    return lambda: any(m["title"] == title for m in _json(f"/repos/{repo}/milestones?state=all") or [])


def starred(repo):
    return lambda: _get(f"/user/starred/{repo}").status_code == 204


def following(user):
    return lambda: _get(f"/user/following/{user}").status_code == 204


@dataclass
class TaskSpec:
    id: str
    cluster: str
    kind: str  # navigate | retrieve | mutate
    goal: str
    check: Callable[[], bool] | None = None
    url_pattern: str | None = None
    answer: list[str] = field(default_factory=list)  # all must appear (case-insensitive)


TASKS = [
    # --- repo members / collaborators: repo -> Settings -> Collaborators
    TaskSpec("members-1", "members", "mutate", "Add bob as a collaborator to my dotfiles repository.",
             collaborator("byteblaze/dotfiles", "bob")),
    TaskSpec("members-2", "members", "mutate", "Give carol access to the gimmiethat.space repository as a collaborator.",
             collaborator("byteblaze/gimmiethat.space", "carol")),
    TaskSpec("members-3", "members", "retrieve", "Which users are collaborators on my gimmiethat.space repository? Reply with their usernames.",
             answer=["alice"]),
    TaskSpec("members-4", "members", "mutate", "erin wants to look at my metaseq repo. Add her as a collaborator.",
             collaborator("byteblaze/metaseq", "erin")),
    # --- issues: repo -> Issues -> (new | filter | issue page)
    TaskSpec("issues-1", "issues", "mutate", 'Open an issue titled "Improve focus outlines" in the a11yproject.com repository.',
             issue_exists("a11yproject/a11yproject.com", "Improve focus outlines")),
    TaskSpec("issues-2", "issues", "mutate", 'Create an issue "Update color tokens" in primer/design and assign it to carol.',
             issue_exists("primer/design", "Update color tokens", assignee="carol")),
    TaskSpec("issues-3", "issues", "mutate", 'Assign the issue "Screen reader announces menu twice" in a11yproject.com to bob.',
             issue_exists("a11yproject/a11yproject.com", "Screen reader announces menu twice", assignee="bob")),
    TaskSpec("issues-4", "issues", "mutate", 'Close the issue "Add tmux config" in my dotfiles repo.',
             issue_exists("byteblaze/dotfiles", "Add tmux config", state="closed")),
    TaskSpec("issues-5", "issues", "navigate", "Go to the list of closed issues in the a11yproject.com repository.",
             url_pattern=r"/a11yproject/a11yproject\.com/issues\?.*state=closed"),
    TaskSpec("issues-6", "issues", "retrieve", "How many open issues does the primer/design repository have? Reply with the number.",
             answer=["2"]),
    TaskSpec("issues-7", "issues", "retrieve", "Who is assigned to the issue about contrast on footer links in a11yproject.com?",
             answer=["bob"]),
    # --- profile settings: avatar menu -> Settings -> (Profile | SSH keys | Applications)
    TaskSpec("profile-1", "profile", "mutate", "Set the website URL on my profile to https://byteblaze.dev",
             user_field("website", "https://byteblaze.dev")),
    TaskSpec("profile-2", "profile", "mutate", 'Change my full name to "Byte Blaze".',
             user_field("full_name", "Byte Blaze")),
    TaskSpec("profile-3", "profile", "navigate", "Open the page where I can manage my SSH keys.",
             url_pattern=r"/user/settings/keys"),
    TaskSpec("profile-4", "profile", "navigate", "Open the page where I can create access tokens for applications.",
             url_pattern=r"/user/settings/applications"),
    # --- repo creation / structure
    TaskSpec("repos-1", "repos", "mutate", 'Create a new public repository called "hackathon-notes".',
             repo_exists("byteblaze/hackathon-notes", private=False)),
    TaskSpec("repos-2", "repos", "mutate", 'Create a private repository named "secret-plans".',
             repo_exists("byteblaze/secret-plans", private=True)),
    TaskSpec("repos-3", "repos", "mutate", "Fork the primer/design repository into my account.",
             repo_exists("byteblaze/design", fork=True)),
    TaskSpec("repos-4", "repos", "mutate", 'Create a milestone called "Beta" in the primer/design repository.',
             milestone_exists("primer/design", "Beta")),
    TaskSpec("repos-5", "repos", "retrieve", "How many commits are on the main branch of a11yproject.com? Reply with the number.",
             answer=["3"]),
    # --- social
    TaskSpec("social-1", "social", "mutate", "Star the a11yproject.com repository.", starred("a11yproject/a11yproject.com")),
    TaskSpec("social-2", "social", "mutate", "Follow the user alice.", following("alice")),
]
TASKS_BY_ID = {t.id: t for t in TASKS}


class GiteaTask(AbstractBrowserTask):
    """One PathMemory task. `ui_break` is JS injected into every page (recovery experiments)."""

    spec: TaskSpec

    @classmethod
    def get_task_id(cls):
        return f"pathmemory.{cls.spec.id}"

    def __init__(self, seed: int, ui_break: str | None = None) -> None:
        super().__init__(seed)
        self.ui_break = ui_break
        self.slow_mo = 200
        self.timeout = 10000

    def setup(self, page: playwright.sync_api.Page) -> tuple[str, dict]:
        if self.ui_break:
            page.context.add_init_script(self.ui_break)
        page.goto(f"{settings.gitea_url}/user/login")
        page.fill("#user_name", ADMIN[0])
        page.fill("#password", ADMIN[1])
        page.click("form.ui.form button.ui.primary.button")
        page.wait_for_url(re.compile(r".*(?<!/login)$"))
        page.goto(f"{settings.gitea_url}/")
        goal = self.spec.goal + " When you are done, send me a short message (include the answer if I asked a question)."
        return goal, {"task_id": self.spec.id, "cluster": self.spec.cluster, "kind": self.spec.kind}

    def validate(self, page, chat_messages) -> tuple[float, bool, str, dict]:
        # BrowserGym's chat opens with an assistant greeting before the user goal; only count replies after the goal.
        last_user = max((i for i, m in enumerate(chat_messages) if m["role"] == "user"), default=-1)
        replies = [m["message"] for m in chat_messages[last_user + 1:] if m["role"] == "assistant"]
        if not replies:
            return 0.0, False, "", {}
        s = self.spec
        if s.kind == "navigate":
            ok = bool(re.search(s.url_pattern, page.url))
        elif s.kind == "retrieve":
            text = replies[-1].lower()
            ok = all(re.search(rf"\b{re.escape(a.lower())}\b", text) for a in s.answer)
        else:
            ok = s.check()
        return float(ok), True, "", {"success": ok}


def register_all() -> list[str]:
    ids = []
    for spec in TASKS:
        cls = type(f"GiteaTask_{spec.id.replace('-', '_')}", (GiteaTask,), {"spec": spec})
        register_task(cls.get_task_id(), cls, nondeterministic=False)
        ids.append(cls.get_task_id())
    return ids
