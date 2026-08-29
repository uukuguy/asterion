# Prime System-Parity Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or execute inline task-by-task with the same review gates. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Combine the verified prior session/RLM/long-running evidence with the current ecosystem, client, and operational implementation so Prime Gateway reaches exact `Verified-system-parity` at 61 PASS, zero blocking, and two exclusions.

**Architecture:** Commit the meaningful 46-PASS mixed-root snapshot, merge local `main@262b2fd` into it, and resolve only the ten preflighted conflicts by contract ownership. Promote the result to `main` only after the complete provider-free system, repository, promotion, distribution, and independent-review gates pass; then bundle and close obsolete branches and worktrees.

**Tech Stack:** Python 3.12/3.11 compatibility, TypeScript on Node 22.23.2, JSON Schema 2020-12, `unittest`, Ajv, Git merge/worktree/bundle, Rust controlled executor, repository-native Climb and project-state documents.

## Global Constraints

- Preserve `CLI/host -> selected provider -> assembly -> catalog/composer -> exact implementations -> runner -> runtime/host services`.
- Pin Prime exactly at `a18809e00ea30638584d87b3afea7285a9d7296c`.
- Keep `asterion.agent-runtime/v1`, `asterion.capability/v1`, `asterion.capability-package/v1`, and `asterion.application-assembly/v1` closed.
- Python owns orchestration and canonical state; TypeScript owns shared validation and the Prime Node boundary; Rust remains controlled execution only.
- Do not rerun a model/provider/application operation without separate finite authority and budget.
- Do not promote `Implemented`, `External-limited`, missing, or unvalidated evidence to PASS.
- Do not import the alternative branch's H-044/H-045 Climb sequence into the canonical H-001 through H-036 history.
- Do not remove a branch or worktree until the Phase 2 result is on `main` and every unique state has a verified recovery path.
- Do not push or mutate `origin/main` without separate authorization.

---

### Task 1: Freeze the 46-PASS integration snapshot

**Files:**
- Modify: the 73 currently modified tracked files shown by `git diff --name-only`
- Add: `docs/superpowers/plans/2026-08-10-asterion-prime-long-running-operations-parity.md`
- Add: `docs/superpowers/plans/2026-08-17-prime-bounded-verified-loop.md`
- Add: `packages/typescript/prime-gateway/test/long-running.test.mjs`
- Add: `src/asterion/control/long_running.py`
- Add: `src/asterion/control/providers/prime/long_running.py`
- Add: `src/asterion/control/providers/prime/resources/skills/prime-native-rlm/SKILL.md`
- Add: `tests/test_control_long_running.py`
- Add: `tests/test_prime_bounded_loop_experiment.py`
- Add: `tests/test_prime_daemon_lifecycle.py`
- Add: `tests/test_prime_long_running_experiment.py`
- Add: `tests/test_prime_long_running_parity.py`
- Add: `tools/prime_bounded_loop_experiment.py`
- Add: `tools/prime_long_running_experiment.py`
- Exclude: literal `$(getconf DARWIN_USER_TEMP_DIR)/`
- Exclude: `.task13-promotion-bin/`

**Interfaces:**
- Consumes: approved design commit `e6d072d`, diagnostic tree `bbe76e2c2e2ad2a87afb81a918bf276106342381`, and local branch `recovery/pre-consolidation-root-20260830`.
- Produces: one durable integration-snapshot commit that still evaluates to 46 PASS, 15 blocking, two excluded, and zero provider/application operations.

- [ ] **Step 1: Verify the meaningful untracked set is exact**

Run:

```bash
git ls-files --others --exclude-standard | \
  rg -v '^\$\(getconf DARWIN_USER_TEMP_DIR\)/|^\.task13-promotion-bin/'
```

Expected: exactly the thirteen source/test/plan paths listed above; the already
committed design and plan do not appear.

- [ ] **Step 2: Stage tracked changes and the exact thirteen additions**

