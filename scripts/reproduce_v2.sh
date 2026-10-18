#!/usr/bin/env bash
# Reproduce the v2 composition evidence from a fresh clone.
#   scripts/reproduce_v2.sh            # checks only: no LLM, no API key, about 1 minute
#   scripts/reproduce_v2.sh --with-llm # also one composed-route run and one ablated run (needs an OpenAI key,
#                                      # about 2 minutes and $0.005 at gpt-6-luna list prices)
set -euo pipefail
cd "$(dirname "$0")/.."
step() { printf '\n== %s\n' "$*"; }

step "1. services (FalkorDB :6391, Gitea :3300)"
docker compose up -d
until curl -fs http://localhost:3300/api/healthz >/dev/null; do sleep 1; done
uv sync --quiet
uv run playwright install chromium >/dev/null

step "2. Gitea fixture: recreate, seed, compare with the declared state"
uv run python -m pathmemory.repro fixture

step "3. v2 training memory: load from committed dumps, check fingerprints against the manifest"
uv run python -m pathmemory.repro load

step "4. episode provenance: every edge <-> the training episodes that showed it"
uv run python -m pathmemory.repro provenance

step "5. composed route: live Cypher on v2 == committed composition.json (and no single episode has it)"
uv run python -m pathmemory.repro composition

step "6. graph ablation: copy v2, remove the bridge step, compare with the committed ablated graph"
uv run python -m pathmemory.repro ablate

if [[ "${1:-}" == "--with-llm" ]]; then
  F=docs/evidence/v2/memory/flat_memory.json
  step "7. composed-route run in the browser (dashboard repo links hidden, v2 memory)"
  uv run python -m pathmemory.run eval issues-2 --modes graph --break-ui --snapshot pathmemory_v2 --flat $F --tag repro-composed
  step "8. same with the ablated graph"
  uv run python -m pathmemory.run eval issues-2 --modes graph --break-ui --snapshot pathmemory_v2_ablated --flat $F --tag repro-ablation
  uv run python -m pathmemory.compare composed=results/repro-composed/eval.jsonl ablated=results/repro-ablation/eval.jsonl >/dev/null
fi

step "9. memories were not mutated"
uv run python -m pathmemory.repro unchanged
echo "all checks passed"
