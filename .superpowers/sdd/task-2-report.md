# Task 2 Report: sealed npm-cache propagation

## Delivered

- Made `--npm-cache` required by the promotion CLI and threaded its canonical,
  validated path through `run_promotion`, external Prime checkout preparation,
  and operational Prime checkout preparation.
- Added `--offline --ignore-scripts --no-audit --no-fund` to every promotion
  `npm ci` command, including external Prime preparation.
- Routed default-runner npm commands in the copied project through the existing
  closed npm environment. Non-npm commands continue through the pre-existing
  runner behavior.
- Kept cache ownership external: it is neither a manifest field nor packaged
  evidence. No retry, `--prefer-offline`, or online fallback was added.

## Test evidence

TDD red phase:

```text
uv run python -m unittest -v \
  tests.test_check_promotion.PromotionCheckTests.test_external_prime_checkout_rebuilds_every_locked_workspace
FAIL: expected --offline, received online npm ci tuple
```

Green verification:

```text
uv run python -m unittest -v tests.test_check_promotion tests.test_standalone_repository
Ran 45 tests ... OK
uv run ruff check tools/check_promotion.py tests/test_check_promotion.py
All checks passed!
git diff --check
PASS
```

New/expanded focused assertions cover exact `npm ci` flags, closed
environments with canonical cache and `NPM_CONFIG_OFFLINE=true`, absence of
`--prefer-offline`, and a cache-miss failure that makes exactly one npm call.

## Scope and risk

Only `tools/check_promotion.py` and `tests/test_check_promotion.py` are
changed for implementation/testing. Existing unrelated untracked plan files
were preserved. This establishes offline npm preparation when the declared
operator cache is warm; it intentionally does not make uv, cargo, or other
non-npm commands hermetic.
