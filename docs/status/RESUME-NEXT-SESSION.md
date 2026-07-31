# Live Session Checkpoint

> Updated: 2026-07-31 14:57. **Session remains active — not a final handoff.**

## TL;DR

- 50-case completion order remains fixed: Bamboogle, BC+ Level 3 and BC+ Main
  are verified; ArguAna is the active fourth instance.
- `920953a` adds one bounded DCI-native recovery attempt for a failed,
  incomplete, or running native Agent generation. The generic benchmark runner
  remains unchanged and does not retry.
- A clean ArguAna 50/1406 run is live in the current worktree with the local
  resource root explicitly selected. It must finish and resume without a new
  native generation before documentation is promoted.

## Verified baseline

- Bamboogle: 41/50 (82%).
- BC+ Level 3: 17/50 (34%).
- BC+ Main: 14/50 (28%).

## Immediate next action

1. Poll the live ArguAna run using aggregate evidence statuses only.
2. If all 50 complete, run exact `benchmark resume`, check no generation was
   added, record nDCG@10/cost/run ID in the Chinese instance list, and commit.
3. Continue with the next listed DCI instance only after ArguAna is verified.

## Ruled-out paths

- Do not reuse the earlier ArguAna evidence roots: they either selected an old
  external resource root or ended with terminal task failures before recovery.
- Do not report raw prompts, corpus, answers, model output, credentials, or
  private paths.
