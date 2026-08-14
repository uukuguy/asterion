# Prime Native RLM Bounded Model Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or inline TDD execution to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one separately named, one-shot Prime native-RLM model experiment whose admission, cost/deadline ceiling, cancellation, teardown, and evidence are independently verifiable.

**Architecture:** Keep generic framework modules untouched. A Prime-provider-private experiment module receives an already resolved authority and injected private configuration, derives a redacted configuration digest, reserves one run, and owns only its daemon/sidecar children. `tools/verify_prime_loop.py` becomes the explicit command-line gate: provider-free and ordinary bounded levels remain model-free; the new level must require the experiment inputs and can never be reached by default test targets.

**Tech Stack:** Python 3.14, `unittest`, existing Prime derived runtime/sidecar, `asyncio`, closed JSON records, Node 22 only through the pinned Prime launcher.

## Global Constraints

- The only authorized real-model ceiling is 500,000 micros and 600,000 ms; lower operator limits are valid.
- Call `load_bounded_rlm_authority`, not the generic bounded loader, before any daemon, kernel, sidecar, model, or `.env`-derived configuration use.
- `.env` values, model name, provider name, prompts, generated code, message bodies, paths, credentials, and raw outputs never enter manifests, public reports, exceptions, or stdout/stderr.
- Preserve `PRIME_NATIVE_RLM_MAX_DEPTH = 0` for the normal provider factory. This experiment is an explicit private entry point, never a default runtime capability.
- The public daemon protocol is not extended with IPython execution. The only native effect is through the pinned derived Prime RLM shim.
- Provider-free commands, `make test`, `make check`, and `make promotion-check` never run the model experiment.
- A failed, cancelled, timed-out, over-budget, or teardown-uncertain run is never retryable from the same reservation and never yields PASS.

---

### Task 1: Create a pure private experiment contract and one-time reservation

**Files:**

- Create: `tools/prime_native_rlm_experiment.py`
- Create: `tests/test_prime_rlm_experiment.py`

**Interfaces:**

- Produces `NativeRlmExperimentLimits(cost_micros: int, deadline_ms: int)` and `NativeRlmExperimentReservation`.
- Produces `prepare_native_rlm_experiment(authority_path: Path, *, max_cost_micros: int, deadline_ms: int, environ: Mapping[str, str]) -> NativeRlmExperimentReservation`.
- The function returns only immutable, redacted identifiers/digests and must start no process.

- [ ] **Step 1: Write failing contract tests**

  In `tests/test_prime_rlm_experiment.py`, add tests that inject a complete RLM authority JSON and a mapping such as `{"ASTERION_PRIME_EXPERIMENT_MODEL": "private-model"}`. Assert that preparation accepts `500_000`/`600_000`, exposes a 64-character configuration digest rather than the model value, and reports `consumed is False`. Add subtests that reject a missing model variable, `500_001` cost, `600_001` deadline, missing `rlm.child.message`, and a second `reservation.consume()` call. Assert every error omits `private-model` and a sentinel credential.

- [ ] **Step 2: Verify RED**

  Run:

  ```bash
  uv run python -m unittest -v tests.test_prime_rlm_experiment
  ```

  Expected: import failure because `rlm_experiment` does not exist.

- [ ] **Step 3: Implement the minimal pure contract**

  Add frozen dataclasses with these closed fields:

  ```python
  @dataclass(frozen=True, repr=False)
  class NativeRlmExperimentLimits:
      cost_micros: int
      deadline_ms: int

  @dataclass(frozen=True, repr=False)
  class NativeRlmExperimentReservation:
      authority: AuthorityEnvelope
      limits: NativeRlmExperimentLimits
      configuration_digest: str
      _consumed: bool = False

      def consume(self) -> "NativeRlmExperimentReservation":
          if self._consumed:
              raise PrimeRlmExperimentError("Native RLM experiment reservation is inactive")
          return replace(self, _consumed=True)
  ```

  `prepare_native_rlm_experiment` must validate the exact `ASTERION_PRIME_EXPERIMENT_MODEL` environment key without rendering it, call `load_bounded_rlm_authority`, reject limits above the fixed ceilings, and SHA-256 hash `b"asterion.prime.native-rlm\0" + model.encode()`.

