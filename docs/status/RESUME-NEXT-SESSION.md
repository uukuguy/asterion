# Live Session Checkpoint

> Updated: 2026-08-30 09:37 +0800. **Session remains active — not a final handoff.**

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
- Callback Task 4 is independently approved through `bd706a0`: the Python
  factory requires one identity-exact dispatcher and shares one callback-first,
  process-then-callback managed transport across both Prime clients. Production
  remains blocked at root/child composition and the real-process proof.
- The ledger checker reports `61 passed / 0 blocking / 2 excluded` with zero
  provider/application operations, but Phase 2 must not close until the
  operation production-assembly gap is resolved and independently reverified.

## Durable recovery boundary

- The Prime artifact lock expanded from
  `c64aecdec9ddff21fb7ed493cc1837eb68bf428fc94803a65e6c185aca0fbba3`
  to `34374afe3bbef57b6690764a174a22f2fbd3952e26cfac788c955a363a54274d`.
- The synchronized client bundle and module-lock digests are
  `5ada8386371b8b68bf2bf34b892fdee1b93ad936dfa906110901b14141b63e86`
  and `577f5ea261d515223d578673f7431fd12d141fb5160c1611315ab015892485a8`.
- The synchronized ecosystem module-lock digest is
  `4cee1b9e8a1292e92232f2cafe0872988658a27680bece3755f710ac1bad5dd2`.
- Do not rerun or invent Climb hypotheses. Canonical state ends at H-036 with
  `next_action=future-work-queue`.
- Do not instantiate `PrimeOperationGateway` with synthetic receipts or select
  an operation service from request data. Implement only the approved callback
  boundary in
  `docs/superpowers/specs/2026-08-30-prime-operation-host-callback-design.md`.
- The literal `$(getconf DARWIN_USER_TEMP_DIR)/` and
  `.task13-promotion-bin/` artifact roots remain excluded and untouched.

## Immediate next action

1. Continue Task 5 of
   `docs/superpowers/plans/2026-08-30-prime-operation-host-callback.md` with SDD
   plus RED -> GREEN TDD: bind exact root/child dispatchers and prove the real
   Python -> Node -> Python operation round trip.
2. Keep H-037 blocked until the real production callback round trip, full
   provider-free gates, and independent review all pass.

## Ready-to-paste verification

```bash
npm --prefix packages/typescript/prime-gateway run build
npm --prefix packages/typescript/prime-gateway test
uv run python -m unittest -v tests.test_control_host tests.test_prime_control_factory tests.test_prime_long_running_parity tests.test_client_session tests.test_client_operations
uv run python -m unittest -v tests.test_prime_parity_ledger tests.test_check_prime_parity tests.test_prime_climb
uv run python tools/check_prime_parity.py --claim verified-system-parity --provider asterion.prime-gateway
git diff --check --cached
```
