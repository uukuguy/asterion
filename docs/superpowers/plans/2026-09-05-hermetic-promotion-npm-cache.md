# Hermetic Promotion npm Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` for task-by-task implementation and review. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make promotion's npm preparation offline from one explicit operator-owned cache without admitting ambient host npm state.

**Architecture:** The CLI resolves a declared cache before launching commands. The canonical path is passed as data into closed npm environments; Prime checkout preparation and copied-project npm commands use it with explicit offline installs.

**Tech Stack:** Python 3.10, unittest, Make, GitHub Actions YAML, npm.

## Global Constraints

- Cache is operator-owned tooling, never a manifest field or packaged evidence.
- Reject relative, missing, symlink, and non-directory roots before execution.
- Do not propagate HOME, `.npmrc`, proxies, tokens, or ambient npm variables.
- No online or `--prefer-offline` fallback.
- Claim only: npm preparation is offline given a warm declared cache.

---

### Task 1: Validate the declared cache and construct the npm environment

**Files:**
- Modify: `tools/check_promotion.py:470-590`
- Modify: `tests/test_check_promotion.py`

**Interfaces:**
- Produces `_resolve_promotion_npm_cache(raw: str) -> Path`.
- Produces `_closed_npm_subprocess_environment(workspace: Path, npm_cache: Path) -> dict[str, str]`.

- [ ] **Step 1: Write failing tests**

Add subtests for relative, missing, and symlink cache roots. Assert each raises
`PromotionError` before a runner observes a command. Add a hostile environment
test which requires only the resolved cache, `NPM_CONFIG_OFFLINE=true`, and
the fixed registry, while rejecting proxy, token, HOME, and npm config values.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest -v tests.test_check_promotion`

Expected: FAIL because cache validation and the restricted npm environment do
not exist.

- [ ] **Step 3: Implement minimal validation**

Resolve only an absolute existing non-symlink directory, returning a canonical
`Path`; map every invalid form to the one redacted `PromotionError`. Build the
npm environment from `_closed_prime_subprocess_environment`, replacing only
its private cache with the canonical declared cache and adding offline plus the
fixed registry.

- [ ] **Step 4: Run focused verification**

Run: `uv run python -m unittest -v tests.test_check_promotion`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add tools/check_promotion.py tests/test_check_promotion.py && git commit -m "feat(promotion): validate declared offline npm cache"`

### Task 2: Thread the cache through each npm installation

**Files:**
- Modify: `tools/check_promotion.py:477-483, 777-910, 1130-1305`
- Modify: `tests/test_check_promotion.py:150-250, 450-510, 680-730`

**Interfaces:**
- Consumes `npm_cache: Path` from `main()` through `run_promotion()` and both
  Prime checkout preparation functions.
- Produces exact npm install commands containing `--offline --ignore-scripts
  --no-audit --no-fund`.

- [ ] **Step 1: Write failing propagation tests**

Assert recorded Prime preparation and copied-project `npm ci` tuples have all
four flags. Capture each npm environment and assert it contains the canonical
cache and offline flag. Assert no tuple contains `--prefer-offline`, and a
cache-miss failure causes no second online attempt.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest -v tests.test_check_promotion.PromotionCheckTests.test_external_prime_checkout_rebuilds_every_locked_workspace`

Expected: FAIL because existing `npm ci` is online.

- [ ] **Step 3: Implement explicit threading**

Add required `--npm-cache` parsing in `main()`, pass its canonical `Path`
through the promotion entry point and both Prime checkout preparation flows.
Use a runner closure that selects the closed npm environment only for npm
commands in the copied project; preserve existing non-npm runner behavior.
Do not add retries or fallbacks.

- [ ] **Step 4: Run focused verification**

Run: `uv run python -m unittest -v tests.test_check_promotion tests.test_standalone_repository`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add tools/check_promotion.py tests/test_check_promotion.py tests/test_standalone_repository.py && git commit -m "feat(promotion): run npm preparation from sealed cache"`

### Task 3: Declare the operator and CI contract

**Files:**
- Modify: `Makefile:1-80`
- Modify: `.github/workflows/ci.yml:12-26`
- Modify: `README.md:205-225`
- Modify: `tests/test_standalone_repository.py`

**Interfaces:**
- Make passes `ASTERION_PROMOTION_NPM_CACHE` as `--npm-cache`.
- CI restores or provisions a lock-keyed cache resource before promotion.

- [ ] **Step 1: Write failing contract tests**

Assert Make contains `ASTERION_PROMOTION_NPM_CACHE` and `--npm-cache`. Assert
the README says the cache is operator-owned and that a cache miss fails rather
than accessing the network.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest -v tests.test_standalone_repository`

Expected: FAIL because no declared-cache contract is currently exposed.

- [ ] **Step 3: Implement the contract**

Make passes exactly one cache argument. CI restores/provisions that cache as a
tool resource keyed by the relevant lockfiles before the promotion target.
README documents that a cold cache is configuration failure, not a network
fallback, and does not promise cacheless offline promotion.

- [ ] **Step 4: Run static and contract verification**

Run: `uv run python -m unittest -v tests.test_standalone_repository tests.test_check_promotion && uv run ruff check tools/check_promotion.py tests/test_check_promotion.py tests/test_standalone_repository.py && git diff --check`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add Makefile .github/workflows/ci.yml README.md tests/test_standalone_repository.py && git commit -m "docs(promotion): declare offline npm cache contract"`

## Final verification

Run focused checks above. With a known populated cache, run:

`ASTERION_PROMOTION_NPM_CACHE="$(npm config get cache)" make promotion-check`

Record its actual exit status; never promote an incomplete full-suite or
non-npm infrastructure check to PASS.
