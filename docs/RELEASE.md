# Public release notes (2026-10-18)

This public history was produced from the author's working repository by removing machine-specific absolute paths.
Nothing else was changed: no measurement, graph, fingerprint, manifest or code.

## What was replaced

In the 8 commits after `f84bf54` (the last commit already public), every occurrence of the author's local project
directory prefix (two spellings, before and after the folder was moved) was deleted, so a run directory such as
`<local project dir>/results/v1/eval/2026-10-16_02-12-10_…` now reads `results/v1/eval/2026-10-16_02-12-10_…`.
Only the `exp_dir` field of six historical v1 result logs contained such paths:

| file | paths replaced | sha256 (first 16) original | sanitized | every row identical except `exp_dir` |
|---|---|---|---|---|
| `docs/evidence/v1-repaired/recovery.jsonl` | 8 | e62e0d26e770b120 | af6e1b130ea75644 | yes |
| `docs/evidence/v1-repeat/eval.jsonl` | 1 | 9463f774700a2b9b | 1ea1672b0f700f31 | yes |
| `docs/evidence/v1-repeat2/eval.jsonl` | 1 | b61d31cd3540ef2a | b9d7e029027e441f | yes |
| `docs/evidence/v1/eval.jsonl` | 45 | 84ae886145eda39a | 7a39a858bee2375f | yes |
| `docs/evidence/v1/learn.jsonl` | 8 | c2c4560cb49359b5 | 651566dec3a0963a | yes |
| `docs/evidence/v1/recovery.jsonl` | 15 | 16bd05031ac789d4 | 61dcb521681c1844 | yes |

All v2 evidence already used project-relative paths. Graph fingerprints (`pathmemory_v2` `ff0899ff00fbb4d5`,
ablated `93e0b6bd12e2831c`, v1 `c51e00d7fe31aa16`), the training manifest (run ids, task/goal/file hashes) and the
flat-store hash `6c743fd14bc18df2` are unaffected: none of them covers these log files or contains a local path.
The original, unsanitized history is kept privately by the author.

## Commit hashes

Rewriting changes the hashes of the rewritten commits. Documents written before the rewrite cite the original
hashes; this table maps them:

| original | public | commit |
|---|---|---|
| `c9423a9` | `96aa34f` | Final submission docs: Tracks 01 (primary) and 02 (secondary), LLM-fallback wording, form  |
| `df167d6` | `fba0a3e` | REPRODUCE.md: record the clean-clone validation |
| `7403c6a` | `e38edac` | P2: v2 demo in the UI, flat-baseline audit, cost narrative, reproduction from a clean clon |
| `7f75c62` | `3c4afae` | P1: training-only v2 memory with edge provenance, flat-replay baseline, route-composition  |
| `7ab8385` | `b271323` | P0 correctness: explicit model-usage accounting, explicit attempt selection, fail-closed r |
| `a9abfdd` | `c8b5aa4` | Track 02 submission notes: verified results, audited composition, persistence, limits, rep |
| `f8f33fd` | `c7fa016` | Add live-learning tests |
| `dd68f66` | `d251814` | Live learning (write successful runs to FalkorDB, backup/restore), provenance audit, commi |
| `7ddb7b5` | `7ddb7b5` | Live run: start a task from the UI in a visible browser with live step and graph updates |

`7ddb7b5` and everything up to `f84bf54` are unchanged. `docs/evidence/v2/REPRODUCE.md` mentions the clean-clone
validation of original commit `7403c6a`, which is public `e38edac` here.
