# P7 Continuous Rollout Implementation Plan

> For agentic workers: use supervised subagent implementation with disjoint files and root integration review.

**Goal:** implement and verify a P7 experiment that expands continuous consequences and replays death examples without changing real action authority.

**Architecture:** A standalone application Python helper executes actor-owned callbacks in the existing persistent research kernel. Existing read-only evidence assembles current-run death cases. Experimental guidance lives solely in the supervised entry.

**Tech Stack:** Python stdlib/unittest; existing Prime workspace and wheel packaging.

## Global Constraints

No hidden game-state access, hardcoded level solver, additional paid run, mandatory cognition workflow, new tool registration or safety certificate. Unknown remains unknown. Experimental prompt remains entry-only. Other working-tree edits are preserved.

### Task 1: continuous simulation and report data

Files: src/asterion/applications/prime/p7/rollout.py; tests/test_prime_p7_rollout.py.

- [x] Write and run failing tests for one input followed by autonomous ticks, nonfatal collision, unknown/cycle/limit and immutable input.
- [x] Implement rollout, replay_cases and evaluate_candidates using the frozen spec signatures, JSON copies and explicit model-relative results.
- [x] Verify the one-file unittest and Ruff, reporting exact commands. Do not change real plan admission.

### Task 2: existing-kernel integration

Files: research_bridge.py, prompt.py, operator.py and existing research/runtime/autonomous tests.

- [x] Embed installed helper source before generated evidence code; preserve future-import placement and standard existing execution tests.
- [x] Add death_cases and replay_deaths to local research namespace; collect all committed current-run deaths with exact refs/actions and reject missing evidence.
- [x] Append P7_ROLLOUT_EXPERIMENT_PROMPT only from exact research entry; public autonomous prompt remains unchanged.
- [x] Verify read-server and actual persistent kernel availability, plus no new action/tool routes.

### Task 3: integration evidence and review

- [x] Run a private offline witness against preserved Task46 L3 observations, disclosing the partial model and its evidence limits.
- [x] Run focused integration tests, package verification and one required promotion-check; do not run paid ARC witness.
- [x] Independently review model-relative claims, unknown handling, kernel source binding, failure propagation and absence of hidden engine reads.
- [x] Record implementation/verification/unverified live efficacy in existing state files and commit focused changes.

## Evidence so far

- Initial helper tests failed against missing API, then passed; two independent-review regression tests reproduced false cycle / preterminal replay verdicts before repair.
- Root focused suite: `uv run python -m unittest -q tests.test_prime_p7_rollout tests.test_prime_p7_research tests.test_prime_p7_autonomous_interface tests.test_prime_p7_research_runtime tests.test_prime_p7_action_preconditions tests.test_prime_p7_notes_operator tests.test_prime_p7_output_config` — 82 PASS /21.930s.
- Changed-file Ruff and docs-check PASS. Astra final review APPROVE; independent16-test focused probe PASS.
- Private Task46 L3 witness: one input +3 automatic ticks reproduces actual death77; myopic model counterexample; original host observation comparison checked1. Partial operator model, engine/model0, no live efficacy claim.
- Fresh-wheel isolated installed package + actual PersistentIPython PASS; source hashes match checkout, all4 helpers available, two simulated deaths fully replayed, candidate2ticks, engine/model0, kernel closed. Wheel SHA256 `d7477c1672351699252abf4f6408d4ac63d6d065d11fd49354c3f416d563bd03`; receipt SHA256 `7c6d935c4fd3f5ebddfde0ba345abc4e464509dc13aa84aa1415c35f12f01e61`; exact build/install/witness commands in `.asterion-private/task47-p7-rollout/installed-kernel-witness/receipt.json`.
- Required `make promotion-check` full PASS:25commands/provider_operations0/full_datasetno. Log `.asterion-private/task47-p7-rollout/promotion.stdout.log`. User later authorizes the next clean trial; this implementation verification made no live game/model calls.

## Follow-up after user-stopped trial

- Stopped optional-helper trial2/9: L1 17/L2 70, one death RESET, helper unused;449.523s/87actions, cleanup/replay verified.
- L2 before42 offline conditional-risk witness and runtime measurements independently reviewed; unknown boundary remains unknown, hypothesized passable5/0+lethal15 yields dead after7ticks (~24.6ms), model/game0. Human retrospective partial model, no live predictive-capability claim.
- Final user-directed general uncertainty policy implemented only at research entry.14 existing entry-boundary tests/Ruff PASS; fresh installed wheel source/public separation PASS. No package topology/tools/runtime change; prior full promotion belongs to9bcfcce3. A new clean live trial is user-authorized; default experienceOFF.

## Approved next implementation: automatic fatal-risk screening

Task48 is stopped. No further live trial is authorized. The user now approves per-primitive automatic rollout, separate proactive-call evidence, and stopping predicted/conditional fatal actions while warning on ordinary model incompleteness. This supersedes optional-call guidance; earlier verification does not verify this follow-up.