Run `git add -u`, followed by `git add -- <path>` for each of the thirteen
listed paths. Do not use `git add .`.

Expected:

```bash
git diff --cached --name-only | wc -l
```

prints `86`, and neither excluded artifact prefix appears in the cached diff.

- [ ] **Step 3: Commit the snapshot**

Run:

```bash
git commit -m "feat: restore prior Prime parity evidence"
```

Expected: the commit includes 73 tracked modifications and thirteen additions;
the worktree retains only the two excluded artifact roots.

- [ ] **Step 4: Prove snapshot provenance**

Run:

```bash
git diff --exit-code 6b6aa8b574a8431e6a1d726354c1b39d3dbbf30a HEAD -- . \
  ':(exclude)docs/status/JOURNAL.md' \
  ':(exclude)docs/superpowers/specs/2026-08-30-prime-system-parity-integration-design.md' \
  ':(exclude)docs/superpowers/plans/2026-08-30-prime-system-parity-integration.md'
```

Expected: no output. Verify separately that the diagnostic Journal bytes are an
exact prefix of the new Journal; only the approved design, implementation-plan,
and Task 2 ordering-amendment entries may follow.

- [ ] **Step 5: Verify the pre-merge claim remains 46/15/2**

Run:

```bash
uv run python tools/check_prime_parity.py --claim verified-system-parity --provider asterion.prime-gateway
```

Expected: exit 1 with `passed_feature_count=46`,
`blocking_feature_count=15`, `excluded_feature_count=2`,
`provider_operations=0`, and `application_operations=0`.

### Task 2: Merge the H-035/H-036 line and establish a failing system gate

**Files:**
- Conflict: `docs/status/JOURNAL.md`
- Conflict: `packages/typescript/prime-gateway/src/main.ts`
- Conflict: `packages/typescript/prime-gateway/test/main.test.mjs`
- Conflict: `src/asterion/control/providers/prime/client.py`
- Conflict: `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`
- Conflict: `tests/test_check_prime_parity.py`
- Conflict: `tests/test_control_host.py`
- Conflict: `tests/test_prime_climb.py`
- Conflict: `tests/test_prime_control_factory.py`
- Conflict: `tests/test_prime_parity_ledger.py`

**Interfaces:**
- Consumes: the Task 1 snapshot and `main@262b2fdf0085294e89078a6311c9034d489e4667`.
- Produces: an explicit 61/0/2 acceptance test that first fails on the clean
  46/15/2 snapshot, one clean RED-gate commit, followed by one uncommitted
  three-way merge with exactly ten known conflicts.

- [ ] **Step 1: Add the failing combined-claim assertion**

In `tests/test_check_prime_parity.py`, replace the branch-specific blocked
assertion with this exact acceptance shape while retaining redaction checks:

```python
def test_verified_system_claim_passes_only_with_closed_union(self) -> None:
    output = io.StringIO()
    with redirect_stdout(output):
        exit_code = parity_checker.main(
            [
                "--claim",
                "verified-system-parity",
                "--provider",
                "asterion.prime-gateway",
            ]
        )

    rendered = output.getvalue()
    report = json.loads(rendered)
    self.assertEqual(exit_code, 0)
    self.assertEqual(report["status"], "PASS")
    self.assertEqual(report["passed_feature_count"], 61)
    self.assertEqual(report["blocking_feature_count"], 0)
    self.assertEqual(report["blocking_feature_ids"], [])
    self.assertEqual(report["excluded_feature_count"], 2)
    self.assertEqual(report["provider_operations"], 0)
    self.assertEqual(report["application_operations"], 0)
    self.assertNotIn("prime_evidence", rendered)
    self.assertNotIn("anchors", rendered)
    self.assertNotIn(str(ROOT), rendered)
    self.assertNotIn(PINNED_COMMIT, rendered)
```

- [ ] **Step 2: Run the new assertion RED on the clean snapshot**

Run:

