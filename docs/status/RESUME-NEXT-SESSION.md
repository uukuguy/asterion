# Next-Session Handoff

> Updated: 2026-09-18 20:50, end of session. Phase 6 P4 Tasks 9 / 14 / 15 / 16 committed; **Task 17 (witness-gated publish) awaits operator authorization**.
> HEAD: `35427ad8` clean.

## TL;DR

1. **Phase 6 (P4 rebuild) Tasks 9, 14, 15, 16 done and committed.** Tasks 1-13 were already at `3c11b994`. Three commits closed the remaining code-side gap:
   - `a2839e6` Task 9 fix: operator `recover.prior_checkpoint_sha256` reads `store.recover_checkpoint().checkpoint.digest` (was `prior_identity.continuation_id`)
   - `048078d` Task 14 commit fixture + secondary fix: operator recover-mode inherits prior's `pi_command_sha256` / `extension_binding_fingerprint` / `ceilings_sha256` (hardcoded literals only matched same-build commit+recover, broke cross-build detach+attach)
   - `ce67fa0` Task 15 Makefile `asterion-prime-p4-run` + `-verbose` supervisors with `jq -e` assertions
2. **55 P4 tests green** (52 prior + 3 operator), 105 P1/P2 regression tests green, **detachment gate 0**, ruff clean, `create_provider()` still returns 3 apps (P7/P1/P2) — P4 stays gated until Task 17 witness.
3. **Task 17 needs operator authorization** to run `make asterion-prime-p4-run` (builds a wheel + invokes Orb twice + asserts via `jq -e`). The Makefile target is in place; this is operator-bounded work the agent cannot run.
4. **Open invariants carried from Phase 5:** three pre-existing red tests (`test_pi_session`, `test_prime_p7_native_installed`, `test_core_only_install`) untouched. Project uses `project-state` for docs/status lifecycle.

## Where things stand

- **Branch**: local `main`, clean at `35427ad8` (was `3c11b994` at session start).
- **Phase 6 commits this session**:
  - `a2839e6e` `fix(prime/p4): operator recover-mode prior_checkpoint_sha256 reads prior's last sealed checkpoint digest`
  - `048078d3` `feat(prime/p4): Task 14 commit fixture + recover-mode inherits prior runtime-binding SHAs`
  - `ce67fa05` `feat(prime/p4): Task 15 Makefile asterion-prime-p4-run witness supervisor`
  - `35427ad8` `docs: Phase 6 stop at Task 17 witness gate`
- **No background processes** (no Orb VM, no Pi subprocess, no `python -m asterion`).
- **No `ASTERION_PRIME_*` env vars leaked.**
- **Plan file** still at `~/.claude/plans/serene-mixing-cat.md` (255 lines, sha256 `aa45271e531eaf55150d48011a4c88f290087c780182bb58f9988c698bf017ac`).
- **New DECISIONS entry**: `D-2026-09-18-01` records the runtime-binding SHA inheritance invariant surfaced by Task 14.

## What this session delivered

### Code

| File | Change | Why |
|---|---|---|
| `src/asterion/applications/prime/p4/operator.py` | `_recover_mode` returns 4-tuple `(prior_id, next_id, prior_checkpoint_digest, result_sha)`; captures `store.recover_checkpoint().checkpoint.digest` before worker execution; `_run_async` recover branch uses prior_checkpoint_digest for the output field | Task 9 fix: `prior_checkpoint_sha256` must equal prior's last sealed checkpoint digest, not `continuation_id` |
| `src/asterion/applications/prime/p4/operator.py` | `_build_identity` accepts `pi_command_sha256` / `extension_binding_fingerprint` / `ceilings_sha256` as kwargs with the same literals as defaults; `_recover_mode` passes prior identity's values | Task 14 secondary fix: continuation rules reject hardcoded literals when prior was sealed by a different build |
| `src/asterion/applications/prime/p4/operator.py` | Removed unused `result_sha` parameter from `_seal_commit_checkpoint`, unused `prior_identity` tuple element in `_run_async`, unused `argv` parameter on `main()` | Pyright / clean-code cleanup |
| `tests/fixtures/prime_p4/small_state.json` (new) | Pre-baked gen=1 sealed state (PrimeBackendIdentity + PrimeCheckpoint + transcript + usage, hex-encoded bytes); canonical public description; checkpoint digest `35af5974…ba72` | Task 14: enables in-process recover-mode test against a cross-build prior |
| `tests/test_asterion_prime_p4_operator.py` (new + extended) | Three tests: subprocess end-to-end + 2 fixture-based in-process (`test_recover_mode_reads_prior_checkpoint_from_fixture`, `test_recover_mode_seeded_identity_uses_random_worker`) | Task 14 consumer + regression guards for both fixes |
| `Makefile` | `asterion-prime-p4-run` + `asterion-prime-p4-run-verbose` targets; `ASTERION_PRIME_P4_PRIVATE_ROOT ?= $(CURDIR)/.asterion-private/prime-p4-witness` default | Task 15: witness supervisor with `jq -e` assertions (6 invariants) |

