# Live Session Checkpoint

> Updated: 2026-08-30 06:56 +0800. **Session remains active — not a final handoff.**

## TL;DR

- Prime system-parity integration landed as merge commit `0c40c85`, with
  parents `e895ffb` and main `262b2fd`.
- The selected Gateway retains long-running, client, ecosystem, and operation
  protocol surfaces, but independent review proved the production descriptor
  does not inject an operator-owned TypeScript operation dispatcher.
- Python long-running transport validation is closed by `a666f1c`: Task 4
  Python `90/90` and Task 3 `35/35` pass.
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
  an operation service from request data. No existing operator-owned dispatcher
  or reverse callback transport is available in the TypeScript descriptor path.
- The literal `$(getconf DARWIN_USER_TEMP_DIR)/` and
  `.task13-promotion-bin/` artifact roots remain excluded and untouched.

## Immediate next action

1. Decide whether to add an explicit operator-owned host callback
   transport/service for Prime operations (recommended) or withdraw the
   unreachable `operations-v1` production claim and reopen the six operation
   parity rows.
2. Amend the approved design/plan before implementation. H-037 remains blocked.

## Ready-to-paste verification

```bash
npm --prefix packages/typescript/prime-gateway run build
npm --prefix packages/typescript/prime-gateway test
uv run python -m unittest -v tests.test_control_host tests.test_prime_control_factory tests.test_prime_long_running_parity tests.test_client_session tests.test_client_operations
uv run python -m unittest -v tests.test_prime_parity_ledger tests.test_check_prime_parity tests.test_prime_climb
uv run python tools/check_prime_parity.py --claim verified-system-parity --provider asterion.prime-gateway
git diff --check --cached
```