```bash
uv run python -m unittest -v tests.test_check_prime_parity.TestCheckPrimeParity.test_verified_system_claim_passes_only_with_closed_union
```

Expected: FAIL because the clean snapshot reports 46 passed and fifteen
blocking features instead of the required 61/0 union. The failure must be the
new assertion, not a syntax, import, or JSON parse error.

- [ ] **Step 3: Commit the RED gate and pending Journal bookkeeping**

Stage only `tests/test_check_prime_parity.py` and the append-only Journal
entries accumulated since Task 1, then commit:

```bash
git add tests/test_check_prime_parity.py docs/status/JOURNAL.md
git commit -m "test: define Prime system parity union gate"
```

Expected: only the named acceptance test remains deliberately RED; the worktree
retains only the two excluded artifact roots. Defer the new commit's own Journal
line until resolving the merge Journal so the pre-merge tree stays clean.

- [ ] **Step 4: Start the three-way merge without committing**

Run:

```bash
git merge --no-ff --no-commit main
```

Expected: exit 1 and exactly the ten conflict paths listed above. Any additional
conflict stops the task for design review.

### Task 3: Resolve the ledger, checker, and canonical Climb state

**Files:**
- Modify: `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`
- Modify: `tests/test_check_prime_parity.py`
- Modify: `tests/test_prime_parity_ledger.py`
- Modify: `tests/test_prime_climb.py`
- Modify: `docs/status/JOURNAL.md`

**Interfaces:**
- Consumes: stable feature/scenario/evidence IDs from both merge stages.
- Produces: one canonical sorted ledger with 61 mandatory PASS rows, two exclusions, canonical H-001 through H-036 history, and an append-only Journal union.

- [ ] **Step 1: Form the ledger union by stable IDs**

For each entry in `features`, `scenarios`, and `evidence`, key by
`feature_id`, `scenario_id`, or `evidence_id`. Preserve the common metadata from
`main`; take the Prime provider result from the side where that exact feature is
already PASS. Reject duplicate keys with unequal immutable identity fields.

The resulting provider-result partition must be:

```python
EXPECTED_PROVIDER_FREE_PRIME_FEATURE_IDS = (
    "ecosystem.collision-diagnostics",
    "ecosystem.context-files",
    "ecosystem.custom-providers-models",
    "ecosystem.extension-state-commands",
    "ecosystem.extensions-lifecycle",
    "ecosystem.mcp",
    "ecosystem.packages",
    "ecosystem.prompt-templates",
    "ecosystem.skills",
    "ecosystem.tools",
    "harness.history-snapshots",
    "harness.memory-entries",
    "harness.prompt-entries",
    "harness.rollback",
    "harness.scope-isolation",
    "harness.skill-descriptions",
    "harness.subagent-specifications",
    "interface.acp",
    "interface.cli-interactive",
    "interface.export-share",
    "interface.headless-print",
    "interface.json-stream",
    "interface.rpc",
    "interface.sdk",
    "interface.tui-commands",
    "interface.tui-extension-ui",
    "operation.auth",
    "operation.controlled-update-restart",
    "operation.detach-attach-replay",
    "operation.doctor",
    "operation.goals",
    "operation.heartbeat-agent",
    "operation.heartbeat-user",
    "operation.model-selection",
    "operation.orphan-cleanup",
    "operation.resident-workers",
    "operation.restart-update-recovery",
    "operation.schedule-once-cron",
    "operation.settings-keybindings",
    "operation.telemetry-usage",
    "operation.worker-residency-eviction",
    "rlm.cancellation-teardown",
    "rlm.environment",
    "rlm.messaging",
    "rlm.recovery",
    "rlm.registry-lifecycle",
    "rlm.usage-cost",
    "session.delivery",
    "session.fork-clone",
    "session.persistence-naming",
    "session.resume-delete",
    "session.rich-attachments",
    "session.tree-navigation",
    "session.usage-status",
)
EXPECTED_BOUNDED_PRIME_FEATURE_IDS = (
    "harness.evidence-refinement",
    "operation.autonomous-quality",
    "rlm.child-model",
    "rlm.generated-program",
    "rlm.recursion-depth",
    "session.branch-summaries-labels",
    "session.compaction",
)
EXPECTED_EXTERNAL_LIMITED_PRIME_FEATURE_IDS = ()
EXPECTED_IMPLEMENTED_PRIME_FEATURE_IDS = ()
```

