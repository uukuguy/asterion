# Next-Session Handoff

> Updated: 2026-07-26 13:27 end of session.

## TL;DR

- Bounded DCI reproduction is implemented, independently reviewed CLEAN, and
  merged locally into `main` as `d0e8f0b`.
- Merged-state verification passed: 493 Python tests, TypeScript, Rust, builds,
  and 19 promotion commands; provider operations remained 0 and no full dataset
  ran.
- External execution remains unauthorized. The next session must obtain a fresh
  exact authorization before any Agent/Judge work.

## Where things stand

- Branch: `main`, 40 commits ahead of `origin/main`; nothing was pushed.
- The feature worktree and local feature branch were removed.
- `paper reproduce --limit N` is plan-only by default.
- Bounded evidence is `External-limited`, non-full, non-comparable, and always
  reports acceptance as not applicable.
- Dataset execution is bound to raw bytes, benchmark identity, device, and
  inode.
- Final code and security reviews report zero Critical, Important, or Minor
  findings.
- Status files contain the live handoff/state updates.

## What this session delivered

- Exact bounded selection, operation planning, one-use authority, and private
  output identity.
- Exact QA/IR/mixed Judge accounting.
- Pre-Agent dataset-content and descriptor revalidation.
- Descriptor-safe RunManifest persistence outside closed batch roots.
- Real coordinator → batch → compiler → writer → reload integration coverage.
- Body-free I/O failure handling and mutation/symlink/forgery defenses.
- Public one-query workflow and `External-limited` documentation.
- Local merge and complete worktree/branch cleanup.

## Next steps

1. Obtain fresh authorization for:
   - profile: `paper-reference/pi`
   - scope: `bright.robotics.main.full`
   - limit: `1`
   - operator-selected private output root
   - `max-agent-operations=1`
   - `max-judge-operations=1`
   - positive finite total, per-Agent, and per-Judge USD caps
2. Rerun preflight after authorization.
3. Execute once, compile/load the RunManifest, and compare it as
   `External-limited`.
4. Optionally push the local `main` history when desired.

## Don't go down these paths again

- Do not reuse earlier authorization, configuration, caches, or evidence.
- Do not treat one-query evidence as full-paper or published-score
  reproduction.
- Do not allow bounded comparisons to produce PASS.
- Do not bind only query IDs; retain raw dataset content and descriptor
  identity.
- Do not write RunManifest evidence inside closed batch roots.
- Do not bypass exact Judge-plan accounting.

## Ready-to-paste commands

```bash
git status --short --branch
git log --oneline -10

uv run asterion-dci paper describe
uv run asterion-dci paper verify
uv run asterion-dci paper reproduce \
  --profile paper-reference/pi \
  --scope bright.robotics.main.full \
  --limit 1 \
  --output-root "$(mktemp -d)/not-created"

make check
make promotion-check
```
