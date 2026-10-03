# P7 Chinese Cognition Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a bounded Chinese cognition narrative before structured evidence in every P7 LLM decision context.

**Architecture:** Add a pure application-level renderer for semantic cognition and session state. Attach its `cognition_narrative_zh` output to initial context and refreshable observe/action/cognition responses while retaining bounded JSON evidence and broker authority. Update the P7 prompt to read the narrative first and author new hypotheses in Chinese.

**Tech Stack:** Python 3.12, `unittest`, existing P7 operator/broker projections, packaged Prime wheel.

## Global Constraints

- `execution_authority` remains `none` for all cognition narratives.
- Broker observations and checked actions remain authoritative; the narrative cannot authorize or dispatch actions.
- Structured JSON and private JSONL evidence remain available for validation and replay.
- Narrative output is deterministically bounded and must not include credentials, prompts, raw provider payloads, or private paths.

---

### Task 1: Add the bounded Chinese cognition renderer

**Files:**
- Create: `src/asterion/applications/prime/p7/cognition_narrative.py`
- Test: `tests/test_prime_p7_cognition_narrative.py`

**Interfaces:**
- Consumes `semantic` report mappings and optional `cognition_session` mappings.
- Produces `render_cognition_narrative_zh(semantic, cognition_session, *, max_bytes=4096) -> str`.

- [x] **Step 1: Write the failing renderer tests**

```python
def test_renders_state_confirmed_open_and_next_test_in_chinese():
    text = render_cognition_narrative_zh(
        {"natural_language_context": "A movable band.", "claims": {
            "rule": [{"id": "move", "claim": "The band moves up.", "status": "certain", "next_test": "Check ACTION1."}],
            "success_condition": [{"id": "goal", "claim": "Touch the target.", "status": "undetermined", "next_test": "Test contact."}],
        }},
        {"session": {"state": "READY", "episode": 1, "episode_actions": 2}},
    )
    assert "当前游戏认知" in text
    assert "已确认" in text and "待验证" in text
    assert "READY" in text and "ACTION1" in text

def test_renderer_is_bounded_and_handles_unavailable_input():
    text = render_cognition_narrative_zh(None, None, max_bytes=512)
    assert "认知刷新不可用" in text
    assert len(text.encode("utf-8")) <= 512
```

- [x] **Step 2: Run tests and verify the missing-module failure**

Run: `uv run python -m unittest -q tests.test_prime_p7_cognition_narrative`

Expected: FAIL because the renderer module and function do not exist.

- [x] **Step 3: Implement the deterministic renderer**

Implement status labels, bounded claim selection, context normalization, and explicit unavailable text. Select at most four confirmed claims and four open claims, truncate each claim to 180 characters, and reserve bytes for the Chinese headings and state line.

- [x] **Step 4: Run renderer tests**

Run: `uv run python -m unittest -q tests.test_prime_p7_cognition_narrative`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/asterion/applications/prime/p7/cognition_narrative.py tests/test_prime_p7_cognition_narrative.py
git commit -m "feat(p7): add bounded Chinese cognition narrative"
```

### Task 2: Inject the narrative into every decision response

**Files:**
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Modify: `src/asterion/applications/prime/p7/broker.py`
- Test: `tests/test_prime_p7_live_command.py`

**Interfaces:**
- Consumes `render_cognition_narrative_zh` from Task 1.
- Produces a top-level `cognition_narrative_zh` field in planning background and attached observe/action/cognition/update results.

- [x] **Step 1: Add failing response-shape tests**

Extend the synthetic client tests to assert `planning_background["cognition_narrative_zh"]` exists, starts with `当前游戏认知`, and changes after the semantic report changes. Assert the initial prompt contains `## 当前游戏认知（中文）` before the JSON projections.

- [x] **Step 2: Run the focused tests and verify failure**

Run: `uv run python -m unittest -q tests.test_prime_p7_live_command`

Expected: FAIL because no response currently contains `cognition_narrative_zh`.

- [x] **Step 3: Attach the narrative before structured projections**

In the broker planning background, render the current semantic report/session and add `cognition_narrative_zh` beside `semantic_cognition`. In `_attach_planning_background`, preserve that field before large worldmap/frame fields. In `_initial_game_context`, add a Chinese narrative heading and text before the serialized planning JSON; use the unavailable Chinese fallback when cognition cannot be read.

- [x] **Step 4: Run focused response tests**

Run: `uv run python -m unittest -q tests.test_prime_p7_live_command tests.test_prime_p7_bridge_dispatch`

Expected: PASS, with existing response byte caps and execution authority assertions unchanged.

- [x] **Step 5: Commit**

```bash
git add src/asterion/applications/prime/p7/operator.py src/asterion/applications/prime/p7/broker.py tests/test_prime_p7_live_command.py
git commit -m "feat(p7): inject Chinese cognition into decision context"
```

### Task 3: Make the P7 prompt Chinese-first

**Files:**
- Modify: `src/asterion/applications/prime/p7/prompt.py`
- Test: `tests/test_prime_p7_live_command.py`

**Interfaces:**
- Consumes the `cognition_narrative_zh` field and initial-context heading from Task 2.
- Produces prompt instructions that require Chinese cognition proposals, experiment questions, and analysis explanations while preserving exact tool operation names and JSON contracts.

- [x] **Step 1: Add prompt contract assertions**

Assert `P7_SOLVE_PROMPT` contains the Chinese-first instruction, the `cognition_narrative_zh` field name, and the rule that structured evidence must be checked after reading the narrative.

- [x] **Step 2: Implement prompt wording**

Add a concise Chinese section before the existing detailed contract. Require Chinese for `claim`, `reason`, `falsifier`, `next_test`, `question`, and `explanation`; keep IDs, operation names, action names, and schema keys exact.

- [x] **Step 3: Run prompt and tool-contract tests**

Run: `uv run python -m unittest -q tests.test_prime_p7_live_command tests.test_prime_p7_tool_registry tests.test_prime_p7_bridge_dispatch`

Expected: PASS.

- [x] **Step 4: Commit**

```bash
git add src/asterion/applications/prime/p7/prompt.py tests/test_prime_p7_live_command.py
git commit -m "feat(p7): instruct cognition in Chinese first"
```

### Task 4: Verify packaged LLM input and update state

**Files:**
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`

- [x] **Step 1: Run the focused P7 suite and static checks**

```bash
uv run python -m unittest -q tests.test_prime_p7_cognition_narrative tests.test_prime_p7_cognition_session tests.test_prime_p7_cognition_assessment tests.test_prime_p7_bridge_dispatch tests.test_prime_p7_live_command tests.test_prime_p7_native_broker
make lint
make docs-check
```

Expected: all selected tests pass; lint and docs checks pass.

- [x] **Step 2: Run the packaged startup witness**

```bash
make asterion-prime-p7-level-witness GAME=sp80 LEVEL=1 2>&1 | tee /tmp/asterion-p7-chinese-context.log
```

Verify the terminal shows a short Chinese `当前游戏认知` line and the private run evidence contains the same narrative in the initial model context. Record the receipt without claiming a win unless `completed_level_count` advances.

- [x] **Step 3: Record evidence and commit state**

Append the test commands, packaged run ID, narrative visibility result, and actual level result to `docs/status/JOURNAL.md` and update the checkpoint in `docs/status/RESUME-NEXT-SESSION.md`. Commit the state documentation with a focused message.
