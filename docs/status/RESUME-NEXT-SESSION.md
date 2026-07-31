# Live Session Checkpoint

> Updated: 2026-07-31 13:16. **Session remains active — not a final handoff.**

## TL;DR

- Bamboogle is the unified 125-case instance; its historical bounded result is
  41/50 (82%).
- BC+ Level 3 now has an exact product instance, payload suite, executor
  contract, tests, and a Chinese runbook.
- Its authorized 50/830 real run is in progress under a fresh source lock and
  private evidence root; 28 cases have completed with no failed runs.

## Durable baseline

- `dci@1.0.0` provides generic benchmark composition; DCI instances bind exact
  suites and implementations without framework code importing DCI products.
- The BC+ Level 3 executor preserves its established 300-turn, ten-concurrent
  profile. Aggregation retains native evidence and maps concurrent results by
  query identity.
- The active run invokes `env -u DEEPSEEK_API_KEY` so the `.env` judge
  credential is used instead of a conflicting inherited shell variable.

## Immediate next action

1. Wait for the active BC+ Level 3 run to finish all 50 cases, inspect only
   aggregate evidence, then verify its exact resume reuses evidence.
2. Publish the verified 50/830 result in `DCI-BENCHMARK-INSTANCES.md`, commit
   and journal it.
3. Implement and run the next instance, `dci.bcplus.main@1.0.0`, with the same
   50-case closure before proceeding to later instances.

## Ruled-out paths

- Do not treat earlier BC+ evidence roots as results: they stopped on
  credential, turn-budget, concurrency, or evidence-publication defects.
- Do not create separate public sample/full instances: an instance has its
  published total; a bounded result is reported as `50/total`.
- Do not inspect or expose prompts, answers, corpus content, raw model output,
  credentials, or private paths in public documentation.

## Active command

```bash
env -u DEEPSEEK_API_KEY uv run asterion-dci benchmark run \
  --instance dci.bcplus.level3@1.0.0 \
  --case-limit 50 \
  --capability-source-lock "$PWD/outputs/asterion-dci-bcplus-level3-stage50-final-closed-20260731/source-lock.json" \
  --evidence-root "$PWD/outputs/asterion-dci-bcplus-level3-stage50-final-closed-20260731/evidence" \
  --execute
```
