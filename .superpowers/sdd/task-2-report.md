# Task 2 report

Implemented bounded P7 console supervision and the loopback HTTP application. No model or real guest attempt was launched by this task. No commits were made; root owns integration.

## Delivered

- `console_session.py`: one activity slot; service-allocated exact run ID and exact guest unit; fixed level-witness argv; 900 second host watchdog; inherited unbounded/attempt/Make control flags removed. Operator/ARC roots and guest are trusted constructor values, passed explicitly. stdout/stderr are discarded and never used as browser data.
- Startup and stop command IDs deduplicate exact requests. Stop responds immediately with `stopping`; process termination, reap and guest cleanup happen outside the state lock. Natural exit also reaps the process group and independently checks the owned guest unit. Failed cleanup blocks restart.
- `operator.main`: optional console ID comes only from process environment, matches `p7-live-[0-9]{14}-[0-9a-f]{24}`, and refuses an existing or symlinked evidence directory. Non-console calls continue generating their ID.
- Make containment branch now admits a console-owned witness. Guest launcher requires witness mode, the complete strict ID/unit/900-second contract, and absence of the unbounded marker; sweep behavior remains. The environment allowlist forwards the console ID.
- Guest `systemctl stop` timeout is 30 seconds, exceeding the existing 20-second unit stop/KILL window. Console host cleanup timeout is 40 seconds and retains the helper's inactive/not-found and unpopulated-cgroup checks. The unrelated sweep supervisor still has its old host timeout; this task did not change that workflow.
- `console_server.py`: only 127.0.0.1; exact Host; exact Origin and page-injected random token for POST; bounded JSON and exact keys; fixed routes; no arbitrary file serving or CORS. HTML uses the renderer's actual script/style hashes plus frame-ancestors restriction.
- `game.public_game_catalog`: returns only validated game ID, alias and win-level metadata without importing game code.

## Frozen browser interface

- `GET /api/state`: `{session_id,state,game_id,run_id,cleanup_confirmed,snapshot,revision}`. IDs/game/snapshot are null while idle. States: `idle`, `starting`, `running`, `stopping`, `completed`, `incomplete`, `cancelled`, `timed-out`, `failed`, `cleanup-unconfirmed`.
- `GET /api/games`: `{games:[{game_id,alias,win_levels}]}`.
- `GET /api/runs`: `{runs:[{run_id,game_id,status}]}` from at most 256 explicitly validated run directories.
- `GET /api/replay/<run_id>`: safe console snapshot only, with catalog/game/run identity checks.
- `POST /api/start`: `{game_id,command_id}`; `POST /api/stop`: `{session_id,command_id}`. Both return the state shape with HTTP 202. Use `Content-Type: application/json` and `X-P7-Console-Token` header; browser same-origin Origin is required. Errors use fixed `{error:code}` responses.
- `render_console(snapshot,live_config={token,games})` receives the token only in the real-time page. No token in URLs or state APIs. Polling state does not start/stop a task.
- `serve_console(operator_root,arc_root,guest_machine='ubuntu',open_browser=False,on_ready=None)` is the CLI entry; it invokes on_ready with the bound loopback URL and cleans the session on SIGTERM/SIGINT/shutdown.

## Verification

- PASS: `uv run python -m unittest -q tests.test_prime_p7_console_session tests.test_prime_p7_console_server tests.test_prime_p7_guest tests.test_prime_p7_native_game tests.test_prime_p7_console_cli` — 43 tests, one existing opt-in real Orb probe skipped. Includes actual HTTP using fake processes, exact host/origin/token, immutable views, concurrent start/idempotency, stop during startup, slow cleanup without response blocking, deadline cancellation, natural exit, final success proof, mismatched run/game, environment contamination and reused run IDs.
- PASS: targeted `ruff check` over session/server/game/operator/guest helper and Task 2 test files; `git diff --check`.
- PASS: `make -n asterion-prime-p7-level-witness GAME=sp80 LEVEL=1 ...` read-only check confirms console containment branch and `python -I -m ...p7.operator` from wheel path.
- Related regression run: 138 tests across live-command, native-game, Task 2 and CLI had one failure: `TestPrimeP7LiveCommand.test_initial_context_logs_cognition_refresh` expected `startup-cognition-marker`, but log reported `duplicate-snapshot`. Reported to root/Task 1 owner; not classified as baseline and not fixed outside this task's ownership. Task 2 focused suite passed.

## Boundaries

Success is derived from the final safe snapshot's successful status plus sealed/replay-verified evidence, never process exit zero. An exit-zero run without successful evidence is incomplete. Forced stop need not produce final operator summary, but requires independent containment cleanup to permit a new run.

Real Mac/Orb containment, real wheel/model witness and visual acceptance are not proven by these fake-process tests; root owns that deployment verification. No pause/resume or manual game execution was added.

## Review correction: surviving host descendants

The important finding in `task-2-review.md` was reproduced before changing the implementation. The real-process regression starts a fresh process group with a Python parent and a child that ignores SIGTERM. Both parent-terminated and parent-natural-exit cases failed with the original helper: the guest-cleanup boundary observed a surviving host group.

`_stop_process` now sends SIGKILL to any remaining group members regardless of whether waiting for the parent timed out, reaps the parent, and waits up to five seconds for `killpg(pgid, 0)` to report group absence. A surviving group or inspection failure raises instead of granting cleanup confirmation. Session shutdown allows 60 seconds for the host teardown plus the existing 40-second guest cleanup. The independent guest cleanup still follows the host phase; any unconfirmed host teardown blocks restart even if guest cleanup succeeds.

Real regression uses actual subprocesses and OS group signals, with a readiness file from the TERM-ignoring child. It checks group absence at guest-cleanup entry for both parent exit modes, parent reaping and the final public cleanup flag. Its finally block forcibly cleans the owned group even on test failure. No model or Orb service is involved.

Fresh command outputs after correction:

```text
$ uv run python -m unittest -q tests.test_prime_p7_console_session.TestPrimeP7ConsoleSession.test_real_process_group_cleans_term_ignoring_child_after_parent_exit
Ran 1 test in 0.187s
OK

$ uv run python -m unittest -q tests.test_prime_p7_console_session tests.test_prime_p7_console_server tests.test_prime_p7_guest tests.test_prime_p7_console_cli
Ran 31 tests in 3.487s
OK (skipped=1)

$ uv run ruff check src/asterion/applications/prime/p7/console_session.py tests/test_prime_p7_console_session.py
All checks passed!

$ git diff --check
(no output; exit 0)
```

The skipped test remains the opt-in actual Orb probe. Only `console_session.py`, its session tests and this report changed for the review correction; no commit was made.
