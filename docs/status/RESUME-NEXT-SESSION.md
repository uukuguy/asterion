# Live Session Checkpoint

> Updated: 2026-07-31 13:16. **Session remains active — not a final handoff.**

## TL;DR

- The DCI evaluation order is fixed: each real instance completes its 50-case
  result and exact resume before any full-data evaluation is considered.
- Bamboogle is verified at 41/50 (82%); BC+ Level 3 is verified at 17/50
  (34%); BC+ Main is verified at 14/50 (28%). All have zero failed runs and
  no-regeneration resume closure.
- The next unimplemented instance is `dci.beir.arguana@1.0.0`.

## Durable baseline

- `dci.bcplus.main@1.0.0` uses suite `dci.bcplus.main@1.0.0`, task
  `bcplus.main`, the established 100-turn / ten-concurrent profile, and the
  real Agent/Judge engine.
- Its run `run-9bc4c4ec92f44ee8bab0fda79c01ceb4` completed 50/830 with 14
  correct, 28% accuracy, and 0 failures. Resume reused all 50 generations.

## Immediate next action

1. Verify and commit the BC+ Main result documentation.
2. Implement `dci.beir.arguana@1.0.0` through an exact IR task contract,
   suite, runbook, tests, and 50-case real execution/resume closure.

## Ruled-out paths

- Do not use shell-background or `nohup` for benchmark runs here: the command
  host reaps them when the short shell exits. Use a controlled live run.
- Do not label either 50/830 result as a full benchmark or paper reproduction.
- Do not publish prompts, answers, corpus text, raw model output, credentials,
  or private filesystem paths.
