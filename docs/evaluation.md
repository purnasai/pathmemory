# Evaluation

PathMemory's published results demonstrate route composition on a local Gitea fixture.
They do not establish a general task-success or latency improvement.

## Current experiment: v2

Memory was built from ten successful training episodes. The held-out task, `issues-2`,
creates an issue in `primer/design` and assigns it to carol. Evaluation uses fresh fixture
state and a copy of the selected memory snapshot for each graph trial. The agent does
not record failures into evaluation memory.

The experiment compares the same base agent in four modes:

| Mode | Memory behavior |
|---|---|
| `none` | Base agent navigates and completes the task |
| `flat` | Top-three trajectories by goal-word similarity are added to the prompt |
| `flatreplay` | Replays a contiguous stretch of one stored trajectory |
| `graph` | Queries routes across steps learned in different trajectories |

Replay modes share the chooser, target matcher, entity checks, and model fallback. An
additional graph ablation removes the Explore-to-repository bridge step. A flat-prompt
coverage check pins the relevant training episodes instead of relying on retrieval.

With dashboard repository links hidden, graph replay reached the destination in 5/5
trials. Single-trajectory replay and the bridge ablation reached it through replay in 0/5.
Every mode still passed the task checker in every trial: the base model can navigate
when replay stops.

Graph mode averaged 6.0 model calls and 15.0k input tokens, compared with 7.0 calls and
20.6k input tokens without memory. The agent without memory used fewer browser actions
(7.0 versus 9.0), using an activity-feed shortcut that memory does not learn. There was
no demonstrated latency advantage or significance test. Normal-UI single-trajectory
replay tied graph replay on model calls and estimated cost.

Costs are historical estimates using the recorded litellm 1.80.0 pricing table. They are
not current API quotes. Model usage includes the chooser and base-agent completions,
including parse retries; browser steps are a separate measurement.

## Evidence and reproduction

- [Comparison and limitations](evidence/v2/FAIR_COMPARISON.md)
- [Composition and per-edge sources](evidence/v2/COMPOSITION.md)
- [Reproduction steps and recorded clean-clone validation](evidence/v2/REPRODUCE.md)
- [Training manifest and memory snapshots](evidence/v2/memory/)
- [Raw trial summaries](evidence/v2/runs/)
- [Screenshot walkthrough](evidence/v2/DEMO_WALKTHROUGH.md)

Recompute the current comparison from committed summaries:

```bash
uv run python -m pathmemory.compare \
  normal=docs/evidence/v2/runs/normal.jsonl \
  broken=docs/evidence/v2/runs/broken.jsonl \
  ablation=docs/evidence/v2/runs/ablation.jsonl
```

`scripts/reproduce_v2.sh` loads committed memory dumps and checks composition without
calling a model. Adding `--with-llm` produces two new browser runs. Rebuilding memory
from raw training episodes requires the ignored `results/` directories. A dump/provenance
check alone does not reproduce the original browser training runs.

The Results tab uses all v2 trials and falls back to committed summaries when local
results are absent. Opening a trace requires its local screenshot and pickle files.

## Historical results: v1

v1 results remain available as recorded. They have known methodological problems:

- The repaired memory included `members-2`, a test-task episode, so the recovery results
  were not held out.
- The original “LLM calls” column counted browser steps chosen by the model, excluding
  the destination chooser and parse retries.
- Evaluation wrote failure counts into its memory and did not reset read-only tasks.
- `repos-5` was run under two different goal definitions.

[Correction notes](evidence/v1-derived/CORRECTIONS.md) document those issues and revised
accounting. The UI labels these experiments historical and uses explicit latest-attempt
selection; the report command can display both first and latest attempts.

```bash
uv run python -m pathmemory.report docs/evidence/v1/eval.jsonl --select both
uv run python -m pathmemory.report docs/evidence/v1/recovery.jsonl --select both
uv run python -m pathmemory.report docs/evidence/v1-repaired/recovery.jsonl --select both
```

The previous v1 reproduction commands are retained below for historical investigation.
They reset fixture state and rebuild the demo memory; they are not the recommended setup.

```bash
uv run pathmemory learn --tag v1
uv run pathmemory eval --tag v1
uv run pathmemory learn explore-1 explore-2 --keep --tag v1-alt
uv run pathmemory recovery --tag v1
uv run pathmemory ingest results/v1/learn/* results/v1-alt/learn/* \
  results/v1/recovery/*PathMemory-none_on_pathmemory.members-2_0 --tag v1-repaired
uv run pathmemory recovery members-4 issues-2 issues-5 repos-3 --modes flat graph --tag v1-repaired
```

## Limits

One self-seeded site with synthetic data, one model, one composition case, and five trials
per mode. The UI break is partial: activity-feed issue links remain available. The
`explore-3` training task was added after inspecting the training data. These conditions
are useful for testing composition, but they do not represent WebArena or a broader benchmark.

A [historical persistence check](evidence/persistence/) recorded the same v1 route and
counts across a process and container restart. The current Compose file has no graph
volume, so persistence across container removal is not provided.
