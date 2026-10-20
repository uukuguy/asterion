# Live Session Checkpoint

> Updated: 2026-10-20 19:16. **Session remains active — not a final handoff.**

## TL;DR

- The peer-foundation worklist is the active program. `P-PI-1` is done. Decision D-2026-10-20-04.
- `PiRpcSession` keeps `PiChildProcess`. `stop` and `force_close` reap only through that child. The one-shot facade uses the same spawn and reap. Commit `2f5046d3`. Event mapping, redaction, and evidence stay on the facade.
- `P-NATIVE-1` and `P-CITE-1` are pending and are not started.

## Verified facts

- `tests.test_asterion_pi_runtime.PiRuntimeClientTests` passed: 23 tests. A one-shot run and a locked `force_close` both invoke `PiChildProcess.reap`.
- One stdout line longer than 4MiB raises `ProtocolError` `Pi runtime output limit exceeded`. Queued stdout bytes stay within the 64KiB line cap.
- The regression set passed: `tests.test_asterion_pi_runtime`, `PiRpcReusableTests.test_force_close_kills_the_process_group_without_the_command_lock`, `TestP1Operator.test_forced_pi_close_bypasses_an_active_command_lock`, and `TestPrimeOwnedBackend.test_injected_output_capacity_reaches_launch_and_python_bridge`. 26 tests. Forced close still finishes within 0.5s while the command lock is held.
- `PiExtensionProcessTests.test_public_events_redact_adversarial_extension_channels` and `test_redaction_preserves_protocol_controls_matching_environment` passed. Their stdout shows `<redacted>`.
- A fresh interpreter called the shipped one-shot `run` twice on a local stub. Both runs exited 0, printed `fresh-owner-token-77eeaf02`, and recorded one `run.completed` event. The stub child was gone after each run.
- `ruff check` passed on `pi.py`, `pi_rpc.py`, `test_asterion_pi_runtime.py`, `test_pi_rpc_reusable.py`, and `test_pi_runtime_extensions.py`.
- No model run was started.

## Open boundary

- `P-NATIVE-1` is not started. There is no Native provider that assembles `dci` and `controlled-code`.
- `P-CITE-1` is not started. `prime-*-native` packages still execute Prime.
- A paid run, benchmark, official card, L9 rerun, and a push of `main` stay outside this program.

## Next action

1. `P-NATIVE-1` is the next pending package and is not started: one Native provider assembles the `dci` package and the `controlled-code` package against `pi.reference`. The base does not import either package.
2. Do not start a paid run from this checkpoint.
