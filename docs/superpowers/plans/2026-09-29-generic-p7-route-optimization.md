# Generic P7 Action Feedback and Route Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add game-neutral action-effect feedback and bounded offline route optimization without changing broker authority or primitive action counting.

**Architecture:** Project the existing `ArcHistoryRecord` delta evidence through the operator facade as bounded feedback. Add a pure `optimizer.py` that accepts immutable actions and a caller-supplied fresh replay oracle; it proposes candidates but never executes a live broker action. Update the generic prompt for snapshot reuse, terminal stop, and feedback-driven hypotheses.

**Tech Stack:** Python 3.11+, `unittest`, dataclasses, typing protocols, existing P7 broker/history/replay contracts.

## Global Constraints

- No game IDs, coordinates, route literals, prompts, or game-specific rules in framework code or optimizer tests.
- `ArcBroker` remains the only online action authority and continues counting every primitive action.
- Optimizer code must not import `ArcBroker`, `ArcadeEngine`, provider clients, or credentials.
- Feedback must omit raw frames and remain bounded by the existing changed-cell sample and serialized tool-result limits.
- Every implementation step begins with a failing test and ends with a focused passing test.

---

### Task 1: Expose bounded per-action feedback

**Files:**
- Create: `tests/test_prime_p7_action_feedback.py`
- Modify: `src/asterion/applications/prime/p7/broker.py:300-410`
- Modify: `src/asterion/applications/prime/p7/operator.py:430-530`
- Test: `tests/test_prime_p7_native_broker.py`

**Interfaces:**
- Consumes: `ArcHistoryRecord` fields `changed_cell_count`, `changed_cells`, `changed_cells_omitted`, frame digests, levels, and state.
- Produces: `ArcBroker.act_checked()` result field `feedback: list[dict[str, object]]`; each item contains the bounded delta and the item stop reason. `_P7BrokerClient.act_checked()` forwards it unchanged.

- [ ] **Step 1: Write failing feedback tests**

```python
def test_checked_result_contains_bounded_changed_frame_feedback(self):
    broker = ArcBroker(engine=_HistoryEngine())
    broker.bind_history("run-feedback")
    result = broker.act_checked([{
        "action": {"name": "ACTION1", "data": {}},
        "expect": {"cell": {"x": 0, "y": 0, "value": 1}},
    }])
    self.assertEqual(result["feedback"][0]["changed_cell_count"], 1)
    self.assertEqual(result["feedback"][0]["changed_cells"], [[0, 0, 0, 1]])
    self.assertFalse(result["feedback"][0]["no_effect"])
    self.assertNotIn("frame", result["feedback"][0])

def test_checked_result_marks_no_effect_feedback_and_preserves_count(self):
    broker = ArcBroker(engine=_SettledNoEffectEngine())
    broker.bind_history("run-no-effect-feedback")
    result = broker.act_checked([{
        "action": {"name": "ACTION1", "data": {}},
        "expect": {"cell": {"x": 0, "y": 0, "value": 7}},
    }])
    self.assertEqual(result["feedback"][0]["changed_cell_count"], 0)
    self.assertTrue(result["feedback"][0]["no_effect"])
    self.assertEqual(result["applied_count"], 1)
```

- [ ] **Step 2: Run the focused tests and verify the intended failure**

```bash
uv run python -m unittest -v tests.test_prime_p7_action_feedback
```

Expected: FAIL because `feedback` is not present in the broker result.

- [ ] **Step 3: Implement the broker feedback projection**

In `ArcBroker.act_checked`, create a `feedback` list beside `transitions`. After each committed history record and after the item stop reason is determined, append only:

```python
{
    "changed_cell_count": record.changed_cell_count,
    "changed_cells": [list(item) for item in record.changed_cells],
    "changed_cells_omitted": record.changed_cells_omitted,
    "before_frame_sha256": record.before_frame_sha256,
    "after_frame_sha256": record.after_frame_sha256,
    "levels_completed": record.levels_completed,
    "state": record.state,
    "no_effect": record.changed_cell_count == 0,
    "stop_reason": item_stop_reason,
}
```

