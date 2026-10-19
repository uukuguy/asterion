# Live Session Checkpoint

> Updated: 2026-10-20 02:32. **Session remains active — not a final handoff.**

## TL;DR

- `P-LIVE-1` started. One current-main P1 preset ran on guest `ubuntu-fusion-control`.
- Run `p1-cbf17566ec1bdd98a2d6c0ab` reached stage 1, compact, and resume, then stopped. Public status is `recovery-required`. The alarm is `prime-model-callback-limit`, phase `execution`, limit 8, observed 9, source `application`. `receipt_sha256` is null. The operator exited 1.
- This is not a completed P1 verification. One stop is not a stability rate. P4, P3, P5, and P6 were not started.
- `P-NOTES-1` and `P-P2-1` stay accepted. Milestone tags are unchanged.

## Host

- Named machine `ubuntu` is still absent. This run passed `PRIME_ORB_MACHINE=ubuntu-fusion-control`.
- The guest is running. Root `uv` is 0.13.1. `uv` manages CPython 3.12.15, which the preset selected for IPython 9.17.1. The `node@22` npm cache resolves offline.
- `asterion-prime-p1-run` now forwards the existing `ASTERION_PRIME_PI_AGENT_DIR` default into the guest. Commit `1a56b541`.

## Next action

1. Leave this P1 stop as the recorded result. Do not raise the callback cap from this one observation, and do not launch a second paid P1 run unless the user continues the package.
2. After that, run the existing P4, P3, P5, and P6 presets one at a time on the same guest. P5 must show one real repair. P6 must show one real rollback. A first-try success is not those two outcomes.
3. Keep `P-COMPOSE-1` and `P-COMPACT-1` unstarted.

## Ruled out

- Do not treat the callback stop as an RPC or host failure. The public stages passed compact and resume before the execution cap.
- Do not rerun L9 or reopen the death-prediction repair.
- Do not treat `P-P2-1` as a live DeepSeek retrieval proof.
