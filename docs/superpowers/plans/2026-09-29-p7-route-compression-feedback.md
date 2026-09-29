# P7 Route Compression Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert verified offline route shortening into generic, state-bound compression proofs that P7 can consume and validate during live solving.

**Architecture:** The optimizer will produce immutable `RouteCompressionProof` records for deletion, replacement, reorder, and collapsed-subsequence edits. The ARC oracle supplies bounded route and digest evidence; the operator serializes only proofs whose source route matches the live prefix, and the model treats them as conditional hypotheses. Official saved-submit remains separate and is the only formal score path.

**Tech Stack:** Python dataclasses, existing P7 replay oracle, JSON prompt serialization, `unittest`, Ruff.

## Global Constraints

- Keep route optimization game-neutral; no BP35 action names, coordinates, or route constants.
- Accept a proof only after baseline and candidate fresh replay both verify the same identity and terminal target.
- Do not place prompts, credentials, commands, or mutable state in manifests.
- Keep official score submission separate from local offline evidence.
- Preserve deterministic ordering, bounded prompt size, and fail-closed behavior.

---

### Task 1: Define compression proof data and candidate edit metadata

**Files:**
- Modify: `src/asterion/applications/prime/p7/optimizer.py`
- Test: `tests/test_prime_p7_optimizer.py`

**Interfaces:**
- Produce `RouteCompressionProof` with fields `kind`, `source_start`, `source_end`, `before`, `after`, `identity`, `baseline_action_count`, `candidate_action_count`, `prefix_digest`, `suffix_digest`, and `terminal_state`.
- Extend `RouteCandidate` with `proofs: tuple[RouteCompressionProof, ...] = ()` while preserving existing constructor compatibility.

- [ ] Write failing tests for a delete proof and malformed identity/action-count rejection.
- [ ] Run `uv run python -m unittest -q tests.test_prime_p7_optimizer.TestRouteOptimizer.test_route_compression_proof_for_delete` and confirm failure.
- [ ] Implement strict dataclass validation and a helper that computes canonical action spans and stable route digests.
- [ ] Run the new tests and the existing optimizer tests; expect all to pass.
- [ ] Commit: `feat(p7): add verified route compression proof records`.

### Task 2: Generate generic delete, replace, reorder, and collapse candidates

**Files:**
- Modify: `src/asterion/applications/prime/p7/optimizer.py`
- Test: `tests/test_prime_p7_optimizer.py`

**Interfaces:**
- Add `_iter_compression_candidates(route, max_removed, replacements)` yielding `(candidate, proof_span, proof_kind)` in deterministic order.
- Keep `candidate_budget` and `time_budget_seconds` bounds unchanged.

- [ ] Add fake-oracle tests for one successful candidate in each proof class.
- [ ] Run those tests and confirm failure before implementation.
- [ ] Implement candidate generation: single deletion, replacement, adjacent reorder, and contiguous subsequence collapse; deduplicate candidates by action tuple.
- [ ] Attach a proof only when `RouteResult.action_count == len(candidate)` and the candidate is shorter than baseline.
- [ ] Run `uv run python -m unittest -q tests.test_prime_p7_optimizer` and confirm all optimizer tests pass.
- [ ] Commit: `feat(p7): search generic route compression edits`.

### Task 3: Capture fresh ARC state evidence for proofs

**Files:**
- Modify: `src/asterion/applications/prime/p7/optimizer_arc.py`
- Test: `tests/test_prime_p7_optimizer.py`

**Interfaces:**
- `ArcReplayOracle.replay` continues returning `RouteResult`; add a bounded `proof_context(route)` method or equivalent internal digest helper for prefix/suffix route identity.
- `optimize_arc_route` returns `RouteCandidate.proofs` without exposing engine frames or credentials.

- [ ] Add tests proving warmup identity, action cap, and proof digests remain deterministic across fresh engines.
- [ ] Run tests and confirm the new proof assertions fail initially.
- [ ] Implement digest-only proof context from canonical actions and replay identity; never serialize frames or private paths.
- [ ] Run optimizer ARC tests and `git diff --check`.
- [ ] Commit: `feat(p7): bind compression proofs to fresh replay identity`.

### Task 4: Serialize bounded proofs into generic P7 guidance

**Files:**
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Test: `tests/test_prime_p7_live_command.py`

**Interfaces:**
- Add `_summarize_route_proofs(proofs, target_level) -> str` with a hard 16 KiB UTF-8 bound and stable JSON fields.
- `_optimize_verified_route` returns proof metadata and appends the proof section only for source/live-prefix-compatible routes.

- [ ] Add tests for proof prompt content, bounded output, redaction, and prefix mismatch fallback.
- [ ] Run the tests and confirm failure.
- [ ] Implement serialization using action names/data, edit kind, spans, counts, identity, and digests only.
- [ ] Update the prompt text to require one-at-a-time `p7_act_checked`, state confirmation, and abandonment on digest mismatch.
- [ ] Run `uv run python -m unittest -q tests.test_prime_p7_live_command`.
- [ ] Commit: `feat(p7): feed verified compression proofs to solver`.

### Task 5: Verify formal-score separation and regression boundaries

**Files:**
- Modify: `docs/superpowers/specs/2026-09-29-p7-route-causal-feedback-design.md` only if implementation wording needs correction
- Test: `tests/test_prime_p7_official.py`, `tests/test_prime_p7_solutions.py`, `tests/test_prime_p7_next_level.py`

**Interfaces:**
- Local proof metadata must never be accepted as an official receipt or promotion.
- Existing saved-submit path remains the explicit formal-score action.

- [ ] Add a regression test proving an optimized local `RouteCandidate` cannot create an official receipt without saved-submit.
- [ ] Run the focused P7 suite and confirm the boundary.
- [ ] Run `make lint` and `git diff --check`.
- [ ] Run `uv run python -m unittest -q tests.test_prime_p7_live_command tests.test_prime_p7_optimizer tests.test_prime_p7_guest tests.test_prime_p7_native_replay tests.test_prime_p7_action_feedback tests.test_prime_p7_next_level tests.test_prime_p7_official tests.test_prime_p7_solutions`.
- [ ] Commit: `test(p7): verify compression proof and score boundaries`.

### Task 6: Record evidence and prepare one controlled validation run

**Files:**
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/status/DECISIONS.md` only if the proof boundary changes the active decision

- [ ] Journal each implementation commit and the final focused verification.
- [ ] Confirm `git status --short` is empty and no P7 process remains.
- [ ] Run one controlled offline P7 validation only after all tests pass; record whether the model used a proof, ignored it, or diverged from it.
- [ ] Do not claim a scorecard change unless official saved-submit returns a closed-confirmed result.
- [ ] Commit the final state journal entry.
