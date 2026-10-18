"""Every text PathMemory sends to a model or an MCP client, in one place.

The rendered text is part of the experiment: v1 and v2 results were recorded with exactly these strings, so a
change here is a change to the method, not a refactor.
"""

# --- destination chooser (agent.py, one model call per episode) ---------------------------------------------------

CHOOSER_SYSTEM = "Reply with JSON only."

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

# one entry of {sites}; DONE_HERE is appended when past tasks worked on that page
CHOOSER_SITE = "- key={key}  (example page: {title})"
CHOOSER_SITE_DONE_HERE = "\n    done here: {goals}"

# --- flat memory (agent.flat_hint: top-k past trajectories in the goal) -------------------------------------------

FLAT_HINT_HEADER = "Successful past trajectories on this website (use them if relevant):\n\n"
FLAT_HINT_TASK = "Past task: {goal}\n"
FLAT_HINT_STEP = "  on {url}: {action}"

# --- hand-over note after graph / flat replay (agent._handover_hint) ----------------------------------------------

HANDOVER_ARRIVED = (
    "Memory note: before your first action, PathMemory replayed known navigation to {url} "
    "(page type {target}), where this kind of goal is usually done. "
    "Any page you see after that is the result of your own actions, so check whether the goal "
    "is already complete before repeating anything."
)
HANDOVER_STOPPED = (
    "Memory note: PathMemory tried to navigate to a page of type {target} but stopped at {url}. "
    "Continue from here yourself."
)
HANDOVER_SIMILAR = "Similar past tasks done on this page:"
HANDOVER_TASK = "- {goal}"
HANDOVER_TASK_STEPS = "  -> steps: {steps}"
HANDOVER_FOOTER = "Treat this as guidance: check the current page and complete the goal yourself."

# --- MCP server ----------------------------------------------------------------------------------------------------

MCP_INSTRUCTIONS = (
    "Procedural memory of a website (a Gitea instance), stored in FalkorDB as page templates "
    "(e.g. /:owner/:repo/settings/collaboration) linked by verified navigation clicks. "
    "Typical use: resolve_url for the current page, list_pages to pick a destination, find_route to get "
    "the clicks, then report_failure for any click that no longer works and call find_route again with "
    "that step in `avoid`. Placeholders like {repo} in click names are filled with the task's values."
)
