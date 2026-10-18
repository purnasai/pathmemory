# Development

Work from a source checkout. Install the locked runtime and development dependencies:

```bash
uv sync --locked
```

## Routine checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -m 'not integration'
```

Run `uv run ruff format .` to format Python code. CI runs the checks above on Python 3.12.

## Container integration tests

Integration tests use scratch FalkorDB graphs; one Gitea test recreates the demo site.
Run them when no live task or experiment is using these containers:

```bash
scripts/reproduce_v2.sh
uv run pytest -q -m integration
```

Tests marked `falkordb` or `gitea` skip when their service is unavailable. Some checks also
need ignored raw run files; their skip reason explains that requirement. A skipped check
has not verified that behavior.

## Navigation and experiment changes

- Add regression coverage for changed matching, routing, response parsing, or trial accounting.
- Keep replay's entity, visibility, and ambiguity checks intact.
- Preserve model prompt strings during refactors. A prompt change changes the experimental method.
- Keep published JSON/JSONL evidence and memory dumps as recorded. Put new runs under a new tag
  and document the new conditions rather than replacing historical results.
- `site/` keeps its module paths so older serialized BrowserGym runs remain readable.
- `probe.py` re-exports historical probe classes so saved experiment arguments can be loaded.
- `run.py`, `report.py`, `compare.py`, `repro.py`, and `ui.py` are compatibility entry points;
  implement behavior in `evaluation/` or `demo/`.

For changes to memory loading or route composition, also run the no-model reproduction
script. A browser/model run is needed to validate changed end-to-end agent behavior;
unit tests and dump checks alone do not establish that result.