Return `feedback` at the top level. In `_P7BrokerClient.act_checked`, copy this list into the tool result without adding frames or private identities. Keep the existing observation and batch fields for compatibility.

- [ ] **Step 4: Run the focused tests and the existing broker matrix**

```bash
uv run python -m unittest -v tests.test_prime_p7_action_feedback tests.test_prime_p7_native_broker
```

Expected: PASS; existing action counts, no-effect guard, prediction mismatch, and terminal behavior remain unchanged.

- [ ] **Step 5: Commit the feedback slice**

```bash
git add src/asterion/applications/prime/p7/broker.py src/asterion/applications/prime/p7/operator.py tests/test_prime_p7_action_feedback.py
git commit -m "feat(p7): expose bounded action feedback"
```

### Task 2: Add an isolated generic route optimizer

**Files:**
- Create: `src/asterion/applications/prime/p7/optimizer.py`
- Create: `tests/test_prime_p7_optimizer.py`
- Test: `tests/test_prime_p7_native_replay.py`

**Interfaces:**
- Consumes: immutable `PlannerAction` tuples and a caller-provided `ReplayOracle`.
- Produces: `RouteResult`, `ReplayOracle`, `RouteCandidate`, and `optimize_route()`.

- [ ] **Step 1: Write failing optimizer tests**

```python
def test_optimizer_finds_shorter_verified_route(self):
    route = (action("A"), action("REDUNDANT"), action("B"))
    oracle = TableOracle({("A", "B"): success(2), route: success(3)})
    result = optimize_route(route, oracle, max_removed=1, candidate_budget=8)
    self.assertEqual(result.actions, (action("A"), action("B")))
    self.assertEqual(result.replay.action_count, 2)

def test_optimizer_rejects_shorter_candidate_without_terminal_success(self):
    route = (action("A"), action("B"))
    oracle = TableOracle({(): failure(0), route: success(2)})
    result = optimize_route(route, oracle, max_removed=1, candidate_budget=4)
    self.assertEqual(result.actions, route)

def test_optimizer_does_not_mutate_input_or_call_live_broker(self):
    route = (action("A"), action("B"))
    oracle = RecordingOracle(success(2))
    optimize_route(route, oracle, max_removed=1, candidate_budget=2)
    self.assertEqual(route, (action("A"), action("B")))
    self.assertEqual(oracle.live_calls, 0)
```

The test helpers use `PlannerAction(name: str, data: tuple[tuple[str, int], ...])`, not any game-specific action names or coordinates.

- [ ] **Step 2: Run the optimizer tests and verify failure**

```bash
uv run python -m unittest -v tests.test_prime_p7_optimizer
```

Expected: FAIL because `optimizer.py` does not exist.

- [ ] **Step 3: Implement immutable optimizer contracts**

Implement:

```python
@dataclass(frozen=True, slots=True)
class PlannerAction:
    name: str
    data: tuple[tuple[str, int], ...] = ()

@dataclass(frozen=True, slots=True)
class RouteResult:
    success: bool
    action_count: int
    terminal_state: str
    identity: tuple[str, int]

class ReplayOracle(Protocol):
    def replay(self, actions: tuple[PlannerAction, ...]) -> RouteResult: ...

@dataclass(frozen=True, slots=True)
class RouteCandidate:
    actions: tuple[PlannerAction, ...]
    replay: RouteResult
    removed_indices: tuple[int, ...]

def optimize_route(
    route: tuple[PlannerAction, ...],
    oracle: ReplayOracle,
    *,
    max_removed: int = 3,
    candidate_budget: int = 128,
) -> RouteCandidate: ...
```

Require the baseline replay to succeed. Enumerate combinations of removed
indices in increasing removal count, stop at `candidate_budget`, accept only
results with `success is True` and `action_count == len(candidate)`, and return
the shortest verified candidate (or the verified baseline if none improves).

- [ ] **Step 4: Run optimizer tests and replay isolation tests**

```bash
uv run python -m unittest -v tests.test_prime_p7_optimizer tests.test_prime_p7_native_replay
```

Expected: PASS; no existing replay contract changes.

- [ ] **Step 5: Commit the optimizer slice**

