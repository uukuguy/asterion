# Live Session Checkpoint

> Updated: 2026-10-20 18:26. **Session remains active — not a final handoff.**

## TL;DR

- The peer-foundation worklist is the active program. `P-PI-1` is done. Decision D-2026-10-20-04.
- The one-shot `pi.reference` facade and the long-lived session start, signal, and reap through `PiChildProcess`. Commit `ee1e687d`. Event mapping, redaction, and evidence stay on the facade.
- `P-NATIVE-1` and `P-CITE-1` are pending and are not started.

## Verified facts

- `tests.test_asterion_pi_runtime.PiRuntimeClientTests` passed: 22 tests.
- The regression set passed: `tests.test_asterion_pi_runtime`, `PiRpcReusableTests.test_force_close_kills_the_process_group_without_the_command_lock`, `TestP1Operator.test_forced_pi_close_bypasses_an_active_command_lock`, and `TestPrimeOwnedBackend.test_injected_output_capacity_reaches_launch_and_python_bridge`. 25 tests.
- A fresh interpreter called the shipped one-shot `run` twice on a local stub. Both runs exited 0, printed `fresh-owner-token-77eeaf02`, and recorded one `run.completed` event. The stub child was gone after each run.
- `ruff check` passed on `pi.py`, `pi_rpc.py`, `test_asterion_pi_runtime.py`, `test_pi_runtime_extensions.py`, and `test_default_runtime_factory.py`.
- No model run was started.

## Open boundary

- `P-NATIVE-1` is not started. There is no Native provider that assembles `dci` and `controlled-code`.
- `P-CITE-1` is not started. `prime-*-native` packages still execute Prime.
- A paid run, benchmark, official card, L9 rerun, and a push of `main` stay outside this program.

## Next action

1. Start `P-NATIVE-1`: one Native provider assembles the `dci` package and the `controlled-code` package against `pi.reference`. The base does not import either package.
2. Do not start a paid run from this checkpoint.
