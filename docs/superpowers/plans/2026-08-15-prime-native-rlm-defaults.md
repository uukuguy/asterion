# Prime Native-RLM Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the explicitly opted-in native-RLM probe runnable with secure defaults rather than operator-authored internal files.

**Architecture:** The tool module mints a narrow in-memory authority only when no advanced authority file is supplied. The CLI owns private run-root selection and keeps generic bounded verification unchanged. Both layers expose only public-safe errors.

**Tech Stack:** Python 3.12, unittest, Asterion authority value objects.

## Global Constraints

- `--native-rlm-experiment` remains mandatory and default-off.
- Model-provider calls remain absent from `make test`, `make check`, provider-free, and preflight.
- Defaults are 500,000 micros, 600,000 ms, one child, and depth one; overrides can only reduce limits.
- No prompt, credential, private path, model value, or authority document content appears in public output.

---

### Task 1: Default in-memory authorization

**Files:**
- Modify: `tests/test_prime_rlm_experiment.py`
- Modify: `tools/prime_native_rlm_experiment.py`

**Interfaces:**
- Produces `prepare_native_rlm_experiment(authority_path: Path | None, *, max_cost_micros: int | None, deadline_ms: int | None, environ: Mapping[str, str], now_ms: int | None = None) -> NativeRlmExperimentReservation`.

- [ ] Write a failing test calling `prepare_native_rlm_experiment(None, max_cost_micros=None, deadline_ms=None, ...)` and asserting the exact Prime Gateway portfolio, RLM operations, approved limits, and a digest-only model record.
- [ ] Run `uv run python -m unittest -v tests.test_prime_rlm_experiment.TestNativeRlmExperiment.test_preparation_uses_private_default_authority`; expect a signature/type failure.
- [ ] Construct the immutable envelope from fixed `PortfolioGrant` and `BudgetLimit` values, using only an opaque random authority id and a short validity window; retain loader validation when a path is supplied.
- [ ] Run the same command; expect PASS.
- [ ] Commit `feat: add native RLM default authorization`.

### Task 2: Automatic private evidence root and CLI defaults

**Files:**
- Modify: `tests/test_verify_prime_loop.py`
- Modify: `tools/verify_prime_loop.py`
- Modify: `.gitignore`
- Modify: `docs/guides/prime-control-operator-guide.md`

**Interfaces:**
- Consumes the Task 1 preparation function.
- Produces native CLI admission requiring `--source-root` and `--native-rlm-experiment`, with optional `--authority`, `--max-cost-micros`, and `--private-evidence-root`.

- [ ] Write a failing CLI test that omits all advanced arguments, patches preflight/preparation, and asserts default admission; add a test that an over-ceiling value fails before preflight.
- [ ] Run `uv run python -m unittest -v tests.test_verify_prime_loop.TestVerifyPrimeLoop.test_native_rlm_bounded_uses_defaults_after_explicit_opt_in`; expect failure because advanced arguments are still mandatory.
- [ ] Create mode-0700 `.asterion-private/prime-rlm` directories for the native command only; use the explicit root unchanged after validating it; pass `None`/approved ceiling to preparation.
- [ ] Ignore `.asterion-private/` and document required model configuration plus optional overrides without publishing private paths.
- [ ] Run the focused test commands; expect PASS.
- [ ] Commit `feat: default native RLM experiment inputs`.

### Task 3: Boundary verification

**Files:**
- Modify only files required by fixes discovered in this task.

- [ ] Run `uv run python -m unittest -v tests.test_prime_rlm_experiment tests.test_verify_prime_loop`.
- [ ] Run `make lint` and `make check`.
- [ ] Confirm the native target is not invoked by either command and no public report contains a sentinel credential or private root.
- [ ] Commit only necessary corrections with a focused message.
