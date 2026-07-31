# Live Session Checkpoint

> Updated: 2026-07-31 20:15. **Session remains active — not a final handoff.**

## TL;DR

- Every real DCI instance must first close a scored, resumed `min(50, total)` run.
- Bamboogle, BC+ Level 3/Main, BEIR ArguAna/SciFact, Bright Biology/Earth
  Science, and Bright Economics are `Verified-bounded`; their results are in
  `DCI-BENCHMARK-INSTANCES.md`.
- Bright Economics has completed its actual 50/103 run and resume verification:
  nDCG@10 0.3717, about $4.11, run `run-63742304e39c4d4a852d1bc4b27174f9`.
- Bright Robotics completed its actual 50/101 run and resume verification:
  nDCG@10 0.4178, about $4.46, run `run-e9575e75038647269134b72c4da70502`.
- QA 2WikiMultiHopQA completed its actual 50/12,576 run and resume verification:
  80% (40/50), about $1.89, run `run-9d46b77d0fd84f408a20bc329b7f7032`.

## Immediate next action

1. Implement QA HotpotQA with test-first contract, payload, binding,
   Chinese runbook, and focused verification.
2. Run exactly 50/total, then resume the returned run ID and verify the native
   generation count is unchanged before publishing its result.
3. Continue the remaining QA instances in the same order; do not start any
   full-data run until every real instance has a 50/total closure.

## Ruled-out paths

- Do not introduce public sample/full duplicate instances; report `50/total`.
- Do not publish raw prompts, corpus, answers, model output, credentials, or
  private paths.
- Do not infer data totals: use the paper benchmark inventory (Earth Science is
  116).
