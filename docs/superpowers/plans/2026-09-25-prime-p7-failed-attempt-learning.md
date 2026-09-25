# P7 Failed-Attempt Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach one explicitly requested P7 same-game retry to use verified local failed-run facts and current-run action feedback before spending another paid BP35 Level-1 attempt.

**Architecture:** Add an application-owned failed-attempt evidence reader beside the existing P7 run-story reader, because `run_story.evidence.read_run_evidence()` intentionally accepts completed success evidence and rejects the sealed BP35 failed runs. Feed a bounded, digest-bound fact block into the P7 operator only when a retry marker is present, add generic border/interior action feedback to the worker surface, and wrap the existing `SweepScheduler._attempt()` in a one-shot retry controller that writes its own timestamped manifest without touching the paused breadth ledger.

**Tech Stack:** Python `unittest`, existing P7 private summary/trace/recording formats, `tools/run_prime_p7_sweep.py`, Makefile installed-wheel P7 recipes, no new runtime dependencies.

## Global Constraints

- Do not hardcode BP35-specific coordinates, colors, map text, solution text, or action sequences; BP35 is only the acceptance example.
- Retry mode is OFFLINE, seed `0`, target level selected from local verified progress, human action cap, 30-minute limit, and five-minute no-action limit.
- Select at most the two most recent failed runs for the exact game ID, seed, and target level.
- Eligible sources must be regular local private-run files under `.asterion-private/prime-p7-live`, with matching private summary, sealed hash-valid trace, seal digest, replay verification, cleanup completion, and zero progress through the target level.
- Interrupted runs, including the existing CD82 `running` breadth entry, are never selected as failed-run advice.
- Public receipts expose only safe counts and the new result; private diagnostics may store source run IDs and digests.
- Do not resume or edit the breadth campaign ledger in this task.
- Do not perform an official submission in this task.
- Run zero-model installed-wheel preflight and independent code review before the one authorized paid retry.

---

## File Structure

- Create `src/asterion/applications/prime/p7/failed_attempts.py`
  - Narrow reader for sealed failed P7 evidence, action-effect facts, fact-block digesting, and retry advice rendering.
  - Public interfaces:
    - `class FailedAttemptEvidenceError(ValueError)`
    - `@dataclass(frozen=True) FailedActionFact`
    - `@dataclass(frozen=True) FailedRunFacts`
    - `@dataclass(frozen=True) FailedAttemptAdvice`
    - `select_failed_attempt_advice(runs_root: Path, *, game_id: str, seed: int, target_level: int, limit: int = 2) -> FailedAttemptAdvice`
    - `render_failed_attempt_advice(advice: FailedAttemptAdvice) -> str`
- Modify `src/asterion/applications/prime/p7/ipython_host.py`
  - Extend the guest helper `diff()` payload with `interior_changed_cells`, `border_changed_cells`, and `border_only`.
- Modify `src/asterion/applications/prime/p7/prompt.py`
  - Add a retry-only prompt section contract that treats failed-run facts as checked observations and repeats the generic Retrodict guidance: distinguish observed mechanics from goals, do not treat local frame changes as progress, and do not repeat a failed sequence without a new falsifiable reason.
- Modify `src/asterion/applications/prime/p7/operator.py`
  - Read retry marker from operator-owned environment, select and render failed-attempt facts before `run_composed_application()`, append the fact block only in retry mode, and record private diagnostics.
- Create `tools/run_prime_p7_retry.py`
  - One-shot controller for `make p7-retry GAME=<alias-or-exact-id>`, plus `--preflight-only`.
  - It uses `SweepScheduler._attempt()` with `unbounded_first_round=True`, `action_stall_seconds=300`, `validate_action_stall=True`, `run_timeout=1800`, seed `0`, and the normal installed P7 sweep attempt command.
  - It writes `.asterion-private/prime-p7-live/retry-manifests/<timestamp>-<game>-level-<n>.json`.
- Modify `Makefile`
  - Add `.PHONY` entries and recipes for `p7-retry-preflight`, `asterion-prime-p7-retry-preflight`, `p7-retry`, and `asterion-prime-p7-retry`.
  - Forward retry-only environment names through Orb: `ASTERION_PRIME_P7_RETRY_MODE`, `ASTERION_PRIME_P7_RETRY_ADVICE_DIGEST`, and `ASTERION_PRIME_P7_RETRY_SOURCE_RUNS`.
