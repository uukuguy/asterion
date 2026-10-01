# P7 Structured Cross-Level Mechanics Prior Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give P7 a bounded, auditable prior that summarizes reusable mechanics from verified earlier levels and forces a falsifiable probe on the next level.

**Architecture:** Keep prefix replay as the trusted state transfer. Add a pure prior extractor over the broker's detached history projection, expose the result through a read-only `p7_client.mechanics_prior()` method, and inject only compact workflow guidance into the prompt. The extractor reports evidence and contradictions; it never chooses actions or changes broker authority.

**Tech Stack:** Python dataclasses and mappings, native P7 broker/history contracts, unittest, Ruff.

## Global Constraints

- Preserve the direction `operator → broker/client → runner`; the prior extractor must not discover games, providers, runtimes, or credentials.
- Keep `asterion-prime-p7-next`, `list`, `describe`, and preflight provider-free behavior unchanged.
- Use only detached history fields already exposed by `ArcHistoryRecord.public_view()`; never expose prompts, raw provider payloads, private paths, or full raw frames.
- Prefix replay remains trusted and must not be counted as a model probe.
- A changed frame is evidence of an effect; only `levels_completed` increase or an authoritative terminal state proves progress.
- All extraction, paging, and rendering limits are finite and fail closed.

---

### Task 1: Add the pure mechanics-prior extractor

**Files:**
- Create: `src/asterion/applications/prime/p7/mechanics_prior.py`
- Test: `tests/test_prime_p7_mechanics_prior.py`

**Interfaces:**
- Consumes: a finite sequence of broker history public mappings.
- Produces: `build_mechanics_prior(records: Sequence[Mapping[str, object]], *, current_level: int) -> dict[str, object]`.

- [ ] **Step 1: Write failing tests**

Create synthetic level 0/1/2 records containing action/data, `changed_cell_count`, `changed_cells`, `levels_completed`, and `state`. Assert the result has deterministic `prefix_actions`, `highest_verified_level`, `current_level`, sorted per-level `action_counts`, normalized ACTION6 coordinate ranges, level-advance sequences, and candidate rules with `observed`/`repeated`/`mixed` confidence.

Also assert that one-level evidence is `observed`, the same action with effects on two levels becomes `repeated`, a changed/no-change mix becomes `mixed`, input mappings are not mutated, and private-looking keys or raw frame fields never appear in output.

- [ ] **Step 2: Run the focused test to verify failure**

Run: `uv run python -m unittest -v tests.test_prime_p7_mechanics_prior`

Expected: FAIL because `mechanics_prior.py` and `build_mechanics_prior` do not exist.

- [ ] **Step 3: Implement the bounded extractor**

Implement frozen internal records or local immutable tuples, validate only the required detached history fields, ignore malformed optional rows, and return a safe empty prior for an empty input. Group actions by `levels_completed`; summarize counts, no-effect counts, changed-cell totals, sampled changed-cell coordinates, ACTION6 min/max x/y, and sequences where `levels_completed` increases. Sort all keys and lists. Emit candidate evidence only from repeated action families, with `mixed` when the same family has both effect and no-effect observations.

Do not infer universal coordinates, routes, object identities, or hidden objective rules. Keep the returned mapping JSON-safe and bounded by fixed sample/rule limits.

- [ ] **Step 4: Run the focused test to verify pass**

Run: `uv run python -m unittest -v tests.test_prime_p7_mechanics_prior`

Expected: all extractor tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime/p7/mechanics_prior.py tests/test_prime_p7_mechanics_prior.py
git commit -m "feat(p7): extract structured cross-level mechanics prior"
```

### Task 2: Expose a read-only prior tool through the P7 client

**Files:**
- Modify: `src/asterion/applications/prime/p7/operator.py` near `_P7BrokerClient.history` and tool registration in `run_live`
- Test: `tests/test_prime_p7_mechanics_prior.py`
- Test: `tests/test_prime_p7_native_broker.py`

**Interfaces:**
- Consumes: `build_mechanics_prior`, the current broker history, and current `ArcStatus`.
- Produces: `_P7BrokerClient.mechanics_prior() -> dict[str, object]` and a rendered registry entry with signature `p7_client.mechanics_prior()`.

- [ ] **Step 1: Write failing client and registry tests**

Build a fake/native broker with a multi-level history and assert `mechanics_prior()` pages at most eight bounded pages of at most 32 records, returns the extractor mapping, and does not expose run identity or frame payloads. Assert the registry render contains the exact method signature and its description says the result is evidence, not a route.

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `uv run python -m unittest -v tests.test_prime_p7_mechanics_prior tests.test_prime_p7_native_broker`

Expected: FAIL because the client method and registry entry are absent.

- [ ] **Step 3: Implement bounded paging and safe fallback**

Add `mechanics_prior()` to `_P7BrokerClient`. Read `history(0, 32)`, then continue from the next sequence for at most eight pages or until the latest sequence is reached. Catch broker/unavailable errors and return a safe mapping with `available: false`, `reason: "history-unavailable"`, and current scalar status. Pass detached records to `build_mechanics_prior`; cap the serialized result before returning it. Register the tool alongside `tried_actions` and `last_outcome_summary`.

- [ ] **Step 4: Run focused tests to verify pass**

Run: `uv run python -m unittest -v tests.test_prime_p7_mechanics_prior tests.test_prime_p7_native_broker`

Expected: all prior/client tests PASS and existing broker tests remain green.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime/p7/operator.py tests/test_prime_p7_mechanics_prior.py tests/test_prime_p7_native_broker.py
git commit -m "feat(p7): expose mechanics prior through broker client"
```

