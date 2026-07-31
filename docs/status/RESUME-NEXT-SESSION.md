# Live Session Checkpoint

> Updated: 2026-07-31 15:50. **Session remains active — not a final handoff.**

## TL;DR

- Every real DCI instance must first close a scored, resumed `min(50, total)` run.
- Bamboogle, BC+ Level 3/Main, BEIR ArguAna/SciFact, and Bright Biology are
  `Verified-bounded`; their results are in `DCI-BENCHMARK-INSTANCES.md`.
- Bright Earth Science is implemented in commit `5d36652`; its real 50/116 run
  is live under `outputs/asterion-dci-bright-earth-science-stage50-20260731-rerun`.

## Live run

- Process: `asterion-dci benchmark run` for `dci.bright.earth-science@1.0.0`.
- Lock and evidence root are in the live-run directory above.
- At checkpoint, nine completed native evidence records exist and no failure is
  recorded. Do not call a second `run`.

## Immediate next action

1. Poll aggregate evidence statuses only; never expose raw benchmark material.
2. When all 50 complete, get summary nDCG@10/cost/run ID, run exact resume,
   verify native-generation count is unchanged, then update the Chinese table
   and runbook and commit.
3. Only then implement and run Bright Economics 50/103 with the same test-first
   and payload/Chinese-runbook closure.

## Ruled-out paths

- Do not introduce public sample/full duplicate instances; report `50/total`.
- Do not publish raw prompts, corpus, answers, model output, credentials, or
  private paths.
- Do not infer data totals: use the paper benchmark inventory (Earth Science is
  116).
