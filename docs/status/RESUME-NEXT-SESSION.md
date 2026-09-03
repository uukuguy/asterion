# Live Session Checkpoint

> Updated: 2026-09-03 12:12. **Session remains active — not a final handoff.**

## TL;DR

- Product 2 programmatic long context is committed at `4639d11`.
- Product 3 recursive workflow is now provider-free E2E PASS:
  receipt `db6fdeb`, strict report binding `e21b8a5`, real compatibility
  witness `cb7bab3`, and native lifecycle/zero-resource verification
  `8d3978f`.
- A real local daemon run returned `PASS supported 2 2 2 2 2`: two bound
  children, root-to-child messages, child-to-root results, terminals, and
  deletions. No model/provider invocation occurred.
- Product 5's one-call model run completed, but it ran trusted-local. It is
  valuable operational evidence, not formal restricted-worker acceptance.

## Current decision

- Prime is an IPython-only action surface with recursive `rlm(...)` and a
  versioned Continual Harness—not generic Native/DCI parity.
- Provider-free recursive mechanics use zero token/cost resources with a
  finite positive deadline. This is correct only for the no-model mechanical
  scenario; future model-bearing child work must have explicit child budgets.
- Product 3 receipt still cannot claim sandboxing, model work, generated
  programs, arbitrary recursion, or native-Linux isolation.
- The capability specification requires an injected restricted worker for all
  seven formal acceptance products. Existing worker gating and Docker launcher
  are hard-coded to `prime.ipython-coding`, so they cannot yet attest Products
  2–7. Product-level `bounded-sandboxed` receipts must not be emitted from the
  trusted-local P5/P6 experiment receipts.

## Verification evidence

- Python: 28 tests across recursive receipt/compatibility, RLM adapter, and
  RLM messaging parity passed.
- Node: 37 Prime gateway main tests passed, including zero-resource native RLM
  budget clamping and expiry rejection.
- Ruff, Pyright, Node syntax, and `git diff --check` passed.
- `make promotion-check` remains **not PASS** (stopped before unapproved
  Climb H-001); `make test` remains red on a pre-existing DCI packaged-
  assembly inventory expectation.

## Immediate next action

1. Generalize the application-owned restricted worker role and public
   attestation binding across the seven exact product scenario IDs without
   relaxing Docker/platform policy. Then remove the invalid P5 trusted-local
   `bounded-sandboxed` receipt projection.
2. Retain Products 2–4 as provider-free, trusted-local mechanics only.
3. Only after a real restricted-worker runner exists, re-run Product 5 and
   authorize a separate Product 6 bounded refinement. ARC-AGI-3 remains
   unimplemented and requires a later isolated broker/functional-subset design.

## Recovery commands

```bash
git status --short
git log --oneline -12
make test.prime-long-running.provider-free
uv run python -m unittest -v tests.test_prime_bounded_autonomy_receipt
node --test packages/typescript/prime-gateway/test/main.test.mjs
```
