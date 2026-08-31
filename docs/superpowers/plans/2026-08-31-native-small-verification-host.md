# Native Small Verification Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing operator-owned Prime/DeepSeek bounded runtime available through the parameter-free Native small-verification action.

**Architecture:** An application-layer bridge loads private `.env` configuration and constructs an injected one-turn resolver. It delegates execution to the existing Native RLM bounded runner, reduces only a redacted receipt, and leaves all framework modules configuration-free.

**Tech Stack:** Python 3.12, `unittest`, existing Prime Native RLM experiment utilities, Native bounded-turn protocol, Make.

## Global Constraints

- Framework modules do not read `.env`, credentials, provider settings, executable paths, or mutable host state.
- The user action accepts no provider, model, cost, or deadline parameter.
- The one execution path has fixed finite limits and can perform at most one provider operation.
- Provider-free tests, `make check`, and `make promotion-check` never execute a provider.
- Public outputs and persisted evidence exclude private configuration, prompts, answers, credentials, raw provider output, and private paths.

---

## File structure

| File | Responsibility |
|---|---|
| `src/asterion/applications/dci_agent_lite/native_small_verification.py` | Private config resolution, fixed resolver, bounded host, redacted receipt projection. |
| `src/asterion/applications/dci_agent_lite/operator_config.py` | Reuse only its safe `.env` resolution conventions if a narrow shared helper is needed. |
| `tools/verify_native_verified_loop.py` | Explicit external command dispatch and public result reduction. |
| `tests/test_dci_native_small_verification.py` | Application bridge, no-secret, no-call, and receipt unit tests. |
| `tests/test_native_verified_loop_verification.py` | Public command shape and provider-free guard tests. |
| `Makefile` | Explicit bounded command separated from provider-free targets. |
| status docs | Evidence-state update after a real, authorized run only. |

### Task 1: Add the application-owned preset bridge

**Files:**
- Create: `src/asterion/applications/dci_agent_lite/native_small_verification.py`
- Create: `tests/test_dci_native_small_verification.py`

**Interfaces:**
- Produces `NativeSmallVerificationHostResolver(repo_root: Path).resolve() -> tuple[NativeBoundedReservation, NativeBoundedTurnHost]`.
- Consumes the existing private Prime Native RLM environment/model resolver and returns public-safe errors only.

- [ ] **Step 1: Write failing unit tests** for a valid fixed resolver, missing credential rejection before host construction, and public representations that exclude a sentinel secret.

- [ ] **Step 2: Run the focused test module** with `uv run python -m unittest -v tests.test_dci_native_small_verification`; expect import failure before implementation.

- [ ] **Step 3: Implement the bridge** using the existing bounded Prime RLM environment and model-selection helpers. Derive opaque provider/model digests, create a one-turn finite reservation, and make the host delegate only to the established bounded runtime path.

- [ ] **Step 4: Run the focused tests**; expect pass without a provider operation because launch functions are injected fakes.

- [ ] **Step 5: Commit** bridge and tests with `feat: add native small verification host`.

### Task 2: Reduce execution to a body-free Native receipt

**Files:**
- Modify: `src/asterion/applications/dci_agent_lite/native_small_verification.py`
- Modify: `tools/verify_native_verified_loop.py`
- Modify: `tests/test_dci_native_small_verification.py`
- Modify: `tests/test_native_verified_loop_verification.py`

**Interfaces:**
- Produces a receipt accepted only when both `rlm.generated-program` and `operation.autonomous-quality` completed under the fixed bounded reservation.
- Produces public `PASS`, `INCOMPLETE`, or `External-limited` JSON without internal fields.

- [ ] **Step 1: Write failing tests** for exact accepted receipt fields, rejection of partial or unredacted receipts, and a parameter-free public command result.

- [ ] **Step 2: Run the focused test modules**; expect the new receipt assertions to fail.

- [ ] **Step 3: Implement exact receipt reduction and CLI dispatch.** Keep ordinary `--level provider-free` pure; move true execution behind the existing explicit `small-verification` level and return a public-safe status for all host failures.

- [ ] **Step 4: Run focused tests and `make test.native-verified-loop.provider-free`**; expect pass with zero external operations.

- [ ] **Step 5: Commit** receipt/CLI changes with `feat: run native small verification through operator host`.

### Task 3: Add the explicit bounded command and record truth

**Files:**
- Modify: `Makefile`
- Modify: `docs/status/PRIME-PARITY-LEDGER.md`
- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/climb/session-state.json`
- Modify: `tests/test_prime_climb.py`

**Interfaces:**
- `make verify.native-verified-loop.small` is the sole externally executing target and is excluded from `make check` and promotion checks.

- [ ] **Step 1: Write failing tests** asserting the target/CLI remains parameter-free and current truth stays External-limited until an actual receipt exists.

- [ ] **Step 2: Implement target wiring and truthful state.** Do not promote a feature merely because the host exists; promotion requires a validated result from an explicit run.

- [ ] **Step 3: Run `make test.native-verified-loop.provider-free`, `make check`, `make promotion-check`, and `git diff --check`**; expect all provider-free validation to pass with zero operations.

- [ ] **Step 4: Commit** verification-boundary/docs changes with `docs: record native small verification host boundary`.

## Self-review

The plan keeps private configuration in an application layer, reuses the only existing controlled runtime rather than adding a direct client, makes the real call explicit and finite, and requires a validated redacted receipt before promotion.
