# Live Session Checkpoint

> Updated: 2026-08-30 15:44 +0800. **Task 8 closure recorded; next work is Phase 3 design.**

## TL;DR

- Prime system-parity integration landed as merge commit `0c40c85`, with
  parents `e895ffb` and main `262b2fd`.
- The selected Gateway retains long-running, client, ecosystem, and operation
  protocol surfaces, but independent review proved the production descriptor
  does not inject an operator-owned TypeScript operation dispatcher.
- Python long-running transport validation is closed by `a666f1c`: Task 4
  Python `90/90` and Task 3 `35/35` pass.
- Option 1A is approved in `0bf5db5` and its per-session root/child correction
  is committed in `8b7fb18`: the operator injects the sole Python
  `OperationManager` for each session, while the Prime provider owns only a
  lifecycle-managed private callback transport.
- Callback Tasks 1 and 2 are independently approved through `ef9808c`: the
  manager exposes exact immutable identity and the Python private Unix server
  validates, dispatches, redacts, drains, and removes its endpoint.
- Callback Task 3 is independently approved through `3e5872c`: the TypeScript
  client enforces the exact framed callback protocol and absolute deadline, and
  the sole production descriptor path assembles it into the Prime operation
  gateway.
- Callback Task 5 is independently approved through `8204e6d`: root and nested
  child sessions share one exact manager between provider context and host, and
  the real Node sidecar closes execute/reconcile/cancel, missing callback,
  failure/no-retry, redaction, cleanup, and zero-effect proofs.
- Callback Task 6 is independently approved through `9c00a9a`: the final HEAD
  passes 2335 Python tests, TypeScript, Rust, lint, docs, build, the 28-command
  promotion gate, and the cross-cutting review fix loop.
- Task 7 is closed at `73ef120`: H-037 passed detached verification and then
  canonical execution exactly once with 2338 Python tests plus the full
  28-command promotion gate. The disposable verification worktree is removed.
- The ledger checker reports `61 passed / 0 blocking / 2 excluded` with zero
  provider/application operations. `Verified-system-parity` and Phase 2 are
  PASS; every native row remains missing.
- Local `main` is the sole local branch and primary worktree; `origin/main`
  remains `f1316bb`. The verified final bundle preserves the pre-cleanup graph,
  while binary patches and a 14-file source archive preserve accepted dirty
  worktree state.
- All 53 obsolete worktrees, three obsolete local branches, 24 temporary
  recovery refs, and two audited artifact roots are removed from active Git and
  workspace state.

## Durable recovery boundary

- The Prime artifact lock expanded from
  `c64aecdec9ddff21fb7ed493cc1837eb68bf428fc94803a65e6c185aca0fbba3`
  to `34374afe3bbef57b6690764a174a22f2fbd3952e26cfac788c955a363a54274d`.
- The synchronized client bundle and module-lock digests are
  `5ada8386371b8b68bf2bf34b892fdee1b93ad936dfa906110901b14141b63e86`
  and `577f5ea261d515223d578673f7431fd12d141fb5160c1611315ab015892485a8`.
- The synchronized ecosystem module-lock digest is
  `4cee1b9e8a1292e92232f2cafe0872988658a27680bece3755f710ac1bad5dd2`.
- Do not invent Climb hypotheses. Canonical state ends at H-037 with
  `next_action=phase-3-native-kernel-design`; Task 8 Git closure precedes new
  design work.
- Do not instantiate `PrimeOperationGateway` with synthetic receipts or select
  an operation service from request data. Implement only the approved callback
  boundary in
  `docs/superpowers/specs/2026-08-30-prime-operation-host-callback-design.md`.
- The literal `$(getconf DARWIN_USER_TEMP_DIR)/` and
  `.task13-promotion-bin/` artifact roots remain excluded and untouched.

## Immediate next action

1. Start Phase 3 with a separate approved native-kernel design derived from the
   common verified-loop and parity scenarios.
2. Keep every native row Missing until exact native evidence exists; do not
   recreate long-lived worktrees before their branch work is ready to close.

## Ready-to-paste verification

```bash
npm --prefix packages/typescript/prime-gateway run build
npm --prefix packages/typescript/prime-gateway test
uv run python -m unittest -v tests.test_control_host tests.test_prime_control_factory tests.test_prime_long_running_parity tests.test_client_session tests.test_client_operations
uv run python -m unittest -v tests.test_prime_parity_ledger tests.test_check_prime_parity tests.test_prime_climb
uv run python tools/check_prime_parity.py --claim verified-system-parity --provider asterion.prime-gateway
git diff --check --cached
```