- [x] Core worker: first reproduce missing explicit risk and death-warning loss with small unittest assertions, then add `risk_check` and orthogonal findings/coverage; retain raw fatal findings across confidence downgrades. Own `p7/rollout.py` and `tests/test_prime_p7_rollout.py`.
- [x] Integration worker: add explicit model registration, genuine call-origin records and current-frame per-action kernel execution; test missing registration, fresh batch states, fatal veto, cancellation, lock/observer safety and plan idempotency. Own P7 solver/runtime/bridge/dispatch/projection and their focused tests; do not change common Prime.
- [x] Root: update research-only guidance with registration, safety-first candidate checking and exact proactive call binding; preserve public prompt and allowlists. Own prompt, entry-boundary tests and documentation.
- [x] Astra: review lock/recovery/cancellation contracts and final implementation. Root runs focused integration, installed-wheel persistent-kernel witness, promotion check, documents implemented/verified/unverified boundaries and commits. No game/SDK/model requests. Full promotion failures remain qualified below; packaged checks and the isolated console retry are separately verified.

### Task49 verification and limits

- Core20 tests PASS, including risk before settled, copied inputs, callback failure, raw death retained after confidence downgrade and aggregated candidate attribution. New assertions reproduced missing API and missing candidate attribution before repair.
- Root final focused command: `uv run python -m unittest -q tests.test_prime_p7_rollout tests.test_prime_p7_auto_rollout tests.test_prime_p7_autonomous_solver tests.test_prime_p7_research_runtime tests.test_prime_p7_research tests.test_prime_p7_autonomous_interface tests.test_prime_p7_action_preconditions tests.test_prime_p7_solver_control tests.test_prime_p7_dispatch_deadline tests.test_prime_p7_notes_operator tests.test_prime_p7_output_config` —123 PASS/26.412s at that boundary. One additional solver generation-change assertion also passes. The final recovery-registration cleanup test first failed both success/failure subcases, then `uv run python -m unittest -q tests.test_prime_p7_auto_rollout tests.test_prime_p7_research_runtime` —28 PASS/16.530s. No further broad suite is needed for that two-line cleanup.
- Astra final code review APPROVE, including explicit invalidation after checkpoint-source restoration; failure to invalidate propagates instead of declaring recovery successful.
- First full promotion reached4700tests/394.214s with16 errors in5 existing tool-state-view tests: their minimal hosts lacked the optional rollout accounting field. Root reproduced the same16 errors, repaired optional projection with `getattr`, then `uv run python -m unittest -q tests.test_prime_p7_tool_state_view tests.test_prime_p7_auto_rollout` —13 PASS/3.959s. Astra confirms APPROVE. This does not change fatal action admission.
- Full promotion rerun reached4702tests/382.137s,4 skips, with one failure in the unchanged console process-group cleanup timing case; the original full result remains FAIL. Exact isolated retry `uv run python -m unittest -v tests.test_prime_p7_console_session.TestPrimeP7ConsoleSession.test_real_process_group_cleans_term_ignoring_child_after_parent_exit` PASS/0.148s. No console source/test or timeout was changed. A private packaging continuation re-executed the other24 original packaging/TypeScript/Rust/installed-wheel checks and replaced only full unittest discovery with the complete console module, which also passed/1.067s. All25 actual continuation commands passed, provider0/full_datasetno. This is not a new full-suite PASS. Exact requested/executed commands and retained failure-log hash are in `.asterion-private/task49-p7-auto-rollout/packaging-continuation-receipt.json`; original/rerun logs remain beside it. No third broad suite or paid game was run.
- Fresh installed wheel + `python -I` + actual PersistentIPython child PASS. All7 installed source hashes match the final checkout, including recovery cleanup. Wheel SHA256 `c6057d5ee52d7f2de0d84c1bdcf81f54bd24a72a9312c6ab2699c7974c18d6ed`; commands and evidence `.asterion-private/task49-p7-auto-rollout/installed-kernel-witness/receipt.json`. Missing models are explicitly unassessed; safe prefix runs once, fatal suffix is not dispatched; raw death stops before dispatch; RESET invalidates registration;3 actual actor calls versus6 host attempts/3 model evaluations. Four synthetic fixture dispatches are separate from zero real ARC/SDK/provider/model calls. Kernel/read server closed and child PID absent.
- Synthetic installed-kernel resource sample:14cells/0.724s total, child CPU0.116929s, peak RSS47,333,376bytes on macOS. Warm automatic checks3.458–4.006ms; first cold missing-model check49.864ms; RESET boundary0.001ms. These are local fixture costs, not live game/model-building cost or a general latency bound.
- Unknown model coverage remains a warning under the user-selected policy. A danger omitted from callbacks may still be missed. Per-step host coverage is deterministic; whether a real LLM proactively calls at every insufficiently-safe decision and whether gameplay death rate improves remain unverified. No new live run was started.
