# Prime Climb Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a tracked foreground-only climb loop and make its first cycle prove real Prime RLM lifecycle teardown without provider calls.

**Architecture:** `docs/status/climb/` is durable control-plane state; `tools/climb/` deterministically selects and records one foreground validation cycle. The real Prime fixture emits only safe boolean observations, while Python converts those observations into a provider-free RLM scenario result without promoting it to the ledger prematurely.

**Tech Stack:** Python 3.14/unittest, Node 22, TypeScript gateway, POSIX shell, JSON/YAML-like tracked state.

## Global Constraints

- Do not place model values, credentials, prompts, provider payloads, raw output, or private paths in tracked climb state.
- Do not start detached processes; every daemon must be awaited and protocol-shutdown or test-cleaned.
- Provider-free scenarios must use zero provider operations and zero credential reads.
- Preserve exact Prime gateway descriptor validation, including `rlmMaxChildren`.
- A passing local test is not permission to change an `external-limited` ledger result.

---

### Task 1: Establish deterministic climb state and foreground cycle command

**Files:**
- Create: `docs/status/climb/config.yaml`
- Create: `docs/status/climb/hypotheses.yaml`
- Create: `docs/status/climb/runs.csv`
- Create: `docs/status/climb/session-state.json`
- Create: `docs/status/climb/research-tree.md`
- Create: `tools/climb/cycle.sh`
- Create: `tools/climb/regen-tree.py`
- Test: `tests/test_prime_climb.py`

**Interfaces:**
- Consumes: `tools/climb/cycle.sh <hypothesis-id>`.
- Produces: one appended CSV result and `session-state.json` with `next_action`.

- [ ] **Step 1: Write the failing state-contract test**

```python
def test_climb_cycle_records_only_safe_provider_free_result(self):
    completed = subprocess.run(
        ["tools/climb/cycle.sh", "H-001"], cwd=ROOT, text=True,
        capture_output=True, check=False,
    )
    self.assertEqual(completed.returncode, 0, completed.stderr)
    self.assertNotIn("PRIVATE", completed.stdout + completed.stderr)
    state = json.loads((ROOT / "docs/status/climb/session-state.json").read_text())
    self.assertEqual(state["last_hypothesis"], "H-001")
    self.assertEqual(state["next_action"], "H-002")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest -v tests.test_prime_climb.TestPrimeClimb.test_climb_cycle_records_only_safe_provider_free_result`

Expected: FAIL because `tools/climb/cycle.sh` does not exist.

- [ ] **Step 3: Add tracked state and minimal foreground runner**

```sh
#!/bin/sh
set -eu
case "${1-}" in
  H-001) uv run python -m unittest -v tests.test_prime_rlm_messaging_parity ;;
  *) exit 2 ;;
esac
python3 tools/climb/regen-tree.py "$1" passed H-002
```

`regen-tree.py` must rewrite `research-tree.md`, append one CSV row with
stable fields `cycle,hypothesis_id,outcome,command_id`, and write JSON keys
`last_hypothesis`, `last_outcome`, and `next_action`.

- [ ] **Step 4: Run the state-contract test**

Run: `uv run python -m unittest -v tests.test_prime_climb.TestPrimeClimb.test_climb_cycle_records_only_safe_provider_free_result`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/status/climb tools/climb tests/test_prime_climb.py
git commit -m "feat: add Prime climb cycle state"
```

### Task 2: Make the real Prime RLM harness observe admitted lifecycle teardown

**Files:**
- Modify: `tests/fixtures/prime_gateway/v1/real-prime-rlm-messaging.mjs`
- Modify: `tests/test_prime_rlm_messaging_parity.py`
- Modify: `src/asterion/control/providers/prime/parity_testing.py`
- Test: `tests/test_prime_rlm_messaging_parity.py`

**Interfaces:**
- Consumes: the private RLM bridge client from `asterion-rlm-host-shim.mjs`.
- Produces: safe observation booleans `spawn_admitted`, `lifecycle_recorded`, and `teardown_recorded`.

- [ ] **Step 1: Extend the Python expected observation test first**

```python
self.assertEqual(payload["spawn_admitted"], True)
self.assertEqual(payload["lifecycle_recorded"], True)
self.assertEqual(payload["teardown_recorded"], True)
self.assertEqual(payload["provider_operations"], 0)
```

- [ ] **Step 2: Run the exact test to verify it fails**

Run: `uv run python -m unittest -v tests.test_prime_rlm_messaging_parity.TestPrimeRlmMessagingParity.test_real_daemon_exposes_asterion_rlm_spawn_admission`

Expected: FAIL because lifecycle fields are absent.

- [ ] **Step 3: Add only authenticated bridge lifecycle frames after spawn admission**

```js
await rlm.recordLifecycle({ type: "rlm.child.started", child_id: "rlm-child-1", native_identity_digest: createHash("sha256").update("provider-free-child").digest("hex") });
await rlm.recordLifecycle({ type: "rlm.child.terminal", child_id: "rlm-child-1", status: "cancelled" });
await rlm.recordLifecycle({ type: "rlm.child.deleted", child_id: "rlm-child-1" });
```

The fixture must expose booleans only and keep the existing private-goal
redaction assertion.  The parity adapter may treat this as a provider-free
scenario observation but must not modify the static ledger result.

- [ ] **Step 4: Run the exact test and RLM adapter tests**

Run: `uv run python -m unittest -v tests.test_prime_rlm_messaging_parity`

Expected: PASS with no provider operations and no credential reads.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/prime_gateway/v1/real-prime-rlm-messaging.mjs tests/test_prime_rlm_messaging_parity.py src/asterion/control/providers/prime/parity_testing.py
git commit -m "test: observe real Prime RLM lifecycle teardown"
```

### Task 3: Execute the first cycle and record its verified outcome

**Files:**
- Modify: `docs/status/climb/hypotheses.yaml`
- Modify: `docs/status/climb/runs.csv`
- Modify: `docs/status/climb/session-state.json`
- Modify: `docs/status/climb/research-tree.md`
- Modify: `docs/status/JOURNAL.md`

**Interfaces:**
- Consumes: `tools/climb/cycle.sh H-001`.
- Produces: H-001 terminal state and H-002 as the immediate recovery hypothesis.

- [ ] **Step 1: Execute the foreground cycle**

Run: `tools/climb/cycle.sh H-001`

Expected: exit 0 and one safe state transition.

- [ ] **Step 2: Verify the durable state and process cleanup**

Run: `git diff --check && ps -axo pid,ppid,stat,etime,command | rg -i 'prime|asterion' || true`

Expected: no surviving Prime process and no private material in tracked state.

- [ ] **Step 3: Commit cycle state**

```bash
git add docs/status/climb docs/status/JOURNAL.md
git commit -m "docs: record Prime climb lifecycle cycle"
```
