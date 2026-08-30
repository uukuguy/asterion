# Live Session Checkpoint

> Updated: 2026-08-30 19:04 +0800. **Session remains active — not a final handoff.**

## TL;DR

- Prime Gateway `Verified-system-parity` remains closed at H-037: 61 mandatory
  features passed, zero blocking, two reviewed exclusions, and zero
  provider/application operations.
- Git recovery remains closed on the sole local `main` branch and primary
  worktree; no implementation branch or worktree has been opened.
- The Phase 3.1 Native durable-controller design was approved at `ac1e9ef`.
- The implementation plan is complete at `d1c4723` in
  `docs/superpowers/plans/2026-08-30-asterion-native-controller-core.md`.
  It contains ten TDD tasks from dormant H-038 setup through provider binding,
  common/differential/host/crash verification, and exact H-038 closure.
- Planning self-review corrected the create-event contract: `session.created`
  already initializes the active goal, so Native must not emit a duplicate
  `goal.updated(active)`.
- H-038 has not been opened or run, and all 61 compound `asterion.native`
  feature results remain Missing.

## Durable recovery boundary

- Root goal: complete functional reproduction of the 61 mandatory Prime
  features in `asterion.native` at pinned commit
  `a18809e00ea30638584d87b3afea7285a9d7296c`, with zero blocking and the same
  two reviewed exclusions.
- Phase 3.1 is only the durable single-session controller substrate. Its maximum
  claim is `native-controller-core: PASS`; it cannot promote Native
  `Verified-loop`, Phase 3, or any compound parity feature.
- `ControlHost` retains canonical state, authority, admission, execution,
  settlement, cancellation, and public evidence. Native owns only its private
  journal, reducer, deterministic turns, event stream, and capsules.
- One `NativeSessionDirectory` will own the exact session lock, pinned
  descriptors, and shared total-storage budget used by both records and
  capsules. This prevents split ownership and unfinished storage resources.
- Provider turn usage is a per-turn delta internally but is published as
  cumulative `budget.reported` usage to match the closed host contract.
- Action terminal resolutions become immutable inputs to the next turn; a
  concurrent session terminal durably fences a late adapter result.
- Canonical Climb state remains H-037 with
  `next_action=phase-3-native-kernel-design` until plan execution explicitly
  opens dormant H-038.

## Immediate next action

1. Select the implementation execution mode for the approved ten-task plan.
2. Execute Task 1 on `main`, commit the dormant H-038 boundary, then proceed
   task-by-task with RED/GREEN verification and focused commits.
3. Do not run H-038 until every implementation commit, provider-free receipt,
   `make check`, `make promotion-check`, and clean-tree gate passes.
4. Finish on clean `main` with one local branch and one worktree.

## Ready-to-paste verification

```bash
make docs-check
git diff --check
git status --short --branch
git branch --format='%(refname:short)'
git worktree list --porcelain
```