- Add `tests/test_prime_p7_failed_attempts.py`
  - Evidence reader, safety, fact block, and prompt/operator unit tests.
- Add `tests/test_prime_p7_retry.py`
  - Controller, Makefile, manifest, preflight, and scheduler wiring tests.
- Update `docs/guides/prime-p7-games-and-official-results.md`
  - Add the operator flow after breadth resweep: zero-model preflight, one paid retry, read manifest, compare action behavior, then resume normal breadth only after user instruction.

## Task 1: Failed-Run Evidence Reader

**Files:**
- Create: `src/asterion/applications/prime/p7/failed_attempts.py`
- Test: `tests/test_prime_p7_failed_attempts.py`

**Interfaces:**
- Consumes: existing private P7 run layout: `summary.json`, `trace/prime-trace.jsonl`, `trace/prime-trace.seal.json`, and exactly one `recordings/*/*.jsonl`.
- Produces: immutable `FailedAttemptAdvice` with `source_run_ids`, `source_digest`, `fact_count`, `actions`, safe token usage totals when present, and `render_failed_attempt_advice()`.

- [ ] **Step 1: Write failing tests for exact same-game failed evidence selection**

Add a local test helper in `tests/test_prime_p7_failed_attempts.py` before the tests:

```python
def write_failed_run_fixture(
    runs_root: Path,
    run_id: str,
    *,
    game_id: str,
    seed: int,
    target_level: int,
    actions: int,
    replay_verified: bool = True,
    cleanup_complete: bool = True,
    sealed_trace: bool = True,
) -> Path:
    """Create the smallest sealed failed-run fixture the reader accepts."""
    run = runs_root / run_id
    (run / "trace").mkdir(parents=True)
    (run / "recordings" / game_id).mkdir(parents=True)
    summary = {
        "schema": "asterion.prime.p7-live-private-summary/v1",
        "run_id": run_id,
        "receipt": {"schema": "asterion.prime.p7-live-receipt/v1", "run_id": run_id, "completed_level_count": 0, "primitive_action_count": actions},
        "broker": {"terminal_reason": "human-baseline"},
        "replay_verified": replay_verified,
        "sealed_trace": sealed_trace,
        "cleanup_complete": cleanup_complete,
        "diagnostics": {"sweep": {"target_level": target_level}, "broker_status": {"levels_completed": 0, "primitive_actions": actions, "terminal_reason": "human-baseline"}, "worker_cell_count": 0},
        "experiment": {"game": {"game_id": game_id, "seed": seed, "target_level": target_level}},
    }
    write_minimal_failed_trace_and_recording(run, game_id=game_id, actions=actions)
    (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return run
```

`write_minimal_failed_trace_and_recording()` should live in the same test file and emit hash-chained `arc.action` rows plus matching recording rows with small 3x3 frames. The fixture does not need real ARC SDK output; it only needs enough fields to test the reader's binding rules.

Then create three run directories:

```python
def test_selects_two_recent_same_game_sealed_failed_attempts(self) -> None:
    runs_root = self.root / ".asterion-private" / "prime-p7-live"
    old = write_failed_run_fixture(runs_root, "p7-live-20260925080000-old", game_id="bp35-00000000", seed=0, target_level=1, actions=3)
    newest = write_failed_run_fixture(runs_root, "p7-live-20260925090000-new", game_id="bp35-00000000", seed=0, target_level=1, actions=4)
    other = write_failed_run_fixture(runs_root, "p7-live-20260925091000-other", game_id="cd82-00000000", seed=0, target_level=1, actions=4)

    advice = select_failed_attempt_advice(runs_root, game_id="bp35-00000000", seed=0, target_level=1)

    self.assertEqual(advice.source_run_ids, (newest.name, old.name))
    self.assertEqual(advice.source_count, 2)
    self.assertNotIn(other.name, advice.source_run_ids)
    self.assertTrue(advice.source_digest.startswith("sha256:"))
```

Also add rejection tests:

