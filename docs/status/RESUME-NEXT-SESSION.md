# Live Session Checkpoint

> Updated: 2026-10-20 17:37. **Session remains active — not a final handoff.**

## TL;DR

- The peer-foundation worklist is the active program. `P-PI-1` is open. Decision D-2026-10-20-04.
- Forced Pi close now belongs to `PiRpcSession.force_close`. Prime launch no longer signals the process group. Commit `da76b733`.
- The one-shot `pi.reference` facade in `src/asterion/runtimes/pi.py` still starts its own subprocess. That is the next slice of `P-PI-1`.

## Verified facts

- `tests.test_pi_rpc_reusable.PiRpcReusableTests.test_force_close_kills_the_process_group_without_the_command_lock` passed.
- `tests.test_asterion_prime_p1_operator.TestP1Operator.test_forced_pi_close_bypasses_an_active_command_lock` passed.
- `tests.test_asterion_prime_backend.TestPrimeOwnedBackend.test_injected_output_capacity_reaches_launch_and_python_bridge` passed.
- `tests.test_pi_rpc_reusable.PiRpcReusableTests.test_close_is_idempotent_and_stops_once` passed.
- `ruff check` passed on `pi_rpc.py`, `_launch.py`, and `test_pi_rpc_reusable.py`.
- No model run was started.

## Open boundary

- `P-PI-1` is not done. `pi.reference` still owns a subprocess loop.
- `P-NATIVE-1` and `P-CITE-1` are pending and depend on `P-PI-1`.
- A paid run, benchmark, official card, L9 rerun, and a push of `main` stay outside this program.

## Next action

1. Move `src/asterion/runtimes/pi.py` process creation onto `PiRpcSession`, keeping its event, evidence, and redaction behavior.
2. Re-run the focused Pi runtime tests for that slice. Do not start a paid run from this checkpoint.
