# Three-minute project demo

Target length: 3:00, including the end card. Use normal speech at about 130–140 words per
minute. The [narration](narration.txt) is about 390 words, leaving time to point and click.

The story is: remember navigation, lose the normal route, compose an alternative in
FalkorDB, verify it in the browser, then remove the bridge step to test the explanation.

## Rules and deadline

Checked against the official [rules](https://www.wemakedevs.org/hackathons/falkordb/rules)
and [schedule](https://www.wemakedevs.org/hackathons/falkordb/schedule) on 18 October 2026.
Submissions close at **11:59 PM IST on 18 October 2026**.

The pages require a video of the working project but do not state a video-duration limit.
Three minutes is this demo's target. A public repository, setup instructions, graph model,
dependent queries, track selection, and AI-assistance disclosure also belong in the
submission. Local setup instructions are accepted when the project cannot be deployed.

This project enters Track 01, Agents That Act on Connected Data, and Track 02, Agent
Memory and Coordination. Keep those track names on the end card and in the submission.

## Screen sequence

| Time | Show | Explain |
|---|---|---|
| 0:00–0:22 | PathMemory title, then the Walkthrough tab and held-out issue task | Repeated browser navigation costs model calls. The usual dashboard link is missing. |
| 0:22–0:46 | Graph and one edge's source episodes; briefly show the README graph model | State nodes are page templates; ACT edges are learned navigation. The model chooses a destination; FalkorDB supplies the route. |
| 0:46–1:08 | Route query tab, New Issue destination, Cypher expanded; then usual and broken-link routes | Search up to six hops, exclude a failed step, and combine steps from two training runs. |
| 1:08–1:50 | Recorded runs: broken / graph. Show the dashboard, Explore, repository, Issues, New Issue, then the created issue | Replay checks every landing page. Navigation uses memory; the model fills the form and submits. Keep RECORDED visible. |
| 1:50–2:13 | Walkthrough: bridge-edge ablation, no route; optionally open the recorded ablated run | Removing Explore → repository removes the alternative memory route. The base model remains a fallback. |
| 2:13–2:36 | Results: v2 broken-UI table; point to checker passed, replay reached page, and model calls | Graph replay 5/5; single-trajectory replay and ablation 0/5 through memory. Every mode completed the task. Six versus seven model calls; no demonstrated success or latency advantage. |
| 2:36–3:00 | Repository README and final card with repository URL, both tracks | One local synthetic site, one model, one composition case. Setup, schema, queries, and raw evidence are available. |

Read [narration.txt](narration.txt) continuously over the screen sequence. Rehearse once
and shorten pauses before increasing speech speed. Omit a logo animation or long greeting.

## Recording checklist

- [ ] Run `scripts/reproduce_v2.sh` before filming, when no other demo is using the local containers.
- [ ] The script confirms fixture `32f2a9ca533fd2ce` and v2 fingerprint `ff0899ff00fbb4d5`.
- [ ] The ablated snapshot is `93e0b6bd12e2831c`.
- [ ] Open `uv run pathmemory-ui` at http://localhost:8795, about 1500×950 or larger.
- [ ] Header shows Training memory (v2), and Walkthrough is the default tab.
- [ ] Confirm the chosen recorded graph run has its local screenshots and step traces.
- [ ] Capture the project UI and browser screenshots; keep code text large enough to read.
- [ ] Show recorded execution as RECORDED. Fresh database queries may be shown as live queries.
- [ ] If including a new live agent run, configure `.env` with the API key and rehearse first.
      It opens a visible Chromium window and incurs model charges. Start with no other run active.
- [ ] A previous Live run status is historical until a new task is started; do not present it as current execution.
- [ ] A live run needs extra time for reset and browser startup. Record it separately and edit the footage into
      the browser section, labelling any cuts or speed-up.
- [ ] End with the repository URL, Track 01 and Track 02. AI-assistance disclosure remains in the repository README.
- [ ] Review the final video for readable text, accurate labels, understandable audio, and a duration no longer
      than 3:00. Verify the submitted video link is accessible to judges.

## What to click

In Walkthrough, choose **Highlight the usual route** in step 1, then **Hide the usual link**
to see the alternative in step 2. Use **Highlight the alternative** to highlight it again. Click the Explore-to-repository edge to show its
source, `explore-3`; click New Issue to show `issues-1`.

For the actual execution, choose **Inspect the saved browser steps** in step 3, or open
the broken / graph row under **Browse recorded runs**. The recorded-run page shows its directory and RECORDED label. Select
steps 0–4 in order to show dashboard → Explore → repository → Issues → New Issue; the
later screenshot shows the created issue. These are real saved browser observations,
not a new model run during the presentation.

Then open step 3 and choose **Show the graph without the bridge**. It queries a prepared copy with the bridge removed;
describe it as a comparison against that copy, not a deletion performed on the main graph.

## If a fresh live run fails

Acknowledge it and switch to the recorded graph run. Keep its RECORDED label visible.
Do not claim that the graph improved task success, reduced browser actions, or improved
latency. The demonstrated result is cross-episode navigation replay with fewer model calls
in this case. Without FalkorDB the navigation-memory feature is unavailable; the base
browser agent can still operate as a fallback.

## Finished video

[Watch or download the finished MP4](../media/pathmemory-demo.mp4) (3:00, 1080p).
It is also playable in step 3 of the local walkthrough. The video was recorded before the
guided walkthrough was added, so its original tab label is **Route composition**.