### State

| File | Change |
|---|---|
| `docs/status/JOURNAL.md` | 5 new lines: Task 9 fix commit, Task 14 + secondary fix commit, Task 15 commit, Task 16 sweep, Task 17 gate stop |
| `docs/status/DECISIONS.md` | New `D-2026-09-18-01` — runtime-binding SHA inheritance invariant for cross-process continuity |
| `docs/status/INDEX.md` | No change (no new docs/status files added) |

## Next steps (immediate, action-level)

1. **User-authorize witness**:
   ```
   cd /Users/sujiangwen/sandbox/agentic-2026/asterion
   make asterion-prime-p4-run
   ```
   Expected output on success:
   ```
   [asterion-prime-p4-run] native Asterion-prime P4 cross-generation continuity witness
   [asterion-prime-p4-run] witness passed: gen 1 -> 2, prior_checkpoint_sha256 matches commit checkpoint, result_sha256 differs across modes
   ```
   Exit code 2 with JSON-dump lines on failure. Override with `PRIME_ORB_MACHINE=<vm>` if needed; `make asterion-prime-p4-run-verbose` to surface Orb / python stderr.

2. **After witness exit 0**, paste the output. Agent performs the **Task-4 mirror commit** (single commit, ~3 file edits):
   - `src/asterion/applications/prime/provider.py`: append `prime_long_session_continuity_application()` to the `applications` tuple inside `create_provider()` (alphabetically between P1 `prime.ipython-coding` and P2 `prime.programmatic-long-context`).
   - `pyproject.toml`: add `prime.long-session-continuity__1.0.0` to `asterion.application_index`.
   - `tests/test_asterion_prime_p1_provider.py`: rename `test_provider_publishes_all_three_applications` → `test_provider_publishes_all_four_applications` and append the P4 tuple entry.
   - Sealed receipt sha256 should be recorded in the commit message (per the P2 / P4 pattern).
   - Final journal entry + this handoff file gets a `# Next-Session Handoff` rewrite at the next `handoff` invocation.

3. **Out-of-scope for this session** (carried forward):
   - Phase 7 (P3 rebuild) gets its own plan after Phase 6 closes.
   - Recursive continuity (gen=2→3) explicitly out of scope.
   - Source-detachment gate stays at 0.

## Don't go down these paths again (ruled out)

- `prior_checkpoint_sha256 == prior_identity.continuation_id` — wrong field; must be `store.recover_checkpoint().checkpoint.digest`.
- Hardcoded `pi_command_sha256` / `extension_binding_fingerprint` / `ceilings_sha256` in `_recover_mode` — breaks cross-build detach+attach; inherit from prior identity.
- The plan's "both `receipt_sha256` non-null" assertion is over-specified — recover does not seal a new checkpoint by design; only commit's receipt is asserted.
- Real Pi subprocess in P4 witness — fake-worker is the design.
- Child-process supervisor for the two operator invocations — two `make` Orb invocations are sufficient.
- Multi-generation recovery (gen=2→3) — out of scope.

## Workspace boundary (carried from Phase 5)

- Asterion prime must never import or depend on Prime Agent. Detachment gate stays 0.
- On the DeepSeek backend, pass no `model` to any subagent (AGENTS.md).
- `date` is the only timestamp source.
- Research intensity: review changed code + boundary assertions + small targeted regressions.
- No `python -m asterion.*` background processes may linger.

## Honest caveats carried forward

- **Task 17 has NOT run.** `make asterion-prime-p4-run` was not executed (operator-authorized work); the witness either passes or it doesn't, and the Task-4 mirror commit depends on that result.
- **Three pre-existing red tests still red** (Phase 5 closure): `tests.test_pi_session` (1F+6E), `tests.test_prime_p7_native_installed` (`Prime solver runtime did not complete`), `tests.test_core_only_install.py`.
- **The P4 witness does NOT prove model capability** — the deterministic fake-worker produces distinct result SHAs by construction. That's the design (per spec for Phase 6). Real-model invocation is P1/P7 territory.
- **Recursive continuity (gen=2→3)** is explicitly out of scope.
- **The Orb shell's path-translation** for `$(CURDIR)/.asterion-private/prime-p4-witness` was not end-to-end tested — the Makefile target was syntactically validated and the `jq -e` fragments were tested against host-runnable operator output, but the full Orb shell + wheel install + path translation chain was not exercised. If `make asterion-prime-p4-run` fails with "no such directory" or similar Orb-translation errors, the workaround is to set `ASTERION_PRIME_P4_PRIVATE_ROOT` to a path Orb translates correctly (see P1/P2 patterns in `~/.claude/CLAUDE-PRECEDENTS.md`).