Do not change the two excluded feature IDs.

- [ ] **Step 2: Make the ledger test express the complete closed set**

In `tests/test_prime_parity_ledger.py`, retain
`EXPECTED_MANDATORY_BY_DOMAIN` and change result-set assertions so the union of
provider-free and bounded IDs equals `EXPECTED_MANDATORY_FEATURE_IDS` exactly:

```python
self.assertEqual(
    tuple(
        sorted(
            EXPECTED_PROVIDER_FREE_PRIME_FEATURE_IDS
            + EXPECTED_BOUNDED_PRIME_FEATURE_IDS
        )
    ),
    EXPECTED_MANDATORY_FEATURE_IDS,
)
self.assertEqual(EXPECTED_EXTERNAL_LIMITED_PRIME_FEATURE_IDS, ())
self.assertEqual(EXPECTED_IMPLEMENTED_PRIME_FEATURE_IDS, ())
```

Keep the tests that reject missing evidence identities, forged counters,
provider-free evidence for bounded scenarios, and secret-bearing fixtures.

- [ ] **Step 3: Resolve canonical Climb and Journal history**

Keep canonical `runs.csv`/hypothesis semantics through H-036 from `main` and
the earlier H-001 through H-034 supporting Journal entries from the snapshot.
Resolve `tests/test_prime_climb.py` to require cycles 1 through 36 exactly once,
with H-035 and H-036 passed and `next_action=future-work-queue` before the new
integration transition. Exclude alternative H-044/H-045 rows entirely.

Resolve `docs/status/JOURNAL.md` by retaining every pre-existing line from both
sides and appending corrections; do not rewrite a historical line.

- [ ] **Step 4: Run ledger and checker GREEN**

Run:

```bash
uv run python -m unittest -v tests.test_prime_parity_ledger tests.test_check_prime_parity tests.test_prime_climb
uv run python tools/check_prime_parity.py --claim verified-system-parity --provider asterion.prime-gateway
```

Expected: all tests PASS and the checker returns exactly 61/0/2 with zero
provider/application operations.

### Task 4: Resolve the single Gateway and Prime-client implementation

**Files:**
- Modify: `packages/typescript/prime-gateway/src/main.ts`
- Modify: `packages/typescript/prime-gateway/test/main.test.mjs`
- Modify: `src/asterion/control/providers/prime/client.py`
- Modify: `tests/test_control_host.py`
- Modify: `tests/test_prime_control_factory.py`

**Interfaces:**
- Consumes: one `PrimeControlClient`, the existing long-running coordinator, client observation/session surfaces, and the operational bridge.
- Produces: one Gateway entry point and one selected-provider translation path that expose all closed commands without acquiring authority.

- [ ] **Step 1: Resolve `main.ts` by command ownership**

Preserve one dispatch table. Its entries must include the mixed candidate's
long-running heartbeat/schedule/residency commands and `main`'s client,
ecosystem, and operation commands. Initialization order remains: validate
manifest and locks, construct private/durable stores, construct exact services,
then admit frames. No service may be selected from request payload data.

- [ ] **Step 2: Resolve the Python Prime client by translation ownership**

Keep one class/factory path. Long-running methods translate only the five
pinned heartbeat/control shapes; newer observation and operation methods retain
their exact request/receipt validators. The client performs no authorization,
retry, runtime selection, or credential lookup.

- [ ] **Step 3: Preserve both test matrices**