- [ ] **Step 4: Verify GREEN and commit**

  ```bash
  uv run python -m unittest -v tests.test_prime_rlm_experiment
  git add tools/prime_native_rlm_experiment.py tests/test_prime_rlm_experiment.py
  git commit -m "feat: prepare bounded native rlm experiment"
  ```

  Expected: all contract tests pass with no subprocess calls.

### Task 2: Persist a private-only receipt and enforce terminal classification

**Files:**

- Modify: `tools/prime_native_rlm_experiment.py`
- Modify: `tests/test_prime_rlm_experiment.py`

**Interfaces:**

- Consumes a reservation from Task 1 and opaque child/message lifecycle summaries.
- Produces `write_native_rlm_experiment_receipt(root: Path, reservation: NativeRlmExperimentReservation, *, terminal: Literal["completed", "failed", "cancelled", "uncertain"], child_started: bool, message_delivered: bool, child_deleted: bool, usage: BudgetUsage) -> Mapping[str, object]`.

- [ ] **Step 1: Write failing receipt tests**

  Test a completed receipt with one started child, one delivered message, one delete, and usage at or below the reservation. Assert its public mapping contains only `format`, `status`, `configuration_digest`, safe usage, and Boolean lifecycle assertions. Test missing delete, usage above 500,000 micros, and `uncertain` terminal; assert all classify as non-PASS. Read the private receipt file and assert it has mode `0o600`; assert its public mapping and raised errors omit sentinel prompt/model/credential values.

- [ ] **Step 2: Verify RED**

  ```bash
  uv run python -m unittest -v tests.test_prime_rlm_experiment.TestNativeRlmExperiment.test_receipt_requires_complete_bounded_lifecycle
  ```

  Expected: failure because the receipt writer is missing.

- [ ] **Step 3: Implement closed receipt writing**

  Use `tempfile.NamedTemporaryFile(dir=root, delete=False)` plus `os.replace` and `os.chmod(..., 0o600)`. Write a private canonical JSON document containing only the authority ID/revision, source/configuration digests, status, opaque event digests, and safe usage. Return a `MappingProxyType` with the closed public fields. A receipt is `PASS` only for `completed` plus all three lifecycle booleans and in-range usage; otherwise return `External-limited` for incomplete evidence or `uncertain` for uncertain teardown.

- [ ] **Step 4: Verify GREEN and commit**

  ```bash
  uv run python -m unittest -v tests.test_prime_rlm_experiment
  git add tools/prime_native_rlm_experiment.py tests/test_prime_rlm_experiment.py
  git commit -m "feat: record bounded native rlm evidence"
  ```

### Task 3: Add the explicit, default-off native experiment CLI boundary

**Files:**

- Modify: `tools/verify_prime_loop.py`
- Modify: `tests/test_verify_prime_loop.py`
- Modify: `Makefile`
- Modify: `docs/guides/prime-control-operator-guide.md`

**Interfaces:**

- Extends `--level` with `native-rlm-bounded`.
- Requires `--source-root`, `--authority`, `--max-cost-micros`, `--private-evidence-root`, and `--native-rlm-experiment`.
- Requires the exact environment key but never reads a `.env` file itself.

- [ ] **Step 1: Write failing CLI tests**

  Add a `unittest.mock.patch` test that invokes `main([...])` with every required flag and injected environment. Assert it calls `prepare_native_rlm_experiment` only after `verify_preflight`; add a matrix missing each new flag or the opt-in switch and assert exit `1`, zero calls to preflight, and no model operation. Add a test that `--level bounded` still calls the generic loader and returns its existing `External-limited` outcome.

- [ ] **Step 2: Verify RED**

  ```bash
  uv run python -m unittest -v tests.test_verify_prime_loop.TestVerifyPrimeLoop.test_native_rlm_bounded_requires_exact_opt_in
  ```

  Expected: failure because the level and flags do not exist.

- [ ] **Step 3: Implement argument closure and make target**

  Parse the two new path/Boolean arguments. Reject every extraneous authority argument at `provider-free`/`preflight`; require all five exact inputs at `native-rlm-bounded`. Add only this non-default target:

  ```make
  prime-verify-native-rlm-bounded:
	$(UV_BIN) run python tools/verify_prime_loop.py --level native-rlm-bounded \
		--native-rlm-experiment --source-root "$(ASTERION_PRIME_SOURCE_ROOT)" \
		--authority "$(ASTERION_PRIME_AUTHORITY)" --max-cost-micros "500000" \
		--private-evidence-root "$(ASTERION_PRIME_EVIDENCE_ROOT)"
  ```

  Document that the target is an operator action and is excluded from standard gates.

