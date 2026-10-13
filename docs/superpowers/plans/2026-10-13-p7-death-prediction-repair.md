# P7 death prediction repair

**Goal:** Preserve fatal-risk recognition independently of terminal reconstruction and prevent actor declarations from authorizing unknown real-action probes.

**Approved scope:** The user requested implementation after Task57 completed 9/9. No new paid model/game trial or full-level repeat is authorized. The recorded Task57 wheel and raw evidence remain immutable.

**Architecture:** P7 owns the repair. Generic Prime, public protocol schemas and the game engine remain unchanged. Model callbacks express hypotheses; neither their coverage labels nor free-text risk declarations confer execution authority.

## Design and alternatives

Outcome-only backtests lose fatal recognition when a trajectory stops at an unknown boundary. Preserve compact predicted risk, findings, coverage and artifact references alongside outcome. Incomplete terminal reconstruction remains unknown/unresolved; a recognized fatal condition is independently visible.

For unknown probes, stronger wording alone cannot enforce admission. A gap allowlist alone also cannot prove reversibility because the actor supplies those classifications. Use a trusted application constructor allowance instead: `unknown_probe_action_limit=0` by default, explicitly finite and separate from the ordinary action cap. Covered actions continue normally. Unknown exploration remains possible when the application explicitly accepts a bounded risk; it is never presented as verified safe.

The existing single-step goal/risk/cost and prior-review binding remain necessary. Fresh evaluation must be valid, with a registered model/checker and explicit incomplete coverage; malformed, missing, computation-failed and unavailable assessments cannot consume this authorization. Fatal risk, stale boundaries, unknown execution, cancellation and ordinary budgets remain stronger. Spend one authorization immediately before dispatch, including an uncertain attempt; cached plan retrieval does not spend again. The allowance belongs to a newly constructed host attempt; a resume defaults to zero rather than silently inheriting a grant.

## Work and verification

- [x] Sol: add failing tests in `tests/test_prime_p7_rollout_backtests.py` and the affected feedback assertion in `tests/test_prime_p7_auto_rollout.py`; verify RED.
- [x] Sol: update `src/asterion/applications/prime/p7/rollout_runtime.py` to retain risk/coverage/findings; incomplete death comparison stays unknown, complete death matches, complete nondeath contradicts, unmapped pixels stay incomparable. Unassessed actual death is `death_not_assessed`.
- [x] Sol: add actual Solver/standard-entry failing tests in `tests/test_prime_p7_solve_rollout.py` for default denial, finite application allowance, exhaustion, cached plans, fatal/error veto and uncertain dispatch accounting; verify RED.
- [x] Sol: inject the private trusted allowance through `operator.py`, `research_runtime.py` and `solver.py`; add closed admission checks and bounded decision metadata. Do not add a plan/env/CLI authority field.
- [x] Root: synchronize `prompt.py`, TypeScript tool descriptions and packaged extension resources; describe authorization separately from safety and summarize historical risk separately from terminal outcome.
- [x] Root: recheck the saved Task57 predeath assessment and later historical traces offline, using production code. No new engine or model calls; save a private verification receipt without editing old evidence.
- [x] Astra: independently review the changed admission, authority, resource accounting, backtest classification and generic/domain boundary.
- [x] Root: run the related Python tests, TypeScript tests/resource check, lint and docs checks. Build/validate packaged resources as required, but do not claim a new live deployment without a real witness.
- [x] Root: update README/AGENTS and core durable state, commit and push the verified repair. Preserve Task57's original full-score result and its frozen policy scope.

Astra independent source review APPROVED. Saved-output production-classification replay:35originalenvelopes/31conditionalfatal/4unassessed→unknown/unresolved with original artifacts retained; actualdeath377→death_not_assessed. Final wheel source/resource identity and saved-assessment default denial PASS,0model/game/kernelcalls. Full promotion regression/live-game witness not rerun under the user's narrow offline repair authorization.

Final source commands: related Python125PASS (90Solver/runtime/probe and35backtests/auto); TypeScript115PASS/6existingexternal skips; check-resource/scopedruff/docs/diffPASS. No broad unrelated tests or paid trial.
