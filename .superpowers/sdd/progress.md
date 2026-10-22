# P7 same-game world model implementation progress

- Task 1: complete (commits 4501b625..f0671e09, review clean)
- Task 2: complete (commits f06921da..32b81e7a, review clean)
- Task 3: complete (commits dd7e3ac1..3d3b72f2, review clean)
- Task 4: complete (commits 5f6e8455..2899f0ef, final review PASS; broker Pyright remediation in current closeout)
- Task 5: complete (P7 registry/bridge/extension surfaces and generic action-semantics prompt)
- Task 6: complete (fresh replay ActionExpectation gate and first-mismatch route adoption fallback)
- Task 7: complete (replay/public evidence boundaries verified; focused P7 suite 223 tests passed; repository gate completed with one unrelated offline npm-ci environment failure)

## P7 realtime console (2026-10-05)

- Task 1: complete (commits 6c494834..ed6fa64b; review clean; source events, explicit decision summary, registration; independent source review approved).
- Task 2: complete (commits 6c494834..ed6fa64b; review clean; supervisor/loopback service; independent lifecycle review approved).
- Task 3: complete (commits 6c494834..ed6fa64b; review clean; shared live UI; independent UI review approved).
- Task 4: complete within first-package boundary (final review PASS; fixes `004442f2` / `9e98b49e`; packaged run `p7-live-20261005063214-b9a30b6cbfd609490469887f` verifies decisions/actions/cognition and explicit stop/cleanup; full promotion non-PASS, browser visual acceptance external-limited, no new game completion).

## Prime standard application entry (2026-10-10, canonical Task40)

- Implementation baseline: 405feea5. Task 1 in progress; Tasks 2–8 pending.
- Task 1: d5668e8c effect-free boundary reviewed APPROVED; minor backend-validator compatibility fix in progress. Eight focused tests and Ruff pass.
- Task 3: extension/module split in progress; disjoint ownership from Task 1 validator fix. Task 2 starts after that fix.
- Task 1: complete (405feea5..ae185b25; Astra review approved, minor fix checked by root; 8 focused tests/Ruff pass).
- Task 2: active, owns application.py/private text engine/operator resolver tests. Task 3 owns disjoint TS and P1/P7 artifact producers.
- Task 2: 6fe51d20 implemented, 66 tests/Ruff pass; Astra review NEEDS FIXES: core profile file reads and pre-dispatch shared token/cost exhaustion. Implementer fixing; not complete.
- Task 2: complete (6fe51d20 + 5cc50b56; both Important findings fixed, Astra re-review approved; 67 tests/Ruff pass).
- Task 3: complete (fc225adb; Astra review approved without findings; TS 93 pass/6 external-limited, focused Python/build/installed checks pass).
- Task 4: active; Astra owns persistent runtime/bridge/workspace and P7 migration, optional transport identity check delegated within task.
- Task 4: implemented 865eea25; focused subsets pass, single broad run findings fixed in affected subsets (broad not rerun); independent Astra review pending.
- Task 4 review: NEEDS FIXES (public generic-worker injection; workspace close blocked behind active cell). Implementer fixing both with private test seam and independent worker stop/reap.
- Task 4: complete (865eea25 + 61856505; both ownership findings fixed, Astra re-review approved without findings; 60 targeted tests pass).
- Tasks 5/6: active in approved parallel wave; Task5 owns shared core/durable P1/narrator, Task6 owns P3/P4/P5 consumers.
- Task 6: complete (3d23decc; Sol independent spec PASS/quality APPROVE without findings; 51 focused tests pass). Task 7 active, Task 5 continues.
- Task 5 implemented (19eb7ee0/f6a2506d/9dcc2978), 155 focused tests pass; Astra review NEEDS FIX: blocked services.close can prevent durable independent Pi/lease cleanup. Fix in progress.
- Task 5: complete (19eb7ee0/f6a2506d/9dcc2978 + 61370a0e; independent Astra re-review approved, 155 original and64cleanup subset tests pass).
- Task 7: complete8607fd0a,61focused tests pass; Sol independent spec PASS/quality APPROVE.

