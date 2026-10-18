# The Day My Browser Agent Lost a Link, and a Graph Found Another Way

*How I built PathMemory, a FalkorDB memory for browser agents, for Graph Hacks 2026. It covers the first version, the audit that found its numbers were wrong, and the rebuild that held up.*

*Built for Graph Hacks 2026, organised by WeMakeDevs and FalkorDB. Published on [Medium](https://purnasaigudikandula.medium.com/the-day-my-browser-agent-lost-a-link-and-a-graph-found-another-way-49c22b8b8b69).*

- 🎥 Demo (3 min): https://youtu.be/H7FJTGAeLQ4
- 💻 Code and reproducible evidence: https://github.com/purnasai/pathmemory

![PathMemory guided walkthrough](https://raw.githubusercontent.com/purnasai/pathmemory/master/docs/ui_v2_composition.png)

---

## 1. An agent that keeps asking for directions

If you watch an LLM browser agent long enough, you start to notice that it never learns its way around.

Ask it to add a collaborator to a repository. It reads the page, thinks, clicks the repo. It reads again, thinks, clicks Settings. It reads again, thinks, clicks Collaborators. Every click costs a model call: a few thousand tokens of page in, a little reasoning out.

Now ask it to do the same thing on a *different* repository. It starts from zero and reasons the whole way again, as if it had never been there.

People who use a website don't work like that. After a few visits you stop thinking about *how* to get to Settings; you just go there. Your attention is saved for the part that actually needs it: what to type in the form.

That was the question I took to Graph Hacks: **can a browser agent remember how a website is wired, and spend model calls only on the parts that need judgment?**

The more interesting question came later: **what happens when the website changes and the remembered way in disappears?**

## 2. Why a graph and not a transcript

The most common form of agent memory is a **transcript**: save successful trajectories, retrieve the most similar ones for a new task, and paste them into the prompt ("last time, for a similar goal, you clicked X, then Y, then Z"). It's simple and it often helps.

A transcript, though, describes one journey. It doesn't describe the place.

A website is a graph whether we store it that way or not. Pages are nodes and links are edges. Each time an agent clicks something and lands on a new page, it has learned a small fact that is true beyond that one task:

> *From this kind of page, clicking this element takes you to that kind of page.*

If you store those facts as **edges** rather than as lines in a story, something useful happens. Steps learned in *different* journeys connect wherever they share a page. Then a path query can find a route that no single past journey took.

That is PathMemory: **procedural memory for browser agents, stored as a graph in FalkorDB.**

## 3. The shape of the memory

The data model is small:

```text
(:State {key, route, title})
(:State)-[:ACT {eid, role, name, scope, pre, successes, failures, sources}]->(:State)
(:Task {id, goal, cluster})-[:WORKED_AT {steps}]->(:State)
```

- **A `State` is a page template, not a URL.** `/byteblaze/dotfiles/settings/collaboration` and `/primer/design/settings/collaboration` are the same node: `/:owner/:repo/settings/collaboration`. Without that, nothing generalises.
- **An `ACT` edge is a click, described by what the element *is* rather than where it is.** It stores the accessibility role and name (link `Settings`), the page landmark it was found in (`navigation`, `main:Issues`), any prerequisite clicks such as opening a dropdown, success and failure counters, and **`sources`: the training runs that taught this step.** Entity names become placeholders, so link `design` is stored as link `{repo}`.
- **`WORKED_AT` records where past tasks did their actual work**, which helps when choosing a destination.

At run time the loop is:

1. **One LLM call picks the destination**: which page template and which entities (owner, repo) the task needs.
2. **FalkorDB finds the route** with a bounded path query.
3. **The agent replays the clicks without calling the model.** Before each click it checks that the target is visible, unambiguous, and points at the right entity. After each click it checks that it landed on the expected page template.
4. **When replay arrives, or stops, control goes back to the LLM** for the part that needs judgment: filling in the form and pressing the button.

The query at the centre of it:

```cypher
MATCH (a:State {key:$src}), (b:State {key:$dst})
MATCH p = (a)-[:ACT*1..6]->(b)
WHERE all(r IN relationships(p)
  WHERE r.successes > 0 AND NOT r.eid IN $banned)
RETURN [n IN nodes(p) | n.key] AS pages,
       length(p) AS hops,
       reduce(f = 0, r IN relationships(p) | f + r.failures) AS fails
ORDER BY hops, fails LIMIT 3
```

It searches at most six hops, uses only steps that have worked at least once, skips anything that has already failed **in this run** (`$banned`), and prefers short paths with few recorded failures. When a step fails during replay, its id goes into `$banned` and the query runs again. That one parameter is the whole recovery mechanism.

![Learning and replay architecture](https://raw.githubusercontent.com/purnasai/pathmemory/master/docs/architecture.gif)

## 4. Night one: choosing a website I could break

Before writing any memory I needed a website: one I could reset, seed with known data, and break on purpose.

The obvious choice was WebArena's GitLab environment, but its image is about 30 GB, and I wanted experiments I could rerun in seconds. I used a **local Gitea instance** instead: a small self-hosted Git forge with users, organisations, repositories, issues and settings pages, which is plenty of navigation to learn. A seed script creates synthetic users (`byteblaze`, `carol`, …), organisations (`primer`, `a11yproject`) and repositories, and the whole site is recreated before every evaluation trial.

On top of that:

- **Agent:** AgentLab's `GenericAgent` on BrowserGym, unchanged. PathMemory wraps it and does not fork it. The action space is `click` and `chat`, with no `goto`, so the agent can't skip navigation by typing a URL.
- **Tasks:** 25 tasks in six groups (collaborators, issues, profile settings, repositories, explore, social). Each one is checked automatically through the Gitea API, the final URL, or the agent's answer.
- **Splits:** 8 training tasks and 3 "explore" training tasks build the memory, and 14 held-out test tasks are never written into it.
- **Baselines:** the same agent with **no memory**, and with **flat memory** (the top three most similar past trajectories in the prompt). Same model, prompt, step budget and hint channel in every mode.

The first commit went in at 01:57 on 16 October. About an hour later the memory layer, the replay agent and a first evaluation were running.

## 5. Everything that broke

None of this appears in an architecture diagram, but it's where most of the time went.

**Same name, different link.** Gitea has an "Issues" link in the top navigation bar, which shows *your* issues everywhere, and an "Issues" tab inside each repository. Same role, same accessible name. My first replay clicked the wrong one. The fix was to record the **landmark**, the region of the page the element lives in, as part of the edge.

**Badges.** The repository tab is called "Issues 4" on one repo and "Issues 2" on another. To the matcher those were different links. Counts are now stripped from names.

**Dropdowns.** Some links only exist after you open a menu, and opening the menu doesn't change the URL. A plain page-to-page edge can't express that, so edges now carry **prerequisite clicks**.

**The memory confused the agent.** This one surprised me. In a fork task the agent forked `primer/design` and landed on `/byteblaze/design`, which has *the same page template* as `/primer/design`. My hint told it "you are on the page where the work happens", so it forked again, and then again. The hint now names the **exact URL** where replay ended, not just the template.

**My own answer key was wrong.** One task asked how many commits were on a branch. The agents kept "failing". It turned out Gitea's commit counter on the repo page is cached and disagreed with the API my checker used. The agents were reporting what the page showed; the checker was the thing that was wrong. I replaced that task's goal with a deterministic one and recorded the change.

By the early hours of the 16th I had version one: a demo UI, an MCP server, and a results table I liked very much.

## 6. v1 looked like a win

The v1 headline on the normal UI said graph memory gave the same success rate with **about 26% fewer input tokens and 15% fewer LLM calls** than no memory. Under a UI break, after one repair episode, the graph recovered with far fewer tokens than flat memory. The README said every replayed route had been composed from several runs.

I spent the next day adding things: a live mode where you watch the agent in a visible browser, a "learn" switch that writes a successful run into FalkorDB as it happens, and backup and restore of the memory graph.

Then, on 18 October, I audited my own results before submitting, and three of my claims failed.

## 7. The audit: three things I had wrong

**1. "LLM calls" wasn't counting LLM calls.** The column counted browser steps whose action came from the model. It missed the destination-chooser call that graph mode makes once per run, and the parse retries the base agent makes when it can't parse its own answer. Recounted properly, graph mode made **4.64 model calls per task against 4.21 for no memory, about 10% *more*, not 15% fewer.** The token saving was real, because AgentLab's cost tracker had been counting the chooser's tokens all along. The "fewer calls" claim was false.

**2. The memory had seen a test task.** The "recovery" memory included a repair episode of `members-2`, which is a held-out test task. The Explore → repository step that made recovery possible came from that episode. That is leakage.

**3. "Every route is composed" was not true.** I wrote a provenance audit that traces each edge back to the runs that taught it. Only two of the recovery routes were actually stitched together from several runs. The others were entirely inside the single leaked repair episode.

None of these were bugs a test would catch. They were claims that went further than the evidence did. Fixing them took the rest of the hackathon and turned into most of the project.

The v1 logs are still in the repository unchanged, with a corrections file next to them that recomputes every number from the saved run directories.

## 8. v2: rebuilding it so the claim could be tested properly

The rebuild had one rule: **nothing the agent is tested on may teach the memory, and every claim must point to a file.**

- **Training-only memory.** v2 is built from ten named, successful training runs. The builder refuses held-out tasks and refuses runs whose goal doesn't match the task's current definition. A manifest records run ids, task ids, file hashes, and a fingerprint of the resulting graph.
- **A clean source for the Explore step.** Without the leaked episode, nothing in training showed the agent going Explore → repository, so I added a training task, `explore-3`: *"Using the Explore page's list of repositories (not the dashboard), open the a11yproject.com repository."* The first wording I tried ("Go to the Explore page and open…") failed oddly: the agent navigated correctly and then repeated "go to Explore" for 15 steps. That run is kept in the results and excluded. (I'm listing this as a limitation too: I added `explore-3` *after* looking at the training data.)
- **A fairer baseline.** Flat memory in the prompt isn't a like-for-like comparison with graph replay, so I added **flat replay**: the same destination chooser, the same element matcher, the same checks and the same fallback as graph mode, with one difference. Its route has to be a contiguous stretch of *one* stored trajectory. That isolates the thing I wanted to measure, which is whether joining steps across runs matters.
- **An ablation.** A copy of the graph with exactly one edge removed, the bridge step `/explore/repos → {repo}`. If the result depends on composition, it should disappear there.
- **Isolation.** Before every trial Gitea is recreated, re-seeded, and checked against a fixture fingerprint. The memory graph is copied from a read-only snapshot into a working graph, and evaluation never writes to memory.

## 9. The experiment: hiding the obvious way in

The held-out task is `issues-2`: *create an issue "Update color tokens" in primer/design and assign it to carol.*

On the normal site the route is short. From the dashboard, click the repository, then Issues, then New Issue. The training run `issues-1` contains exactly that route.

Then I break the site. An init script hides every `owner/repo` link on the dashboard, so the first step of the usual route is gone.

Here is what FalkorDB does:

1. With `banned = []`, it returns the usual three-hop route `/ → /:owner/:repo → issues → issues/new`.
2. Replay looks for the repository link on the dashboard and doesn't find it. That step's id goes into `$banned` for the rest of this run, and the query runs again.
3. With the dashboard step banned, there is exactly one route left:

| hop | step | taught by |
|---|---|---|
| `/` → `/explore/repos` | link `Explore` (navigation bar) | explore-1, explore-3 |
| `/explore/repos` → `/:owner/:repo` | link `{repo}` (Explore list) | **explore-3 only** |
| `/:owner/:repo` → `/:owner/:repo/issues` | link `Issues` (repo navigation) | **issues-1 only** |
| `/:owner/:repo/issues` → `.../issues/new` | link `New Issue` | **issues-1 only** |

The first two hops come from a run about *exploring*. The last two come from a run about *creating an issue in a different situation*. **None of the ten training runs contains this route, and none of them even contains all four steps.** An automated test checks this against the committed evidence.

The agent then replays the four clicks in a real Chromium browser, checking each landing page and the repository it is in, and arrives at the New Issue form. Only then does the LLM take over to type the title, pick carol as assignee, and submit.

![Route query in the demo UI](https://raw.githubusercontent.com/purnasai/pathmemory/master/docs/ui_route_query.png)

## 10. Results

Five trials per mode, interleaved, model `gpt-6-luna`, every trial reported:

| condition | mode | task passed | replay reached the form | model calls | input tokens | est. cost / task |
|---|---|---|---|---|---|---|
| broken | no memory | 5/5 | – | 7.0 | 20.6k | $0.0023 |
| broken | flat (prompt) | 5/5 | – | 7.6 | 25.4k | $0.0029 |
| broken | flat replay | 5/5 | **0/5** | 8.4 | 23.7k | $0.0027 |
| broken | **graph** | 5/5 | **5/5** | **6.0** | **15.0k** | **$0.0017** |
| broken + bridge removed | graph | 5/5 | **0/5** | 8.4 | 24.9k | $0.0028 |

What this shows:

- **Graph-composed replay reached the target page in 5/5 trials.** Replaying a single stored trajectory, with the same machinery otherwise, reached it in **0/5**, and so did the graph with the one bridge edge removed. The ablation makes the result depend on that single edge, which is about as direct as I could make the evidence.
- **Graph mode was the cheapest mode on the broken site**: 6.0 model calls and about 15k input tokens per task, against 7.0–8.4 calls and 20.6k–25.4k tokens for the others, roughly 26–39% lower estimated cost at list price.

And what it doesn't show:

- **Every mode passed the task in every trial.** When replay can't help, the base LLM finds its own way. Memory changed *how* the agent got there and what it cost, not *whether* it got there. There is no success-rate claim here.
- **No-memory used fewer browser actions (7 vs 9).** The activity feed on the dashboard still links the issue tracker, and the LLM spotted a two-click shortcut through it. PathMemory only learns navigation links it has seen used in training, so it couldn't take that shortcut. The UI break was only partial, and a sharp model noticed.
- **Flat prompt memory didn't retrieve the right runs.** Its top-3 similarity search didn't include `explore-3` or `issues-1`. I re-ran it with those two pinned into the prompt, and its path and cost didn't change. Having the right transcripts in context was not enough; something had to join them.

## 11. Refusing to click is a feature

Replaying clicks without the model is only safe if replay stops when it isn't sure. I tested that with scripted probes in a real browser:

- **Wrong entity.** Tell replay the target is `a11yproject/design`, which doesn't exist. It reroutes via Explore, finds a link named `design`, reads its href, sees `/primer/design`, and **refuses to click it** (`wrong_entity`). It made one replayed click and no wrong-target actions.
- **Ambiguity.** Create a fork so that two links named `design` appear. Replay refuses to guess and hands control to the LLM.

Across all 45 trials in the comparison, wrong-target clicks were **zero**.

## 12. Other things in the repo

- **A demo UI** (`uv run pathmemory-ui`) with a guided *Learn → Lose a link → Watch replay* walkthrough, a live mode that drives a visible browser, and a "learn" switch that writes a successful run into FalkorDB and highlights the new edges.
- **An MCP server** with six tools (`find_route`, `report_failure`, `record_step`, …), so any agent can ask the graph how to get somewhere and report what happened.
- **Persistence.** The memory survives process restarts and container restarts (verified and logged).
- **One-command reproduction.** `scripts/reproduce_v2.sh` recreates the site, loads the published memory snapshot, re-runs the composition query and the ablation, and checks them against the committed evidence. It needs no API key and was validated from a clean clone.

## 13. Limits

- One self-hosted website with synthetic data, one model, one composition case, five trials per mode. This is a demonstration, not a benchmark.
- No latency advantage (episode times overlap) and no significance test.
- The UI break was chosen by me, and it was partial.
- `explore-3` was added after inspecting the training data.
- The graph learns navigation links, not buttons or forms, so it can't learn shortcuts like the activity-feed one.

## 14. What I learned

**A graph earns its place when you need to combine knowledge.** On the normal site, single-trajectory replay did as well as the graph (both 5/5, about 6 model calls), because one past run already had the whole route. The graph only pulled ahead when the answer was spread across runs that were about different tasks. That is the case a path query handles and a list of transcripts doesn't.

**The most useful thing I built was the audit.** v1's numbers looked good and three of its claims were wrong. A provenance field on every edge (`sources`) let me ask "which run taught this?" and get a real answer, and that question is what exposed the leakage. If I did this again, I'd put provenance in on day one.

**Put the model where judgment is needed.** Navigation is mostly lookup. Deciding what to type in a form isn't. Letting the database handle lookup and the LLM handle judgment made the agent cheaper without making it less capable.

The next step is the obvious one: more sites, more tasks, more breaks, and more composition cases. Then we'll see whether this holds beyond one Gitea instance.

---

**Try it:**

```bash
git clone https://github.com/purnasai/pathmemory
cd pathmemory
scripts/reproduce_v2.sh      # no API key needed
uv run pathmemory-ui         # http://localhost:8795
```

- Demo video: https://youtu.be/H7FJTGAeLQ4
- Code, evidence and corrections: https://github.com/purnasai/pathmemory

*Built for Graph Hacks 2026 (WeMakeDevs × FalkorDB). Built with Claude Code assistance.*