### Task 3: Make the prompt require prior-first, probe-second reasoning

**Files:**
- Modify: `src/asterion/applications/prime/p7/prompt.py`
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Test: `tests/test_prime_p7_live_command.py`
- Test: `tests/test_prime_p7_official_operator.py`

**Interfaces:**
- Consumes: the `mechanics_prior()` tool and the existing verified prompt/tool registry.
- Produces: explicit current-level bootstrap guidance without changing legacy prompt behavior or official operator restrictions.

- [ ] **Step 1: Write failing prompt tests**

Assert the verified prompt names `p7_client.mechanics_prior()`, requires one cross-level hypothesis plus one current-level uncertainty, requires one bounded current-level probe after status/observe/prior, and says contradictions lower confidence. Assert the legacy prompt remains byte-for-byte unchanged and official mode still rejects the legacy variant.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `uv run python -m unittest -v tests.test_prime_p7_live_command tests.test_prime_p7_official_operator`

Expected: FAIL on the missing prior workflow text.

- [ ] **Step 3: Implement the verified prompt contract**

Add a compact section to `P7_SOLVE_PROMPT` immediately after the startup history guidance: call `mechanics_prior()` after `status()` and `observe()`, state one reusable-mechanic hypothesis and one level-specific uncertainty, then send one one-item `act_checked` or `act` probe with a falsifiable expectation. State that the prior is evidence only, that a contradiction must be retained, and that no probe is required after an authoritative terminal state. Register the tool in the same run-specific registry used by `build_solve_prompt`.

- [ ] **Step 4: Run focused tests to verify pass**

Run: `uv run python -m unittest -v tests.test_prime_p7_live_command tests.test_prime_p7_official_operator`

Expected: all prompt and official-boundary tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime/p7/prompt.py src/asterion/applications/prime/p7/operator.py tests/test_prime_p7_live_command.py tests/test_prime_p7_official_operator.py
git commit -m "feat(p7): require prior-first current-level probing"
```

### Task 4: Add offline post-prefix integration evidence

**Files:**
- Modify: `tests/test_prime_p7_live_command.py`
- Modify: `tests/test_prime_p7_native_provider.py` only if the existing fake runtime needs a narrow hook

**Interfaces:**
- Consumes: the verified prompt, registry, fake Pi runtime, and a replayed synthetic prefix.
- Produces: a deterministic test proving the first post-prefix model turn can read the prior and dispatch one bounded current-level probe.

- [ ] **Step 1: Write the failing integration test**

Use the existing fake runtime/worker seams rather than a live provider. Seed a broker with two completed synthetic levels, run the operator path through prompt construction, capture the first model-visible tool section, and assert it contains `mechanics_prior()` and the current-level probe contract. Have the fake model call the prior then one legal `act_checked` item; assert exactly one new action is journaled after the prefix.

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run python -m unittest -v tests.test_prime_p7_live_command`

Expected: FAIL until the prior tool is wired into the operator and prompt.

- [ ] **Step 3: Implement only the test seam needed for deterministic replay**

Reuse existing fake Pi and broker fixtures. Do not add a new provider, subprocess, model, or network dependency. Keep the synthetic action cap finite and assert that prefix replay actions are excluded from the post-prefix count.

- [ ] **Step 4: Run the integration test to verify pass**

Run: `uv run python -m unittest -v tests.test_prime_p7_live_command`

Expected: the new offline test and the existing targeted command tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_prime_p7_live_command.py tests/test_prime_p7_native_provider.py
git commit -m "test(p7): verify post-prefix prior bootstrap"
```

### Task 5: Run repository gates and one bounded live validation

**Files:**
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`

- [ ] **Step 1: Run focused implementation gates**

Run: `uv run python -m unittest -v tests.test_prime_p7_mechanics_prior tests.test_prime_p7_native_broker tests.test_prime_p7_live_command tests.test_prime_p7_official_operator && uv run ruff check src/asterion/applications/prime/p7 tests/test_prime_p7_mechanics_prior.py && git diff --check`

Expected: all named tests and Ruff pass.

- [ ] **Step 2: Record a bounded in-flight checkpoint**

Before any live run, update `RESUME-NEXT-SESSION.md` with the exact target game, prefix level, finite timeout, action cap, and hypothesis that the structured prior will cause a first post-prefix probe. Do not start a broad sweep.

- [ ] **Step 3: Run one controlled live validation**

Run the existing preflight, then one `make asterion-prime-p7-next GAME=tr87` (or the next game selected by the current strategy) with the existing finite timeout/stall controls. Success requires at least one action after the prefix and an authoritative level increase. A usage-only trace or stall receipt is recorded as external-limited/unverified.

- [ ] **Step 4: Record evidence and stop the queue**

Append the run ID, prefix action count, post-prefix action count, level result, cleanup, and model identity to `JOURNAL.md`; update the resume marker to no in-flight run. Do not claim a new verified level from a partial trace.

- [ ] **Step 5: Commit status evidence**

```bash
git add docs/status/JOURNAL.md docs/status/RESUME-NEXT-SESSION.md
git commit -m "docs(p7): record structured prior validation boundary"
```
