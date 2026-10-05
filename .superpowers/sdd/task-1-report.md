# Task 1 report: source process events and public P7 decisions

Status: implemented; provider-free targeted Python and registration checks pass. Full npm suite remains external/test-host limited on existing descriptor communication tests. No real model or game witness was invoked. Root owns commits and final integration.

## Changes and frozen UI shape

- New `console_events.py` implements `ConsoleEventWriter(run_root, run_id, game_id)` and `read_console_events`. Rows use `asterion.prime.p7-console-event/v1`, exact run/game identity, contiguous sequence and complete newline JSONL in `console-events.jsonl`. Payloads are closed and bounded; URLs, private paths, credential forms and control characters are rejected/removed before persistence. The reader retains only the safe complete prefix and rejects wrong run/game identity. Symlink evidence is not traversed.
- `p7_decision` is an actual TypeScript `registerTool` entry, in the Python tool registry, sealed facade, direct Pi method dispatch, socket worker dispatch and generated worker module. Inputs are exact `{goal,basis,expected}`, nonempty and <=600 characters each. It returns a decision ID and `execution_authority: none`. Prompt asks for a brief public Chinese summary before significant plans, explicitly optional and excluding private reasoning.
- `_P7BrokerClient` records pending summaries at `len(broker.journal)` plus the exact current unified observation digest. The next plan consumes the summary only when both still match. Plans without a new matching summary have no decision ID. Actual transitions include sequence, before/after digests, action/data, levels completed and decision ID. Initial and refreshed cognition captures include generated Chinese narrative, stable description and scalar session state, bound to the actual observation. Writer availability/failure cannot reject or change valid solver execution. Decision remains available before the first cognition probe.
- `build_console_snapshot` reads these records without requiring a final summary. Source decisions have `{id, source:'p7_decision', goal,basis,expected, source_action_sequence, observation_sha256, action_ids, event_sequence}`. Actions expose `source_action_sequence` and an explicitly linked `decision_id`. Each level exposes `cognition_timeline` entries `{cognition_revision, source_action_sequence, observation_sha256, stable_description,cognition_narrative_zh,session,frame_id,action_id,scope:'observation',event_sequence}`; latest aligned revision becomes `level.cognition`. Source revision/action matching requires actual position and hashes, never timing. Anonymous cognition log projections are never deduplicated across runs; identified session/event snapshots retain existing deduplication. Missing summaries remain missing. Legacy final-scope cognition and audit-only model rounds remain supported.
- Explicit source RESET transitions remain actions when the image is unchanged. A malformed recording row ends source-position alignment; a later repeated image cannot overwrite an earlier observation position. Recorded pixels remain the only frames.
- Packaged `resources/ipython-extension.mjs` was rebuilt/synchronized. No framework/runtime contracts or main operator run-ID selection were changed.

## Verification

RED evidence: initial source import/constructor/registration were absent; source reset was incorrectly omitted; a recording gap overwrote frame `f000002` with `f000003`. Each was observed failing before its implementation/fix.

Passing commands:

1. `uv run python -m unittest -q tests.test_prime_p7_console_events tests.test_prime_p7_console tests.test_prime_p7_console_export` — final 52 tests PASS after first-probe/cache advisory tests were added. Log: `/tmp/p7-task1-core.log`.
2. `uv run python -m unittest -q tests.test_prime_p7_console_events tests.test_prime_p7_console tests.test_prime_p7_console_export tests.test_prime_p7_bridge_dispatch tests.test_prime_p7_tool_registry tests.test_prime_p7_native_provider` — 105 tests PASS before final first-probe/cache advisory tests; the expanded suite below includes them. Log: `/tmp/p7-task1-python.log`.
3. `uv run ruff check src/asterion/applications/prime/p7/console_events.py src/asterion/applications/prime/p7/console_snapshot.py src/asterion/applications/prime/p7/operator.py src/asterion/applications/prime/p7/ipython_host.py src/asterion/applications/prime/p7/live.py src/asterion/applications/prime/p7/prompt.py src/asterion/applications/prime/p7/tool_registry.py tests/test_prime_p7_console_events.py` — PASS.
4. `node --test --test-name-pattern='registers the ipython|passes a public decision|built artifact' test/ipython-extension.test.mjs` from extension package — 3 tests PASS, including actual registration, exact goal/basis/expected schema, dispatch and pinned-loader artifact.
5. `npm --prefix packages/typescript/asterion-prime-extension run sync-resource` and `npm --prefix packages/typescript/asterion-prime-extension run check-resource` — PASS. Resource check log: `/tmp/p7-task1-resource.log`.

6. `uv run python -m unittest -q tests.test_prime_p7_console_events tests.test_prime_p7_console tests.test_prime_p7_console_export tests.test_prime_p7_bridge_dispatch tests.test_prime_p7_tool_registry tests.test_prime_p7_live_command tests.test_prime_p7_native_broker tests.test_prime_p7_guest tests.test_prime_p7_native_provider` — final 285 tests PASS (1 explicit external skip). Full log: `/tmp/p7-task1-python-expanded.log`.

## Known baseline/test-host limits