In `main.test.mjs`, keep long-running lifecycle/fence tests and all H-035/H-036
dispatch tests. In Python, keep host preflight failures for missing services and
factory tests for exact capability registration. Deduplicate only byte-identical
cases.

- [ ] **Step 4: Run the focused cross-language gate**

Run:

```bash
npm --prefix packages/typescript/prime-gateway run build
npm --prefix packages/typescript/prime-gateway test
uv run python -m unittest -v tests.test_control_host tests.test_prime_control_factory tests.test_prime_long_running_parity tests.test_client_session tests.test_client_operations
```

Expected: all tests PASS with no provider/model/application operation.

- [ ] **Step 5: Complete the merge commit**

Run `git diff --check`, confirm `git diff --name-only --diff-filter=U` prints
nothing, then commit:

```bash
git commit -m "feat: integrate Prime system parity evidence"
```

### Task 5: Add the H-037 Phase 2 closure transition

**Files:**
- Modify: `docs/status/climb/hypotheses.yaml`
- Modify: `docs/status/climb/runs.csv`
- Modify: `docs/status/climb/research-tree.md`
- Modify: `docs/status/climb/session-state.json`
- Modify: `tools/climb/cycle.sh`
- Modify: `tools/climb/regen-tree.py`
- Modify: `tests/test_prime_climb.py`

**Interfaces:**
- Consumes: the approved integration spec, exact 61/0/2 checker, six domain gates, and zero-operation repository gates.
- Produces: H-037 as one provider-free `prime-system-parity-integration` hypothesis and exactly one canonical transition to `phase-3-native-kernel-design`.

- [ ] **Step 1: Write failing H-037 registration and gate tests**

Add assertions that one pending H-037 hypothesis exists, that its cycle branch
contains all named domain/system/repository gates, and that the branch rejects
an existing H-037 row, a dirty tree, nonzero provider/application counts, a
changed exclusion set, and any blocking result.

Run `uv run python -m unittest -v tests.test_prime_climb`. Expected: FAIL
because H-037 is not registered or implemented.

- [ ] **Step 2: Implement and commit the dormant H-037 gate**

Register one pending hypothesis whose command list includes the exact six
domain checkers, the 61/0/2 system checker, focused ledger tests, `make check`,
promotion, and `git diff --check`. Implement the transition guards without
executing the transition. Run the focused tests GREEN, then commit:

```bash
git add docs/status/climb/hypotheses.yaml tools/climb tests/test_prime_climb.py
git commit -m "climb: prepare Prime system parity integration gate"
```

- [ ] **Step 3: Independently verify before the unique transition**

Run all H-037 commands from that clean commit in a disposable detached copy.
Expected: every command exits 0, no canonical state file changes, and no
provider/application operation is recorded. Remove the disposable copy after
capturing its command results.

- [ ] **Step 4: Prove the canonical closure assertion RED without dirtying the gate**

Add this exact canonical-state assertion:

```python
self.assertEqual(
    h037_rows,
    ["37,H-037,passed,prime-system-parity-integration"],
)
self.assertEqual(
    session_state,
    {
        "last_hypothesis": "H-037",
        "last_outcome": "passed",
        "next_action": "phase-3-native-kernel-design",
    },
)
```

Run `uv run python -m unittest -v tests.test_prime_climb`. Expected: FAIL only
because H-037 has not executed. Save the exact test diff and its digest in the
task report, then remove that new assertion with an explicit inverse patch (not
a Git reset/checkout) so the dormant gate commit is clean before execution.

- [ ] **Step 5: Execute H-037 exactly once and commit**

Run the approved transition once from the clean dormant-gate commit. Reapply
the byte-identical closure assertion, run `regen-tree.py`, verify H-037 appears
once, and run `tests.test_prime_climb` GREEN before committing:

```bash
git add docs/status/climb tools/climb tests/test_prime_climb.py
git commit -m "climb: close Prime system parity integration"
```

### Task 6: Record truthful Phase 2 closure