```bash
git add src/asterion/applications/prime/p7/optimizer.py tests/test_prime_p7_optimizer.py
git commit -m "feat(p7): add generic offline route optimizer"
```

### Task 3: Make model guidance generic and terminal-safe

**Files:**
- Modify: `src/asterion/applications/prime/p7/prompt.py:1-210`
- Modify: `src/asterion/applications/prime/p7/operator.py:1570-1610`
- Modify: `tests/test_prime_p7_live_command.py:450-520`

**Interfaces:**
- Consumes: optional application-supplied initial snapshot, optional generic candidate route, and per-action `feedback`.
- Produces: prompt text that contains no game-specific route literals and a solver that does not issue broker reads after target completion.

- [ ] **Step 1: Write failing prompt and terminal tests**

```python
def test_prompt_requires_feedback_driven_replanning(self):
    self.assertIn("changed_cell_count", P7_SOLVE_PROMPT)
    self.assertIn("stop querying", P7_SOLVE_PROMPT)

def test_generic_prompt_has_no_game_specific_route(self):
    self.assertNotIn("bp35", P7_SOLVE_PROMPT.lower())
    self.assertNotIn("45,33", P7_SOLVE_PROMPT.replace(" ", ""))
```

Add a fake terminal client test proving a completed target causes no follow-up `observe`, `status`, or `history` call.

- [ ] **Step 2: Run focused tests and verify failure**

```bash
uv run python -m unittest -v tests.test_prime_p7_live_command
```

Expected: the new prompt/terminal assertions fail against the current guidance.

- [ ] **Step 3: Update generic prompt and closeout behavior**

Replace unconditional startup reread language with a conditional rule that an
application snapshot is authoritative when present. Document the `feedback`
fields and require the model to distinguish frame change from objective
progress. Update the continuation prompt to stop immediately after the target
terminal event. Keep any candidate route wording generic and remove duplicated
route injection when the same verified candidate is already present.

Make the operator's closeout path use the terminal snapshot already returned by
the action instead of querying a closed broker.

- [ ] **Step 4: Run prompt, bridge, and live-command tests**

```bash
uv run python -m unittest -v tests.test_prime_p7_live_command tests.test_prime_p7_bridge_dispatch tests.test_prime_p7_native_provider
```

Expected: PASS with no game-specific strings in generic prompts and no post-terminal broker calls.

- [ ] **Step 5: Commit the guidance slice**

```bash
git add src/asterion/applications/prime/p7/prompt.py src/asterion/applications/prime/p7/operator.py tests/test_prime_p7_live_command.py
git commit -m "fix(p7): use generic feedback and terminal-safe guidance"
```

### Task 4: Full verification and documentation index

**Files:**
- Modify: `docs/guides/prime-p7-games-and-official-results.md` only if the generic offline optimizer needs user-facing usage text.
- Test: `tests/test_prime_p7_action_feedback.py`, `tests/test_prime_p7_optimizer.py`, and the existing P7 suite.

- [ ] **Step 1: Run focused P7 verification**

```bash
uv run python -m unittest -v tests.test_prime_p7_action_feedback tests.test_prime_p7_optimizer tests.test_prime_p7_native_broker tests.test_prime_p7_native_replay tests.test_prime_p7_live_command tests.test_prime_p7_bridge_dispatch tests.test_prime_p7_native_provider
```

Expected: PASS.

- [ ] **Step 2: Run repository validation**

```bash
make test
make lint
make check
```

Expected: PASS, or any pre-existing unrelated failure is recorded with its exact command and boundary.

- [ ] **Step 3: Confirm generic scope and clean state**

```bash
rg -n "bp35|0a0ad940|45,33|27,33|33,15" src/asterion/applications/prime/p7/optimizer.py tests/test_prime_p7_optimizer.py || true
git status --short
```

Expected: no game-specific matches in the optimizer or its tests; only intentional documentation/state changes are present before the final commit.

- [ ] **Step 4: Commit any documentation-only adjustment**

```bash
git add docs/guides/prime-p7-games-and-official-results.md
git commit -m "docs(p7): document generic route optimization"
```
