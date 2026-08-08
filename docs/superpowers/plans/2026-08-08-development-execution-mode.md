# Development Execution Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Pathlight coverage commands run without outer authorization files by default, while restoring exact file authorization when production mode is explicitly enabled.

**Architecture:** Add one execution-mode resolver in the Pathlight coordinator. Development returns an in-memory identity; production delegates to existing strict readers. Plan, source-lock, registry, finite budget, sequential execution, native evidence, and redaction stay unchanged.

**Tech Stack:** Python 3.12 and unittest.

## Global Constraints

- Development is default; production is only `ASTERION_DCI_REQUIRE_EXECUTION_AUTHORIZATION=1`.
- Synthetic identities are never written and contain no credentials, paths, prompts, or corpus content.
- Production omission fails before host/provider construction.

---

### Task 1: Resolve execution mode

**Files:**

- Modify: `src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py`
- Test: `tests/test_dci_pathlight_experiment_cli.py`

**Interfaces:**

- Produces `_execution_authorization(options, plan, output_root, environment) -> dict[str, object]`.
- Consumes `_read_authorization` and `_read_recovery_authorization` in production.

- [ ] Write failing tests: omitted authorization succeeds in development; omitted authorization returns code 2 before host construction with `ASTERION_DCI_REQUIRE_EXECUTION_AUTHORIZATION=1`.
- [ ] Run: `uv run python -m unittest -v tests.test_dci_pathlight_experiment_cli` and confirm the new tests fail because authorization paths are currently mandatory.
- [ ] Implement `_authorization_required` and a synthetic identity using only plan digest plus operator-root digest. Keep explicit file compatibility.
- [ ] Re-run the focused tests and commit `feat: default pathlight execution to development mode`.

### Task 2: Apply mode to every coverage command

**Files:**

- Modify: `src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py`
- Test: `tests/test_dci_pathlight_experiment_cli.py`

**Interfaces:**

- Consumes `_execution_authorization`.
- Produces development support for `execute`, `status`, `reconcile`, `prepare-recovery`, `execute-recovery`, and `status-recovery`.

- [ ] Write a failing recovery E2E test that omits both parent and recovery authorization files and asserts only Economics and SciFact run.
- [ ] Run the test and confirm failure from required authorization options.
- [ ] Make authorization options optional only when development mode is active. Reject missing production files before source-lock resolution, host construction, or provider loading.
- [ ] Run `uv run python -m unittest -v tests.test_dci_pathlight_experiment_cli` and commit `feat: permit development coverage recovery without files`.

### Task 3: Verify boundary and record operations

**Files:**

- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Test: `tests/test_dci_pathlight_experiment_cli.py`

- [ ] Add an assertion that no synthetic authorization file is written.
- [ ] Run `make check && make promotion-check`; verify no provider operation occurs.
- [ ] Record development default, production opt-in, and immediate reporting of the first real provider failure.
- [ ] Commit `docs: record development execution defaults`.