- [ ] **Step 4: Verify GREEN and commit**

  ```bash
  uv run python -m unittest -v tests.test_verify_prime_loop tests.test_prime_rlm_experiment
  make docs-check
  git add tools/verify_prime_loop.py tests/test_verify_prime_loop.py Makefile docs/guides/prime-control-operator-guide.md
  git commit -m "feat: gate native rlm experiment explicitly"
  ```

### Task 4: Connect the pinned derived runtime probe and prove cancellation ownership

**Files:**

- Create: `tests/fixtures/prime_gateway/v1/native-rlm-model-probe.mjs`
- Modify: `tools/prime_native_rlm_experiment.py`
- Modify: `tests/test_prime_rlm_experiment.py`
- Modify: `tests/test_prime_rlm_messaging_parity.py`

**Interfaces:**

- Consumes the Task 3 reservation and private descriptor passed by file descriptor to the existing sidecar process boundary.
- Produces one closed observation containing `child_started`, `message_delivered`, `child_deleted`, safe usage totals, and terminal status.

- [ ] **Step 1: Write failing orchestration tests**

  Add tests with an injected async daemon launcher and probe runner. Assert launch happens only after `reservation.consume()`, the runner receives a timeout no larger than 600 seconds, and cancellation terminates/reaps exactly the injected daemon and sidecar. Assert a missing child terminal/delete or unmatched message produces `uncertain`; prove all logs and public results omit `PRIVATE_NATIVE_RLM_PROMPT` and a sentinel environment value.

- [ ] **Step 2: Verify RED**

  ```bash
  uv run python -m unittest -v tests.test_prime_rlm_experiment.TestNativeRlmExperiment.test_cancellation_reaps_owned_processes
  ```

  Expected: failure because no native probe runner exists.

- [ ] **Step 3: Implement the private runner and probe**

  Use `derive_prime_rlm_runtime`, the existing `PrimeSidecarProcess`, `build_prime_rlm_control_host`, and an `asyncio.timeout(limits.deadline_ms / 1000)` scope. The Node probe must import only the installed private RLM host shim, execute the fixed native RLM probe through the derived daemon binding, and emit one JSON observation with no prompt/model/provider values. In `finally`, close host and sidecar, terminate the exact owned daemon, await it within the remaining deadline, and classify any cleanup failure as `uncertain`.

- [ ] **Step 4: Verify GREEN, static gates, and commit**

  ```bash
  uv run python -m unittest -v tests.test_prime_rlm_experiment tests.test_prime_rlm_messaging_parity
  npm --prefix packages/typescript/prime-gateway test -- test/rlm-host-shim.test.mjs
  uv run ruff check src tests tools
  make test.prime-rlm-spawn-admission.provider-free
  make check
  git add tools/prime_native_rlm_experiment.py tests/test_prime_rlm_experiment.py tests/fixtures/prime_gateway/v1/native-rlm-model-probe.mjs tests/test_prime_rlm_messaging_parity.py
  git commit -m "feat: run bounded native rlm probe"
  ```

  Expected: all provider-free and repository gates pass without model work. Run `make prime-verify-native-rlm-bounded` only as the separately authorized final operator action; its output may promote bounded assertions only after a complete receipt.

### Task 5: Record the real-run result without overpromotion

**Files:**

- Modify: `docs/status/JOURNAL.md` (user-session state; never include in implementation commits)
- Modify: `docs/status/RESUME-NEXT-SESSION.md` (only after a completed experiment boundary)
- Modify: `docs/status/PRIME-PARITY-LEDGER.md` (only if the named real command produces a complete receipt)

- [ ] **Step 1: Execute one authorized run**

  Run the Task 3 target with an operator-owned 0600 authority file, a private evidence root, and the configured environment. Do not print or inspect `.env` values.

- [ ] **Step 2: Classify evidence conservatively**

  Promote only `rlm.generated-program`, `rlm.child-model`, and `rlm.recursion-depth` when the receipt is completed, in range, and proves all required lifecycle edges. Otherwise record `External-limited` or `uncertain`; do not retry under the same reservation.

- [ ] **Step 3: Record durable state**

  Append one ≤20-word journal line with the implementation/run commit or no-code result. Update the recovery checkpoint with the exact next safe action. Do not commit status files.
