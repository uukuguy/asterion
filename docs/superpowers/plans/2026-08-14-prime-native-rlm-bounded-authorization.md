# Prime Native RLM Bounded Authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a non-executing loader that admits only a finite, one-child,
one-depth native Prime RLM authorization.

**Architecture:** Keep the generic `load_bounded_authority` unchanged for
non-RLM verification. Add `load_bounded_rlm_authority` beside it: it delegates
all shared parsing and finite-budget checks to the generic loader, then applies
the three RLM-specific operation requirements and exact depth/concurrency
limits. The loader returns only an immutable `AuthorityEnvelope`; it does not
start any process or touch credentials.

**Tech Stack:** Python 3.14, `unittest`, existing `AuthorityEnvelope` and
`tools.verify_prime_loop` CLI support.

## Global Constraints

- Preserve `asterion.prime-bounded-authorization/v1`; do not introduce a new
  format or authority parser.
- Require `rlm.child.spawn`, `rlm.child.message`, and `rlm.child.delete`.
- Require `max_recursion_depth == 1` and `max_concurrent_children == 1`.
- Reuse the existing redacted `PrimeVerificationError` text for every failure.
- The loader must not invoke a daemon, sidecar, kernel, credential read, model,
  or subprocess.
- Keep `PRIME_NATIVE_RLM_MAX_DEPTH == 0`; this work must not enable native RLM
  execution.

---

### Task 1: Lock the RLM authorization acceptance and rejection matrix

**Files:**

- Modify: `tests/test_verify_prime_loop.py`
- Test: `tests/test_verify_prime_loop.py`

**Interfaces:**

- Consumes: `tools.verify_prime_loop.load_bounded_rlm_authority(path, *, max_cost_micros, now_ms=None)`.
- Produces: executable requirements for the dedicated RLM authority loader.

- [ ] **Step 1: Write the failing test**

  Add this import and test to `tests/test_verify_prime_loop.py`:

  ```python
  from tools.verify_prime_loop import load_bounded_rlm_authority

  def test_native_rlm_authority_requires_exact_capabilities_and_limits(self) -> None:
      with tempfile.TemporaryDirectory() as directory:
          root = Path(directory)
          valid = _write(
              root / "valid-rlm.json",
              _authorization(
                  allowed_operations=[
                      "application.invoke", "checkpoint.create", "child.cancel",
                      "child.message", "child.spawn", "goal.complete", "goal.fail",
                      "rlm.child.delete", "rlm.child.message", "rlm.child.spawn",
                  ],
              ),
          )
          envelope = load_bounded_rlm_authority(
              valid, max_cost_micros=1_000, now_ms=1_000
          )
          self.assertEqual(envelope.max_recursion_depth, 1)
          self.assertEqual(envelope.max_concurrent_children, 1)

          for missing in ("rlm.child.spawn", "rlm.child.message", "rlm.child.delete"):
              operations = [
                  item for item in _authorization()["authority"]["allowed_operations"]
                  if item != missing
              ]
              operations.extend(
                  item for item in ("rlm.child.delete", "rlm.child.message", "rlm.child.spawn")
                  if item != missing
              )
              with self.subTest(missing=missing), self.assertRaises(PrimeVerificationError):
                  load_bounded_rlm_authority(
                      _write(root / f"missing-{missing}.json", _authorization(allowed_operations=operations)),
                      max_cost_micros=1_000,
                      now_ms=1_000,
                  )

          for name, changes in (
              ("zero-depth", {"max_recursion_depth": 0}),
              ("deep", {"max_recursion_depth": 2}),
              ("zero-children", {"max_concurrent_children": 0}),
              ("many-children", {"max_concurrent_children": 2}),
          ):
              with self.subTest(name=name), self.assertRaises(PrimeVerificationError):
                  load_bounded_rlm_authority(
                      _write(root / f"{name}.json", _authorization(**changes)),
                      max_cost_micros=1_000,
                      now_ms=1_000,
                  )
  ```