- Task 8: cleanup4d489f0d complete,162focused tests pass; final domain spec PASS/quality APPROVE. Astra final contract review R1 requires cancellation-safe non-durable cleanup; fixing before final Python/promotion/live gates. TS final93 PASS/6 External-limited.

- Final contract R1 fixed37b6ab71,107focused tests PASS; Astra re-review spec PASS/quality APPROVE. Final Python155:two subTest failures in one installed legacy case(target2/7); fixture shared metrics/evidence root collision confirmed, fixing; promotion/live not started.

- Installed fixture collision fixedf1252307; final155 Python integration tests PASS after rerun. Promotion in progress, then lint/docs/live witness.

- Full promotion first4562tests/4skips/one inventory omission failure. Fixed3d3f9f10;4core-only tests PASS including no-deps wheel imports. Full promotion rerun active; source reviews remain approved.

- Final source acceptance: Sol domain/Astra contracts approved; TS93PASS/6external,Python155PASS,promotion full25commands/provider0,lint/docs PASS. Task8 finite real r11l L1 witness next; not complete until deployment evidence.

- Task8/Task40 complete: fresh-wheel r11l L1 PASS, exact Sol,1level/4actions, replay/seal/cleanup PASS;610source/wheel/resources audited independently PASS. No owned live processes; dedicated-summary behavior remains separate.

## Native DCI research example (2026-10-21)

This section is a new plan. The P7 and Prime lines above are not Tasks 1–4 of this plan.

- Plan: `docs/superpowers/plans/2026-10-21-native-dci-research-example.md`
- Branch: `native-dci-research-example`
- Worktree: `.worktrees/native-dci-research-example`
- Baseline: `014897b9`. `uv run python -m unittest -v tests.test_native_package_host` — 2 tests, OK.
- Task 1: complete (commits `014897b9`..`2b77c81f`, review clean). ⚠️ resolved: GREEN and path-assert evidence accepted from the implementer report; `make promotion-check` failed only on missing Node 22 after the path assert; later-task constraints are outside this diff.
- Task 2: complete (commits `2b77c81f`..`4d9bdf93`, review clean). ⚠️ resolved: worktree `git status --short` was empty at package time; this commit was not pushed (no upstream). Provider order stays the Task 1 registration; this commit does not touch `applications/native/`.
- Minor for final review (plan-mandated, not fixed): `application.py` host-key expression relies on operator precedence; `asterion.applications.provider` is imported twice; `_corpus()` temp dirs are removed only in the successful DCI test.
- Task 3: complete (commits `4d9bdf93`..`bd4d8db4`, review clean). No open ⚠️.
- Task 4: complete (commits `bd4d8db4`..`929e83a3`, includes `b8069cc3` and `929e83a3`, re-review clean). Live run once, exit 2, reason `pi checkout is unavailable`. Model was not called. `outputs/` absent. ⚠️ resolved: journal has one live line and the fix commit did not rerun the preset.
- Minor for final review, Task 4 re-review: `test_shell_and_makefile_are_thin` does not assert the absence of a second recipe.
- Final review: Ready to merge, no Critical or Important. Focused tests re-run: 16 OK.
- Merged fast-forward into local main at `929e83a3`. Worktree removed. Branch deleted. Not pushed. `git pull` was skipped because this repo rebases on pull and main had unpushed commits.
- ⚠️ resolved: one live run, no model evidence, not pushed.
- User decision: the live entry is the Makefile target, like Prime. The recipe supplies `--with "python-dotenv>=1.0.0"`. Do not edit `pyproject.toml`. Do not rerun the live preset.
- Minor for final review (plan-mandated, not fixed): `main` calls `repository_root()` outside the readiness handler; `execute_live` success-path wiring into `run_native_dci_research` is not directly asserted.
- Task 2 minors still open for final review: host-key precedence, duplicate provider import, `_corpus()` cleanup.
- Task 4: pending. One live `make native-dci-example` only after provider-free tests and readiness are green.

