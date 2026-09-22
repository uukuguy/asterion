# Executor Lifecycle Bounds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure cancellation and deadline handling bound the complete Python sidecar and Rust controlled-process lifecycles.

**Architecture:** The Python manager must treat a successfully spawned sidecar as owned before yielding, and synchronously reap its process and stderr drainer on every `__aenter__` failure or cancellation. The Rust executor uses one absolute deadline from spawn through pipe draining; deadline or cancellation kills the controlled process before reader tasks are joined.

**Tech Stack:** Python 3 `asyncio` with `unittest`; Rust 2024 with Tokio process, task, time, and Unix process-group APIs.

## Global Constraints

- Keep direct trusted-policy execution, cleared environments, finite local fixtures, and existing public protocol.
- Scope is `managed_controlled_executor.py`, `process.rs`, and their focused tests; do not change Prime application, Pi RPC, composition, or status documents.
- The controlled executor has a process-lifecycle boundary and is not an OS sandbox.

---

### Task 1: Reap a Python sidecar when entry is cancelled

**Files:**
- Modify: `tests/test_managed_controlled_executor.py`
- Modify: `src/asterion/services/managed_controlled_executor.py`

**Interfaces:**
- Consumes: `ManagedControlledExecutor.__aenter__()` and `_shutdown()`.
- Produces: cancelled entry propagates `asyncio.CancelledError` only after the started child and stderr drain task are reaped.

- [ ] **Step 1: Write the failing test**

Add an `IsolatedAsyncioTestCase` that patches `asyncio.sleep` at the entry yield, starts a real finite local child, cancels the entering task, then asserts `CancelledError`, child exit, and no pending stderr task.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest -v tests.test_managed_controlled_executor.ManagedControlledExecutorTests.test_cancelled_entry_reaps_started_child_and_stderr_task`

Expected: FAIL because cancellation after process ownership bypasses `_shutdown()`.

- [ ] **Step 3: Write minimal implementation**

Wrap post-spawn entry work in `try`/`except BaseException`, await `_shutdown()` exactly once, then re-raise; make shutdown cancellation-resilient while it owns the process and stderr task cleanup.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest -v tests.test_managed_controlled_executor`

Expected: PASS.

### Task 2: Bound Rust capture through inherited pipes

**Files:**
- Modify: `packages/rust/controlled-executor/tests/process.rs`
- Modify: `packages/rust/controlled-executor/src/process.rs`

**Interfaces:**
- Consumes: `execute_bounded()` / `execute_bounded_cancellable()`.
- Produces: `BoundedProcessOutput` returns `timed_out` or `cancelled` within the configured absolute deadline plus finite cleanup when a descendant holds stdout/stderr open.

- [ ] **Step 1: Write the failing tests**

Add Unix-only finite Python fixtures where a parent forks a descendant that retains inherited pipes after the parent exits. Assert both a 500 ms deadline and a cancellation signal return promptly with the matching status and do not wait for the descendant's sleep.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cargo test --manifest-path packages/rust/controlled-executor/Cargo.toml --test process inherited_pipe`

Expected: FAIL because capture joins wait for EOF after the parent has exited.

- [ ] **Step 3: Write minimal implementation**

Record an absolute Tokio deadline before spawn. Run parent wait and both capture joins under that one deadline, prioritize cancellation, terminate the controlled process group on expiry/cancellation, abort/reap reader tasks, and return bounded output. Preserve direct argv execution and `env_clear()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cargo test --manifest-path packages/rust/controlled-executor/Cargo.toml --test process`

Expected: PASS.

### Task 3: Verify formatting and focused lifecycle boundaries

**Files:**
- Verify: `tests/test_managed_controlled_executor.py`
- Verify: `packages/rust/controlled-executor/src/process.rs`
- Verify: `packages/rust/controlled-executor/tests/process.rs`

- [ ] **Step 1: Run focused Python verification**

Run: `uv run python -m unittest -v tests.test_managed_controlled_executor`

Expected: PASS.

- [ ] **Step 2: Run Rust format, lint, and process verification**

Run: `cargo fmt --manifest-path packages/rust/controlled-executor/Cargo.toml -- --check && cargo clippy --manifest-path packages/rust/controlled-executor/Cargo.toml -- -D warnings && cargo test --manifest-path packages/rust/controlled-executor/Cargo.toml --test process`

Expected: PASS.

## Self-Review

R5 is covered by Task 1 for Python entry cancellation and stderr-task ownership, and Task 2 for deadline and cancellation across parent exit plus inherited pipes. The plan uses concrete paths, commands, expected results, and no placeholder tasks. The listed method and result names match the existing executor interfaces.
