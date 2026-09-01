# Live Session Checkpoint

> Updated: 2026-09-02 06:07 +0800. **Session remains active on Prime Smoke Core implementation.**

## TL;DR

- Smoke Core receipt contract and its research/implementation plan are committed.
- Prime client-observation health is now persisted as body-free durable state; sequence gaps survive gateway reopen and block a healthy Core receipt.
- Next: implement the independent two-child, active detach/attach Core scenario and its bounded runner.

## Where things stand

- Commits `d935709` and `bf3dd23` establish and verify the observation-health recovery boundary.
- Gateway tests: `npm run build && node --test test/gateway.test.mjs` passes 65 tests; the narrow gateway suite including durable-store/main/client-observation passed 75 tests.
- `docs/status/JOURNAL.md` is intentionally dirty with append-only entries for the latest commits.

## Durable boundary

- `client.observation.health` stores only status, fixed reason code, sequence numbers, and resync flag; never observation bodies.
- A non-healthy persisted projection is not recreated on attach. Explicit resync remains future work; Core must fail closed until it exists.
- Existing README RLM smoke is one-child and detaches only after terminal; it is evidence for neither Core's two-child requirement nor active detach/attach.

## Immediate next action

1. Add provider-free tests and a Core-specific private scenario/runner that requires two distinct child lifecycles, message causality, active detach/attach, oracle result, and cleanup.
2. Add `make prime-smoke-core`, run its provider-free contract tests, then execute the bounded real Core scenario and retain only its public-safe receipt.

## Ready-to-paste verification

```bash
uv run python -m unittest -v tests.test_prime_core_smoke
npm --prefix packages/typescript/prime-gateway run build
node --test packages/typescript/prime-gateway/test/gateway.test.mjs
make prime-readme-rlm-smoke
```