```python
def test_rejects_interrupted_unsealed_and_symlinked_candidates(self) -> None:
    runs_root = self.root / ".asterion-private" / "prime-p7-live"
    write_failed_run_fixture(runs_root, "p7-live-good", game_id="bp35-00000000", seed=0, target_level=1, actions=2)
    write_failed_run_fixture(runs_root, "p7-live-interrupted", game_id="bp35-00000000", seed=0, target_level=1, actions=2, replay_verified=False)
    (runs_root / "linked").symlink_to(runs_root / "p7-live-good")

    advice = select_failed_attempt_advice(runs_root, game_id="bp35-00000000", seed=0, target_level=1)

    self.assertEqual(advice.source_run_ids, ("p7-live-good",))
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_failed_attempts
```

Expected: FAIL because `asterion.applications.prime.p7.failed_attempts` does not exist.

- [ ] **Step 3: Implement the narrow reader**

Implement these exact boundaries:

```python
class FailedAttemptEvidenceError(ValueError):
    """Rejected failed-attempt evidence."""


@dataclass(frozen=True, slots=True)
class FailedActionFact:
    sequence: int
    action: Mapping[str, object]
    levels_completed: int
    before_sha256: str
    after_sha256: str
    changed_cells: int
    interior_changed_cells: int
    border_changed_cells: int
    border_only: bool
    color_counts: Mapping[int, int]


@dataclass(frozen=True, slots=True)
class FailedRunFacts:
    run_id: str
    terminal_reason: str
    target_level: int
    action_count: int
    input_tokens: int
    output_tokens: int
    actions: tuple[FailedActionFact, ...]


@dataclass(frozen=True, slots=True)
class FailedAttemptAdvice:
    schema: str
    game_id: str
    seed: int
    target_level: int
    source_run_ids: tuple[str, ...]
    source_digest: str
    runs: tuple[FailedRunFacts, ...]
```

Reader rules:

- Reject non-absolute roots, symlink roots, symlink run directories, symlink source files, and run paths outside the supplied `runs_root`.
- Require `summary["schema"] == "asterion.prime.p7-live-private-summary/v1"`, `sealed_trace is True`, `replay_verified is True`, `cleanup_complete is True`.
- Require `diagnostics.sweep.target_level == target_level` and `experiment.game.game_id`, `experiment.game.seed` when available; for older summaries with no `experiment`, accept only if recording identity and diagnostics target match.
- Require terminal reason in `{"human-baseline", "game-over", "ACTION_CAP", "GAME_OVER"}` or broker status with `levels_completed < target_level` and `primitive_actions > 0`.
- Bind trace action entries to recording actions by sequence, action name/data, before/after digest, and level count.
- Include up to 32 first plus 32 last target-level actions per run, de-duplicated when a run has at most 64 actions.
- Compute `interior_changed_cells` on cells where `0 < x < width - 1` and `0 < y < height - 1`; compute `border_changed_cells` on the one-cell border; `border_only` is true when `changed_cells > 0`, `interior_changed_cells == 0`, and `border_changed_cells == changed_cells`.
- Compute `source_digest = "sha256:" + sha256(canonical_json_without_private_paths).hexdigest()`.

- [ ] **Step 4: Run the focused tests and verify pass**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_failed_attempts
```

Expected: PASS for selection, rejection, action binding, border/interior counts, and digest stability.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime/p7/failed_attempts.py tests/test_prime_p7_failed_attempts.py
git commit -m "feat: read verified P7 failed-attempt facts"
```

## Task 2: Retry Fact Block and Prompt Injection

**Files:**
- Modify: `src/asterion/applications/prime/p7/prompt.py`
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Test: `tests/test_prime_p7_failed_attempts.py`

**Interfaces:**
- Consumes: `FailedAttemptAdvice` from Task 1 and retry marker env vars.
- Produces: retry-only model input text and private diagnostics:
  - `diagnostics["failed_attempt_advice"] = {"source_run_ids": ("p7-live-a",), "source_digest": "sha256:<64 hex>", "source_count": 1, "fact_count": 4}`

- [ ] **Step 1: Write failing tests for retry-only prompt injection and redaction**

Add tests with a fake advice block:

```python
def make_advice(*, source_run_ids: tuple[str, ...], source_digest: str) -> FailedAttemptAdvice:
    return FailedAttemptAdvice(
        schema="asterion.prime.p7-failed-attempt-advice/v1",
        game_id="bp35-00000000",
        seed=0,
        target_level=1,
        source_run_ids=source_run_ids,
        source_digest=source_digest,
        runs=(),
    )


def test_retry_prompt_appends_failed_attempt_advice_only_in_retry_mode(self) -> None:
    base = P7_SOLVE_PROMPT
    advice_text = render_failed_attempt_advice(make_advice(source_run_ids=("p7-live-a",), source_digest="sha256:" + "a" * 64))

    retry_prompt = build_p7_retry_prompt(base, advice_text)

    self.assertIn("Checked same-game failed-attempt observations", retry_prompt)
    self.assertIn("source_digest: sha256:" + "a" * 64, retry_prompt)
    self.assertNotIn(str(self.root), retry_prompt)
    self.assertNotIn("worker-cells", retry_prompt)
```

Add an operator-level test that patches `select_failed_attempt_advice()` and `run_composed_application()`:

```python
def test_operator_records_private_failed_attempt_diagnostics(self) -> None:
    captured: dict[str, object] = {}
    with patch.dict(os.environ, {"ASTERION_PRIME_P7_RETRY_MODE": "same-game-failed-attempt"}), \
         patch("asterion.applications.prime.p7.operator.select_failed_attempt_advice", return_value=make_advice(source_run_ids=("p7-live-a",), source_digest="sha256:" + "a" * 64)), \
         patch("asterion.applications.prime.p7.operator.run_composed_application", side_effect=capture_runtime_input(captured)):
        run_operator_fixture_once(game_id="bp35-00000000", target_level=1)

    diagnostics = captured["diagnostics"]
    self.assertEqual(diagnostics["failed_attempt_advice"]["source_run_ids"], ("p7-live-a",))
    self.assertEqual(diagnostics["failed_attempt_advice"]["source_count"], 1)
```

Define `capture_runtime_input()` and `run_operator_fixture_once()` in this test file using the existing P7 operator test style: patch host services and stop immediately after `run_composed_application()` receives `input_text`. The assertion target is the constructed input and diagnostics, not a live model run.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_failed_attempts
```

Expected: FAIL because `build_p7_retry_prompt()` and operator retry diagnostics do not exist.

- [ ] **Step 3: Implement retry-only prompt assembly**

Add to `prompt.py`:

```python
def build_p7_retry_prompt(base_prompt: str, failed_attempt_advice: str) -> str:
    if not failed_attempt_advice:
        return base_prompt
    return (
        base_prompt.rstrip()
        + "\n\nChecked same-game failed-attempt observations:\n"
        + failed_attempt_advice.strip()
        + "\n\nUse these facts only as observations from prior sealed failed runs. "
          "Do not treat local color removal, border animation, or any non-level-increase "
          "as goal progress by itself. Separate checked mechanics from objective "
          "assumptions before acting, and do not repeat a prior failed action sequence "
          "without a new falsifiable reason.\n"
    )
```

In `operator.py`, before `run_composed_application()`, select advice only when:

- `ASTERION_PRIME_P7_RETRY_MODE == "same-game-failed-attempt"`
- `invocation.sweep_mode is True`
- `invocation.game.seed == 0`

Then pass:

```python
input_text = build_p7_retry_prompt(_prompt_for_variant(variant), render_failed_attempt_advice(advice))
```

Record only `source_run_ids`, `source_digest`, `source_count`, and action fact counts in private diagnostics. Do not place raw frames, paths, worker cells, prompts, or credentials in diagnostics.

- [ ] **Step 4: Run focused tests and verify pass**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_failed_attempts
```