- Full `npm --prefix packages/typescript/asterion-prime-extension test` was run. A completed run produced 29 pass / 2 fail / 6 skipped. Existing tests `serializes method calls over the single bridge descriptor` and `recoverable method errors do not poison the bridge` timeout around 60 seconds; failure occurs in descriptor source-detachment behavior, not new tool registration. The latter also failed during the pre-implementation RED run when registration was still absent. Six Pi-mechanics tests explicitly skip because pinned third-party checkout is absent. Final rerun also completed with 29 pass / 2 fail / 6 skipped (182 seconds); all output and both complete failure stacks are saved at `/tmp/p7-task1-npm-full.log`. The targeted new registration/call and artifact tests PASS.
- Expanded Python run including `tests.test_prime_p7_live_command tests.test_prime_p7_native_broker tests.test_prime_p7_guest` reached 310 tests with one failure: `TestPrimeP7LiveCommand.test_initial_context_logs_cognition_refresh` expected `startup-cognition-marker`, but global cognition log duplicate-snapshot state from earlier suites suppressed it. Exact test run independently PASS. Root requested the lifecycle fix. A targeted RED test proved that anonymous projections with identical missing session/counter values suppressed unrelated run content. Deduplication now requires a nonempty session ID, carrying run identity. Existing identified-session/event deduplication tests remain unchanged and PASS; final expanded suite now PASS.
- No live level witness, promotion-check or overall task-level docs/status commit was performed by this worker; root owns those integration steps. Implementation and these tests do not prove P7 autonomous game-solving capability or live UI deployment.

## Review corrections (2026-10-05)

The three Important findings in `.superpowers/sdd/task-1-review.md` were reproduced with failing regressions before the fixes, then each passed:

1. Omitted recording rows and repeated pixels: actual source ACTION1 reaches B, its row is absent, a later recorded ACTION2 reaches B; this formerly attached ACTION1 cognition to the ACTION2 row. The new matrix also uses another ACTION1 reaching the same B, where action identity alone cannot resolve the ambiguity. Projection now establishes source positions only from a unique source transition matching actual action/data, completed levels and after digest, then verifies its contiguous native action sequence and before digest. A mismatch or multiple observable matches permanently ends source-prefix association. Recording frame/action ordinals remain replay metadata, not evidence of a broker position. The malformed-row regression now supplies the real initial source transition instead of relying on row counts.
2. Credential assignment redaction: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `TOKEN`, `ACCESS_TOKEN`, `SECRET` and `CLIENT_SECRET` assignments containing `SENTINELSECRET` formerly survived. Recognizable prefixed assignments now produce empty public prose and writer rejection before any file persistence. These six sentinels pass the regression; this boundary does not claim arbitrary unlabeled strings are detectable secrets.
3. Non-object source payload: a JSON list of decision key/value pairs formerly validated by coercion, retained the original list and crashed snapshot `.get()`. Writer validation now requires a Mapping; persisted payload validation requires an actual dict, and the reader retains the normalized object. Invalid payload type ends the safe prefix and adds the fixed `console-events-invalid` warning. Recursion errors are also treated as invalid evidence. The regression confirms one retained safe row, no snapshot crash, and public invalid-prefix warning.

The two ResourceWarnings were also localized: `SubprocessPythonWorker.close` waited/reaped its child and closed stdin, but left the owned stdout/stderr `Popen` streams open. A real provider-free worker cleanup test failed on `process.stdout.closed` before the fix. Its bounded shutdown now closes all three streams in `finally`; the test passes. The final expanded log contains zero ResourceWarning occurrences.

Final commands and output:

- `uv run python -m unittest -q tests.test_prime_p7_console_events` — `Ran 16 tests ... OK`.
- `uv run python -m unittest -q tests.test_prime_p7_console_events tests.test_prime_p7_console tests.test_prime_p7_console_export tests.test_prime_p7_bridge_dispatch tests.test_prime_p7_tool_registry tests.test_prime_p7_live_command tests.test_prime_p7_native_broker tests.test_prime_p7_guest tests.test_prime_p7_native_provider` — `Ran 289 tests in 0.904s; OK (skipped=1)`. Full log: `/tmp/p7-task1-review-python.log`. Exact warning scan: `ResourceWarning count: 0`.
- Scoped `uv run ruff check` on the original Task 1 Python ownership and new source test file — `All checks passed!`. Log: `/tmp/p7-task1-review-ruff.log`.
- `npm --prefix packages/typescript/asterion-prime-extension run check-resource` — exit 0, rebuilt `dist/ipython-extension.mjs 52.8kb`; packaged resource remains synchronized. Log: `/tmp/p7-task1-review-resource.log`.

No real model/witness, full npm rerun, commit or change to another worker's owned regions was performed during these corrections. The earlier full npm descriptor failures and external skips remain the recorded integration boundary.

### Readable multiline cognition correction

Controller integration found that single-line `public_text` had collapsed stable description/narrative sections used by UI `split('\n')`. A real renderer roundtrip regression failed writer validation on multiline output; the actual broker capture regression also failed because its generated descriptions had no newlines. Added cognition-specific `public_narrative`: it retains normalized line breaks and existing bounds while applying the same path/credential redaction. Both writer and reader use this canonical multiline rule; decision goal/basis/expected retain their single-line rule. Source cognition capture now uses `public_narrative`. Field names and UI interfaces did not change. The prefixed-credential matrix also confirms multiline prose containing each sentinel assignment is rejected.

Final verification after this correction:

- Source suite: 17 tests PASS, including actual `render_stable_game_description_zh`/`render_cognition_narrative_zh` newline roundtrip and broker-capture newlines.
- The same nine-suite expanded command above: `Ran 290 tests in 0.866s; OK (skipped=1)`, `/tmp/p7-task1-review-python.log`; no ResourceWarning remains.
- Scoped ruff: `All checks passed!`, `/tmp/p7-task1-review-ruff.log`.
- `npm --prefix packages/typescript/asterion-prime-extension run check-resource`: exit 0, `/tmp/p7-task1-review-resource.log`.
