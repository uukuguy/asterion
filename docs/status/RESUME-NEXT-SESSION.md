# Live Session Checkpoint

> Updated: 2026-08-01 11:55. **Session remains active — not a final handoff.**

## TL;DR

- All real DCI instances have completed their 50/total execution and compatible-resume verification.
- `db8713c` adds the explicit total-budget authorization required by paper-scoped full executions.
- Bright Biology's authorized 103/103 run is active under run ID `run-86fde416b0ea42b69a6f7876e3386443` with a $54 total budget.
- It runs serially only because concurrent Pi calls demonstrably fail; no case, model path, or evaluation rule is reduced.

## Immediate next action

1. Monitor the Bright Biology run to terminal completion; inspect its summary and execute compatible resume.
2. Record score, cost, duration, and paper-reference comparison in `docs/status/DCI-BENCHMARK-INSTANCES.md`.
3. Continue the approved recommended verification package only after this first full closure is verified.

## Ruled-out paths

- Do not use a sample/full duplicate public instance; report bounded work as `50/total`.
- Do not invoke a paper-scoped full run without `--max-cost-usd`; it is the explicit finite authorization.
- Do not reintroduce Pi parallelism until its native runtime failures are resolved.
- Do not publish prompts, corpus text, answers, model output, credentials, or private paths.
