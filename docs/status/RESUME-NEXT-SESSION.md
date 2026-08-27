# Live Session Checkpoint

> Updated: 2026-08-28. H-034 is closed. H-035 inventory and design are written;
> implementation is paused at the mandatory specification-review gate.

## TL;DR

- Ecosystem Task 10 closes at `3db6685`; independent re-review is clean.
- Prime Gateway `ecosystem.capabilities` is exact 10/10 PASS with zero
  provider/model operations; all native ecosystem rows remain missing.
- H-034 passed one clean cycle. `runs.csv` contains cycle 34 exactly once and
  session state points to H-035.
- Full clean evidence passed: 1,954 Python tests, TypeScript, Ruff, docs, Rust,
  sdist/wheel, and promotion 27/27 with no full dataset.
- H-035 fixes nine client features and four shared-stream evidence packages in
  design commit `7add4fb`. No implementation or system-parity claim exists.

## Current work package

- Branch: `h024-ecosystem-capabilities`.
- Completed plan:
  `docs/superpowers/plans/2026-08-10-asterion-prime-ecosystem-parity.md`.
- Design awaiting review:
  `docs/superpowers/specs/2026-08-28-asterion-prime-client-interfaces-design.md`.
- Existing unrelated working-tree changes must remain untouched.

## Verified work

- Exact domain:
  `uv run python tools/check_prime_parity.py --domain ecosystem.capabilities --provider asterion.prime-gateway`
  returned selected 10, passed 10, blocking 0.
- Exact H-034 cycle passed four ecosystem evidence gates, the domain reducer,
  `make check`, `make promotion-check`, and `git diff --check`.
- `make check`: 1,954 Python tests plus all cross-language, lint, docs, Rust,
  and distribution checks passed.
- Promotion: `promotion full PASS commands=27 provider_operations=0
  full_dataset=no`.
- Climb state: H-034 passed exactly once; next action H-035; generated tree and
  session state agree.
- Independent Task 10 re-review found no Critical, Important, or Minor issue.
- Commit-state verification passed 46 focused tests with one expected external
  source skip, exact ecosystem reduction 10/10, Climb cycles 1–34, and
  `git diff --check`.

## Next action

1. Obtain user review of the committed H-035 design specification.
2. If approved, use `writing-plans` to create the detailed client-interface
   implementation plan.
3. Do not change protocols or client implementation before that approval.
4. Keep H-035 pending until implementation and all four evidence packages pass.

## Claim boundaries

- `Verified-system-parity` remains BLOCKED on 15 `interfaces.operations` rows.
- H-035 covers the nine `interface.*` rows; the six `operation.*` rows remain a
  separate subsequent package.
- Pixel-identical TUI and hidden reasoning identity remain the only exclusions.
- No provider/model operation or full dataset run is authorized by this state.

## Ready-to-paste verification

```bash
uv run python tools/check_prime_parity.py --domain ecosystem.capabilities --provider asterion.prime-gateway
uv run python -m unittest -v tests.test_prime_ecosystem_parity tests.test_prime_parity_ledger tests.test_check_prime_parity tests.test_check_promotion
git diff --check
```