Expected: PASS, including retry-only behavior and redaction checks.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime/p7/prompt.py src/asterion/applications/prime/p7/operator.py tests/test_prime_p7_failed_attempts.py
git commit -m "feat: inject verified failed-attempt advice for P7 retries"
```

## Task 3: Current-Run Border and Interior Feedback

**Files:**
- Modify: `src/asterion/applications/prime/p7/ipython_host.py`
- Test: `tests/test_prime_p7_failed_attempts.py`

**Interfaces:**
- Consumes: existing `diff()` helper in the P7 client facade.
- Produces: existing diff fields plus:
  - `interior_changed_cells: int`
  - `border_changed_cells: int`
  - `border_only: bool`

Expose the pure helper as `frame_change_counts(before, after) -> dict[str, object]` from `ipython_host.py` so tests can verify the classification without launching the worker process.

- [ ] **Step 1: Write failing tests for generic border/interior classification**

Add tests that do not mention BP35:

```python
def test_diff_reports_border_and_interior_changes_separately(self) -> None:
    before = [[0, 0, 0], [0, 1, 0], [0, 0, 0]]
    after = [[2, 0, 0], [0, 3, 0], [0, 0, 0]]

    diff = frame_change_counts(before, after)

    self.assertEqual(diff["changed_cells"], 2)
    self.assertEqual(diff["border_changed_cells"], 1)
    self.assertEqual(diff["interior_changed_cells"], 1)
    self.assertFalse(diff["border_only"])


def test_diff_labels_border_only_as_hypothesis_signal(self) -> None:
    before = [[0, 0, 0], [0, 1, 0], [0, 0, 0]]
    after = [[2, 0, 0], [0, 1, 0], [0, 0, 0]]

    diff = frame_change_counts(before, after)

    self.assertEqual(diff["border_changed_cells"], 1)
    self.assertEqual(diff["interior_changed_cells"], 0)
    self.assertTrue(diff["border_only"])
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_failed_attempts
```

Expected: FAIL because the helper does not expose the new fields.

- [ ] **Step 3: Implement classification without semantic overclaiming**

Refactor the existing diff calculation into this helper:

```python
def frame_change_counts(before: Sequence[Sequence[int]], after: Sequence[Sequence[int]]) -> dict[str, object]:
    changed = 0
    interior = 0
    border = 0
    height = len(after)
    width = len(after[0]) if height else 0
    for y, row in enumerate(after):
        for x, value in enumerate(row):
            if y >= len(before) or x >= len(before[y]) or before[y][x] != value:
                changed += 1
                if 0 < x < width - 1 and 0 < y < height - 1:
                    interior += 1
                else:
                    border += 1
    return {
        "changed_cells": changed,
        "interior_changed_cells": interior,
        "border_changed_cells": border,
        "border_only": changed > 0 and interior == 0 and border == changed,
    }
```

Keep existing diff keys unchanged. Treat `border_only` as a signal for the model to inspect; do not call it a no-op.

- [ ] **Step 4: Run focused tests and verify pass**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_failed_attempts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime/p7/ipython_host.py tests/test_prime_p7_failed_attempts.py
git commit -m "feat: report P7 border and interior action effects"
```

## Task 4: One-Shot Retry Controller and Manifest

**Files:**
- Create: `tools/run_prime_p7_retry.py`
- Modify: `Makefile`
- Test: `tests/test_prime_p7_retry.py`
- Test: `tests/test_prime_make_presets.py`

**Interfaces:**
- Consumes: game alias/exact ID, ARC catalog, P7 runs root, failed-attempt advice reader, and `SweepScheduler._attempt()`.
- Produces:
  - `make p7-retry-preflight GAME=bp35`
  - `make p7-retry GAME=bp35`
  - retry manifest schema `asterion.prime.p7-retry-manifest/v1`

- [ ] **Step 1: Write failing controller tests**

Add tests:

```python
def make_config(*, game: str, runs_root: Path | None = None) -> RetryConfig:
    root = Path(tempfile.mkdtemp())
    return RetryConfig(
        game=game,
        arc_root=root / "arc",
        runs_root=runs_root or root / "runs",
        operator_root=root,
        repo_root=root,
        guest_machine=None,
    )


def test_retry_preflight_selects_next_unresolved_level_and_prior_failures(self) -> None:
    controller = RetryController(make_config(game="bp35"))
    controller._resolve_game = lambda value: "bp35-00000000"
    controller._next_unresolved_level = lambda game_id: 1
    controller._failed_advice = lambda game_id, level: SimpleNamespace(source_run_ids=("p7-live-a", "p7-live-b"), source_digest="sha256:" + "a" * 64)

    data = controller.preflight()

    self.assertEqual(data["schema"], "asterion.prime.p7-retry-preflight/v1")
    self.assertEqual(data["game_id"], "bp35-00000000")
    self.assertEqual(data["target_level"], 1)
    self.assertEqual(data["prior_failed_run_ids"], ["p7-live-a", "p7-live-b"])
    self.assertEqual(data["run_timeout_seconds"], 1800)
    self.assertEqual(data["no_action_stall_seconds"], 300)
```

