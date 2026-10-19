# Next-Session Handoff

> Updated: 2026-10-20 02:44 end of session.

## TL;DR

- `P-NOTES-1` and `P-P2-1` are accepted. `P-LIVE-1` is open.
- One current-main P1 preset stopped at its own model-callback cap. Run `p1-cbf17566ec1bdd98a2d6c0ab`, status `recovery-required`, limit 8, observed 9, `receipt_sha256` null.
- P4, P3, P5, and P6 did not run. Do not start a second paid P1 run unless the user continues the package.

## Verified facts

- Accepted-note epoch: `f73ac2c7`. P2 model inquiry: `b9b680b4`. Provider-free tests passed for those two packages. No live P2 model run.
- P1 preset wiring: `1a56b541` exports the existing `ASTERION_PRIME_PI_AGENT_DIR` into the guest. The live result is recorded in `6e225292`.
- Public P1 stages reached stage 1, compact, resume, and `stage2.release`. The stop is `prime-model-callback-limit`, phase `execution`, source `application`. Operator exit 1. Make exit 2.
- The callback cap `AsterionPrimeLimits(8, 4, 600000)` dates from `f1b08c1f` (2026-09-16). The compaction charge of +2 dates from `de261473` (2026-09-10).
- Guest `ubuntu-fusion-control` has root `uv` 0.13.1, uv-managed CPython 3.12.15, and an offline `node@22` npm cache. The Pi profile at the Make default `/mnt/mac$(HOME)/.pi/agent` is a real directory with `auth.json` and `models-store.json`.
- `make asterion-prime-p1-run` uses Orb. The live `asterion-prime-p4-run`, `asterion-prime-p3-run`, `asterion-prime-p5-run`, and `asterion-prime-p6-run` recipes invoke `uv` on the host.
- Local `main` is ahead of `origin/main` by the commits from this work. Nothing is pushed. Milestone tags are unchanged.
- No Asterion process remains. The guest was stopped at handoff.

## Current judgment

- The P1 stop is the application cap, after compact and resume. It is not an RPC or host failure.
- One stop is not a stability rate and is not a completed P1 verification.
- Do not raise the cap from this single observation.
- `P-LIVE-1` stays in progress. `P-COMPOSE-1` and `P-COMPACT-1` stay unstarted.

## Superseded

- The missing machine `ubuntu` and the missing guest `uv` are no longer the blocker. Use `PRIME_ORB_MACHINE=ubuntu-fusion-control` for Orb presets.
- The Python 3.10 resolver failure and the missing agent-directory preflight rejection were fixed before the paid run.
- Do not follow `docs/status/climb/session-state.json`.
- Do not treat `P-P2-1` as a live DeepSeek retrieval proof.
- Do not rerun L9 or reopen the death-prediction repair.

## Open boundary

- P1 on current main has no completed receipt.
- P4, P3, P5, and P6 live presets have not run. P5 still needs one real repair. P6 still needs one real rollback. Deterministic witnesses do not supply those outcomes.
- A live P2 preset, P1/P4 kernel handoff, dedicated code-aware compaction, and moving probe admission into Prime remain out of this handoff.

## Next action

1. On continue, ask whether to repeat the same P1 preset or to run P4 with P1 still unverified. Do not launch either paid run from this handoff alone.
2. Keep P5 and P6 on their live presets when their turn comes. Record a first-try success as itself.
3. Leave `P-COMPOSE-1` and `P-COMPACT-1` unstarted.

## Ready commands

```bash
orb start ubuntu-fusion-control
make asterion-prime-p1-run PRIME_ORB_MACHINE=ubuntu-fusion-control
```

Run these only after a new authorization for the same P1 preset. The guest is stopped.