**Files:**
- Modify: `docs/status/PRIME-PARITY-LEDGER.md`
- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`
- Modify: `docs/status/DECISIONS.md` only if the integration establishes a new durable architectural decision

**Interfaces:**
- Consumes: named passing H-037 and repository gates.
- Produces: a structural snapshot with Phase 2 closed, the verified integration
  branch explicitly pending local-`main` promotion, and Phase 3 design as the
  only next action.

- [ ] **Step 1: Update the canonical program gates**

Mark Phase 1 `Verified-loop` and Phase 2 `Verified-system-parity` complete only
with their existing named evidence. Leave Phase 3 and Phase 4 unchecked.

- [ ] **Step 2: Update structural and recovery state**

`CURRENT-STATE.md` records the actual active integration branch, Phase 2 closed
at 61/0/2, all native rows missing, local `main` promotion still pending Task 8,
and Phase 3 design as the open theme. It contains no session narration.

`RESUME-NEXT-SESSION.md` becomes a live checkpoint naming the Phase 3 native
kernel design as the immediate next action. It must not claim native code or
native verification exists.

Append one Journal entry for the verified Phase 2 result; do not modify prior
entries.

- [ ] **Step 3: Run documentation and state verification**

Run:

```bash
make docs-check
uv run python -m unittest -v tests.test_prime_climb tests.test_prime_parity_ledger tests.test_check_prime_parity
git diff --check
```

Expected: all PASS.

- [ ] **Step 4: Commit the state transition**

Run:

```bash
git add docs/status docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md
git commit -m "docs: close Prime system parity phase"
```

### Task 7: Run full verification and independent review

**Files:**
- Create: `docs/status/PRIME-SYSTEM-PARITY-INTEGRATION-REPORT.md`
- Modify: `docs/status/JOURNAL.md` by append only

**Interfaces:**
- Consumes: the complete integration branch.
- Produces: named terminal evidence for repository, promotion, distribution, redaction, exact system parity, and independent review.

- [ ] **Step 1: Run the exact system and domain matrix**

Run the system checker and each of the six domain checkers. Expected: system
61/0/2 and every mandatory domain PASS with zero provider/application
operations.

- [ ] **Step 2: Run full repository and promotion gates**

Run under the pinned Node 22/Prime boundary:

```bash
make check
make promotion-check
make docs-check
uv build .
git diff --check
```

Expected: all exit 0; promotion reports zero provider operations and no full
dataset.

- [ ] **Step 3: Run independent review**

Review the merge base through HEAD for dependency direction, duplicate
composer/runner/provider paths, evidence inflation, authority leaks, secret
exposure, nondeterministic arrays, and invalid Phase 3/4 claims. Every finding
must be fixed and reverified before continuing.

- [ ] **Step 4: Write and commit the evidence report**

Record exact commit IDs, commands, counts, Node/Prime versions, operation
counts, review verdict, and nonclaims. Append a Journal line and commit:

```bash
git add docs/status/PRIME-SYSTEM-PARITY-INTEGRATION-REPORT.md docs/status/JOURNAL.md
git commit -m "docs: verify Prime system parity integration"
```

### Task 8: Promote main and close Git/worktree state

**Files:**
- Create outside tracked content: `.git/asterion-pre-phase3-recovery-20260830.bundle`
- Create: `docs/status/GIT-RECOVERY-CLOSURE-20260830.md`
- Remove after bundle verification: obsolete branch refs and registered non-primary worktrees

**Interfaces:**
- Consumes: verified integration HEAD, every named branch head, all detached worktree heads, and audited dirty worktree state.
- Produces: local `main` at the verified integration result plus its truthful
  main-branch state update, one clean primary worktree, a verified recovery
  bundle, and unchanged `origin/main`.

- [ ] **Step 1: Audit every dirty worktree before removal**

For each registered worktree, record HEAD, status paths, and whether each changed
blob is already reachable. If a unique source blob is not generated test output,
create a temporary recovery commit/ref after a sentinel/credential/path scan.
Do not archive virtual environments, `node_modules`, compiler caches, or private
runtime evidence. Record the complete audit in
`docs/status/GIT-RECOVERY-CLOSURE-20260830.md`.

- [ ] **Step 2: Create temporary refs for all unique preserved heads**

Create refs under `refs/recovery/pre-phase3/` for the archived ecosystem tip,
the pre-integration snapshot, alternate H-035/H-036 heads, and every accepted
dirty-worktree recovery commit. Record each ref and object ID in the verification
recovery report.

- [ ] **Step 3: Promote the verified integration commit**

Confirm the old `main@262b2fd` is reachable from a recovery ref, move local
`main` to the verified integration HEAD, switch the primary workspace to
`main`, and verify its HEAD is the exact integration commit. Do not mutate
`origin/main`.

- [ ] **Step 4: Record and verify the truthful main-branch steady state**

Update only the branch/recovery-boundary fields in `CURRENT-STATE.md` and
`RESUME-NEXT-SESSION.md`, finish the worktree/ref audit portion of the recovery
closure report, and append one Journal line. The next action remains Phase 3
native-kernel design. Run `make docs-check`, the system checker, focused
ledger/Climb tests, and `git diff --check`. Keep these documentation changes
uncommitted until the provisional bundle in Step 5 is verified.

- [ ] **Step 5: Create, record, and verify the Git bundle**

First create and verify a provisional bundle at the exact temporary path
`.git/asterion-pre-phase3-recovery-20260830.bundle.tmp`. Record its verified
heads in the recovery closure report, commit the pending main-branch state and
report, then create the final bundle from the now-final `main` plus recovery
refs:

```bash
git bundle create .git/asterion-pre-phase3-recovery-20260830.bundle.tmp \
  main recovery/pre-consolidation-root-20260830 \
  feature/prime-ecosystem-parity --glob='refs/recovery/pre-phase3/*'