```python
def test_retry_run_invokes_scheduler_once_and_writes_private_manifest(self) -> None:
    controller = RetryController(make_config(game="bp35", runs_root=self.runs_root))
    controller._resolve_game = lambda value: "bp35-00000000"
    controller._next_unresolved_level = lambda game_id: 1
    controller._failed_advice = lambda game_id, level: SimpleNamespace(source_run_ids=("p7-live-a",), source_digest="sha256:" + "a" * 64)

    with patch("tools.run_prime_p7_retry.SweepScheduler") as scheduler:
        scheduler.return_value._attempt.return_value = 0
        result = controller.run()

    scheduler.return_value._attempt.assert_called_once()
    self.assertEqual(result["attempted"], 1)
    manifest = json.loads(next((self.runs_root / "retry-manifests").glob("*.json")).read_text())
    self.assertEqual(manifest["schema"], "asterion.prime.p7-retry-manifest/v1")
    self.assertEqual(manifest["prior_failed_run_ids"], ["p7-live-a"])
```

Add a guard test:

```python
def test_retry_refuses_when_failed_advice_is_unavailable(self) -> None:
    controller = RetryController(make_config(game="bp35"))
    controller._failed_advice = lambda game_id, level: SimpleNamespace(source_run_ids=(), source_digest="sha256:" + "0" * 64)

    with self.assertRaises(SystemExit):
        controller.run()
```

- [ ] **Step 2: Write failing Makefile tests**

In `tests/test_prime_make_presets.py`, assert:

```python
self.assertIn(".PHONY: p7-retry-preflight", makefile)
self.assertIn(".PHONY: p7-retry", makefile)
self.assertIn("ASTERION_PRIME_P7_RETRY_MODE", _recipe(makefile, "asterion-prime-p7-solve asterion-prime-p7-level-witness asterion-prime-p7-sweep-attempt"))
```

Also dry-run:

```bash
make --no-print-directory -n p7-retry-preflight GAME=bp35
make --no-print-directory -n p7-retry GAME=bp35
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_retry tests.test_prime_make_presets
```

Expected: FAIL because the controller and Make targets do not exist.

- [ ] **Step 4: Implement controller**

`RetryController.run()` must:

- Resolve `GAME` using the same catalog/alias behavior as existing P7 commands.
- Select next unresolved level from `load_best_prefix()`: if no prefix, target `1`; otherwise `prefix.levels_completed + 1`.
- Call `select_failed_attempt_advice()` and require at least one source run.
- Create `SweepConfig` with:
  - `command=("make", "asterion-prime-p7-sweep-attempt")`
  - `unbounded_first_round=True`
  - `unbounded_second_round=False`
  - `run_timeout=1800`
  - `action_stall_seconds=300`
  - `validate_action_stall=True`
  - `global_token_cap=None`
  - `wallclock_cap=None`
- Set environment for the child attempt:
  - `ASTERION_PRIME_P7_RETRY_MODE=same-game-failed-attempt`
  - `ASTERION_PRIME_P7_RETRY_ADVICE_DIGEST=<digest>`
  - `ASTERION_PRIME_P7_RETRY_SOURCE_RUNS=<comma-separated run IDs>`
- Append a manifest under `retry-manifests/` with `0600` permissions and atomic replace.
- Never read or write `breadth-resweep-campaign.json`.

- [ ] **Step 5: Implement Make targets**

Add short and full targets. The run target must require `GAME` explicitly:

```make
p7-retry-preflight: asterion-prime-p7-retry-preflight

p7-retry: asterion-prime-p7-retry

asterion-prime-p7-retry-preflight:
	@printf '[asterion-prime-p7-retry-preflight] same-game failed-attempt retry readiness; zero model calls\n' >&2; \
	exec /bin/sh -ec 'if [ "$(origin GAME)" != "command line" ] || [ -z "$(GAME)" ]; then printf "[asterion-prime-p7-retry-preflight] pass GAME=<alias-or-exact-id> explicitly\n" >&2; exit 2; fi; build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p7-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; uv build --wheel --out-dir "$$build_dir" >/dev/null; wheel="$$(find "$$build_dir" -name "*.whl" -print -quit)"; uv run --isolated --with "$$wheel" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arc_agi-0.9.9-py3-none-any.whl" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arcengine-0.9.3-py3-none-any.whl" python -I tools/run_prime_p7_retry.py --preflight-only --game "$(GAME)" --operator-root "$(ASTERION_PRIME_OPERATOR_ROOT)" --arc-root "$(ASTERION_PRIME_ARC_ROOT)" --repo-root "$(CURDIR)"'

asterion-prime-p7-retry:
	@printf '[asterion-prime-p7-retry] one same-game failed-attempt retry; 30 minutes, 5 minutes without action, human action cap\n' >&2; \
	exec /bin/sh -ec 'if [ "$(origin GAME)" != "command line" ] || [ -z "$(GAME)" ]; then printf "[asterion-prime-p7-retry] pass GAME=<alias-or-exact-id> explicitly\n" >&2; exit 2; fi; build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p7-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; uv build --wheel --out-dir "$$build_dir" >/dev/null; wheel="$$(find "$$build_dir" -name "*.whl" -print -quit)"; uv run --isolated --with "$$wheel" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arc_agi-0.9.9-py3-none-any.whl" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arcengine-0.9.3-py3-none-any.whl" python -I tools/run_prime_p7_retry.py --game "$(GAME)" --operator-root "$(ASTERION_PRIME_OPERATOR_ROOT)" --arc-root "$(ASTERION_PRIME_ARC_ROOT)" --repo-root "$(CURDIR)"'
```

Extend the Orb environment forwarding in the existing P7 attempt recipe to include the three retry environment names.

- [ ] **Step 6: Run focused tests and verify pass**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_retry tests.test_prime_make_presets
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/run_prime_p7_retry.py Makefile tests/test_prime_p7_retry.py tests/test_prime_make_presets.py
git commit -m "feat: add one-shot P7 failed-attempt retry command"
```

## Task 5: Installed Zero-Model Preflight and Guide Update

**Files:**
- Modify: `docs/guides/prime-p7-games-and-official-results.md`
- Test: installed command behavior, no paid model call

**Interfaces:**
- Consumes: `make p7-retry-preflight GAME=bp35`.
- Produces: safe JSON showing BP35 target level, fixed controls, selected prior failed run IDs, advice digest, and no Orb/model action.

- [ ] **Step 1: Add guide text**

Insert a short section:

````markdown
## Same-Game Failed-Attempt Retry

Use this only after a failed sealed local run should inform exactly one retry:

```bash
make p7-retry-preflight GAME=bp35
make p7-retry GAME=bp35
```

`p7-retry-preflight` is zero-model. It lists the exact game ID, selected next unresolved level, fixed seed `0`, 30-minute attempt limit, five-minute no-action limit, human action cap, prior failed run IDs, and advice digest. `p7-retry` is one paid attempt. It writes a timestamped manifest under `.asterion-private/prime-p7-live/retry-manifests/` and leaves the breadth campaign ledger untouched.
````

- [ ] **Step 2: Run installed zero-model preflight**

Run:

```bash
make p7-retry-preflight GAME=bp35
```

Expected:

- Exit `0`.
- JSON schema `asterion.prime.p7-retry-preflight/v1`.
- `game_id` is BP35's exact official ID.
- `target_level` is `1` unless a newer verified BP35 prefix exists.
- It selects the old sealed BP35 failures.
- It excludes the interrupted CD82 breadth run.
- It does not create or modify `.asterion-private/prime-p7-live/breadth-resweep-campaign.json`.
- It does not launch Orb or a model process.

- [ ] **Step 3: Run docs and style checks**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p7_failed_attempts tests.test_prime_p7_retry tests.test_prime_make_presets
make lint
make docs-check
git diff --check
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add docs/guides/prime-p7-games-and-official-results.md
git commit -m "docs: explain P7 failed-attempt retry flow"
```