- [ ] **Step 2: Run test to verify it fails**

  Run:

  ```bash
  uv run python -m unittest -v tests.test_verify_prime_loop.TestVerifyPrimeLoop.test_native_rlm_authority_requires_exact_capabilities_and_limits
  ```

  Expected: `ImportError` because `load_bounded_rlm_authority` does not exist.

- [ ] **Step 3: Commit the red test**

  ```bash
  git add tests/test_verify_prime_loop.py
  git commit -m "test: define bounded native rlm authority contract"
  ```

### Task 2: Implement the isolated RLM authority loader

**Files:**

- Modify: `tools/verify_prime_loop.py`
- Test: `tests/test_verify_prime_loop.py`

**Interfaces:**

- Consumes: `load_bounded_authority(path, max_cost_micros=..., now_ms=...)`.
- Produces: `load_bounded_rlm_authority(path, *, max_cost_micros, now_ms=None) -> AuthorityEnvelope`.

- [ ] **Step 1: Write minimal implementation**

  Add the required set next to `REQUIRED_BOUNDED_OPERATIONS`:

  ```python
  REQUIRED_BOUNDED_RLM_OPERATIONS = frozenset(
      {"rlm.child.delete", "rlm.child.message", "rlm.child.spawn"}
  )
  ```

  Add this function immediately after `load_bounded_authority`:

  ```python
  def load_bounded_rlm_authority(
      path: Path,
      *,
      max_cost_micros: int,
      now_ms: int | None = None,
  ) -> AuthorityEnvelope:
      try:
          envelope = load_bounded_authority(
              path, max_cost_micros=max_cost_micros, now_ms=now_ms
          )
          if (
              not REQUIRED_BOUNDED_RLM_OPERATIONS.issubset(
                  envelope.allowed_operations
              )
              or envelope.max_recursion_depth != 1
              or envelope.max_concurrent_children != 1
          ):
              raise ValueError
          return envelope
      except PrimeVerificationError:
          raise
      except (TypeError, ValueError):
          raise PrimeVerificationError(
              "Prime bounded authorization is invalid or inconsistent"
          ) from None
  ```

- [ ] **Step 2: Run the focused test to verify it passes**

  Run:

  ```bash
  uv run python -m unittest -v tests.test_verify_prime_loop.TestVerifyPrimeLoop.test_native_rlm_authority_requires_exact_capabilities_and_limits
  ```

  Expected: `OK`; no Prime process is started.

- [ ] **Step 3: Run the full authorization module tests**

  Run:

  ```bash
  uv run python -m unittest -v tests.test_verify_prime_loop
  ```

  Expected: `OK`; generic bounded authority behavior remains unchanged.

- [ ] **Step 4: Commit the implementation**

  ```bash
  git add tools/verify_prime_loop.py tests/test_verify_prime_loop.py
  git commit -m "feat: validate bounded native rlm authority"
  ```

### Task 3: Verify repository boundaries and document the completed preflight

**Files:**

- Modify: `docs/status/JOURNAL.md` (user-session state; do not include in the implementation commit)
- Modify: `docs/status/RESUME-NEXT-SESSION.md` (only if the recovery boundary changes; do not include in the implementation commit)

**Interfaces:**

- Consumes: the verified loader from Task 2.
- Produces: named verification evidence and an updated recovery boundary.

- [ ] **Step 1: Run static checks and the focused provider-free target**

  Run:

  ```bash
  uv run ruff check src tests tools
  make test.prime-rlm-spawn-admission.provider-free
  ```

  Expected: both commands pass; no provider or model operation occurs.

- [ ] **Step 2: Run the repository-wide gate**

  Run:

  ```bash
  make check
  ```

  Expected: Python tests, Ruff, docs, TypeScript, Rust, and wheel build pass.

- [ ] **Step 3: Record durable state**

  Append one ≤20-word journal line with the implementation commit hash and
  state that the loader validates only authorization; it does not enable
  native RLM execution. Rewrite the live checkpoint only if this changes the
  next recovery action.