git bundle verify .git/asterion-pre-phase3-recovery-20260830.bundle.tmp
git bundle list-heads .git/asterion-pre-phase3-recovery-20260830.bundle.tmp
git add docs/status/CURRENT-STATE.md docs/status/RESUME-NEXT-SESSION.md \
  docs/status/JOURNAL.md docs/status/GIT-RECOVERY-CLOSURE-20260830.md
git commit -m "docs: record Git recovery closure"
git bundle create .git/asterion-pre-phase3-recovery-20260830.bundle \
  main recovery/pre-consolidation-root-20260830 \
  feature/prime-ecosystem-parity --glob='refs/recovery/pre-phase3/*'
git bundle verify .git/asterion-pre-phase3-recovery-20260830.bundle
git bundle list-heads .git/asterion-pre-phase3-recovery-20260830.bundle
```

Expected: both provisional and final verification succeed, final `main`
including the recovery report is bundled, and every recorded recovery object
appears. Remove only the exact provisional bundle after final verification.

- [ ] **Step 6: Close registered worktrees and obsolete branches**

Remove each audited non-primary worktree by exact absolute path, then prune.
Delete `h024-ecosystem-capabilities`, `feature/prime-ecosystem-parity`, the
temporary integration branch, and temporary recovery refs after bundle
verification. Remove the exact literal `$(getconf DARWIN_USER_TEMP_DIR)/` and
`.task13-promotion-bin/` artifact roots after verifying they contain only the
previously classified cache and temporary binary files. Do not delete the
bundle.

- [ ] **Step 7: Verify the steady state**

Run:

```bash
git status --short --branch
git branch -vv
git worktree list --porcelain
git bundle verify .git/asterion-pre-phase3-recovery-20260830.bundle
git rev-parse origin/main
```

Expected: clean `main`, one local development branch, one primary worktree, a
valid recovery bundle, and unchanged `origin/main` at
`f1316bb780cf01406b99b8b549461cd02df24138`.