## Task 6: Safety Review, One Paid BP35 Retry, and Improvement Report

**Files:**
- No code changes unless review finds a blocking bug.
- Runtime output: `.asterion-private/prime-p7-live/retry-manifests/*.json`
- Runtime evidence: new `.asterion-private/prime-p7-live/<run_id>/`

**Interfaces:**
- Consumes: verified code, zero-model preflight, user authorization already given for one BP35 retry.
- Produces: one paid BP35 retry and a factual comparison against the prior BP35 failed runs.

- [ ] **Step 1: Independent code review before paid run**

Review for:

- No BP35-specific permanent logic.
- Failed-run reader cannot follow symlinks or read outside `runs_root`.
- Retry prompt contains no private paths, worker cells, raw prompts, credentials, or unrelated game data.
- Public receipt has only safe counts.
- Make preflight performs zero model calls.
- Controller cannot silently loop paid retries.
- CD82 `running` breadth ledger remains untouched.

Expected: reviewer reports no blocking findings.

- [ ] **Step 2: Run one authorized BP35 retry**

Run:

```bash
make p7-retry GAME=bp35
```

Expected: exactly one supervised attempt. It may pass or fail, but it must stop under human action cap, 30 minutes, five-minute no-action stall, level solve, game solve, or terminal game over.

- [ ] **Step 3: Validate new run evidence**

Run:

```bash
make asterion-prime-p7-games
uv run python -m unittest -v tests.test_prime_p7_retry
```

Expected:

- If BP35 Level 1 passes, `make asterion-prime-p7-games` shows BP35 with at least one verified completed level.
- If it fails, the run still has sealed trace, replay verification, cleanup completion, and a retry manifest with terminal outcome.

- [ ] **Step 4: Report action-tracking improvement**

Compare the two prior failed BP35 runs and the new run with these metrics:

- completed levels and terminal reason
- primitive action count
- shared exact action inputs with prior failures
- count of repeated click streaks from prior failures
- border-only action count
- interior-change action count
- first action that causes a meaningful interior change
- distinct settled-frame digests
- input and output token totals

Label improvement only when evidence supports it:

- Passing Level 1 is definitive improvement.
- Failing with less repeated ineffective behavior is changed exploration behavior, not solved capability.
- Repeating the same failed opening sequence is a regression and should stop further paid retries until another design change is approved.

## Acceptance Criteria

- `select_failed_attempt_advice()` selects only same-game, same-seed, same-target-level sealed failed evidence and rejects interrupted, unsealed, symlinked, or unrelated candidates.
- BP35 old failed evidence is available to the retry preflight while the CD82 interrupted breadth run is excluded.
- `diff()` reports `interior_changed_cells`, `border_changed_cells`, and `border_only` without removing existing fields.
- Retry prompt advice is appended only for explicit same-game retry mode.
- Private diagnostics record source run IDs and advice digest; public receipts do not expose raw frames, private paths, prompts, worker cells, credentials, or unrelated game facts.
- `make p7-retry-preflight GAME=bp35` is installed-wheel, zero-model, and read-only with respect to the breadth ledger.
- `make p7-retry GAME=bp35` runs exactly one supervised attempt with seed `0`, human action cap, 30-minute limit, and five-minute no-action stop.
- The retry writes a separate timestamped manifest and does not edit `breadth-resweep-campaign.json`.
- Before the paid retry, focused tests, Ruff, docs check, diff check, installed preflight, and independent review pass.
- After the paid retry, the report tracks action-by-action evidence and states plainly whether behavior improved.

## Commands Summary

```bash
uv run python -m unittest -v tests.test_prime_p7_failed_attempts
uv run python -m unittest -v tests.test_prime_p7_retry tests.test_prime_make_presets
make p7-retry-preflight GAME=bp35
make lint
make docs-check
git diff --check
make p7-retry GAME=bp35
make asterion-prime-p7-games
```
