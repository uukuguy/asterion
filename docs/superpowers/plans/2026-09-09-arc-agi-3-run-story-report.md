# ARC-AGI-3 Run Story Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an Asterion Prime-owned pipeline that compiles one explicit ARC-AGI-3 run into durable normalized process data, adds versioned evidence-cited interpretation, regenerates a professional interactive web report, and serves every report from one loopback-only catalog URL.

**Architecture:** Keep the existing solver behavior untouched. The common Pi runtime adapter translates native usage into the existing `asterion.agent-runtime/v1` contract; Asterion Prime consumes that public event, and P7 privately persists it before applying its receipt-only public projection. A P7 application module then validates an explicit private run root, publishes one immutable fact bundle below `artifacts/arc-agi-3/`, and creates independently versioned analyses and web renders bound by SHA-256 identities.

**Tech Stack:** Python 3.10+ standard library, existing Asterion sealed trace validation and Pi RPC integration, plain UTF-8 HTML/CSS/JavaScript with Canvas, `unittest`, Hatch package resources.

## Global Constraints

- The application-owned data schema identity is exactly `asterion.prime.arc-agi-3-run-story/v1`; this is not a framework protocol.
- Generated artifacts live only below the visible ignored root `artifacts/arc-agi-3/`; raw evidence remains below `.asterion-private/prime-p7-live/<run-id>/`.
- The compiler consumes one explicit absolute run directory and never scans for evidence or chooses a run.
- Framework modules remain ARC-domain-neutral; all new domain behavior lives below `src/asterion/applications/prime/p7/run_story/`.
- `compile`, `render`, and `serve` are provider-free; only `analyze` may call an injected model narrator.
- No generated artifact may contain prompts, credentials, absolute paths, provider payloads, raw worker code/output, or arbitrary exception text.
- Canonical JSON is UTF-8, sorted-key, compact JSON ending in one newline; JSONL preserves semantic record order.
- Directories use mode `0750`, files use mode `0640`, symlink inputs/outputs fail closed, and immutable content IDs are never overwritten.
- The common Pi adapter, not Asterion Prime, normalizes native `message_end` usage into the public `usage.reported` contract. P7 privately persists and sums it; legacy runs without persisted usage render it as `未记录`.
- Recording timestamps may be preserved as event facts but must not be promoted into an inferred elapsed metric.
- The current run must report 23 actions, score `3.267621`, model `deepseek-v4-flash`, 43 reasoning cells, completed level 1, sealed trace, and verified replay.
- The web render uses no CDN, web framework, telemetry, remote font, or runtime network request beyond same-origin artifact reads.
- Verification is intentionally bounded to `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story`, plus `make promotion-check` because packaged resources change.

---

## File Map

- Create `src/asterion/applications/prime/p7/run_story/__init__.py`: public application-layer exports.
- Create `src/asterion/applications/prime/p7/run_story/model.py`: immutable fact/analysis/render value objects, canonical serialization, IDs, and closed validation.
- Create `src/asterion/applications/prime/p7/run_story/evidence.py`: explicit private-run reader and cross-file validation.
- Create `src/asterion/applications/prime/p7/run_story/storage.py`: safe staging, permissions, atomic publication, digest manifests, and catalog rebuilding.
- Create `src/asterion/applications/prime/p7/run_story/compiler.py`: normalized frames, actions, diffs, reasoning index, and metrics.
- Create `src/asterion/applications/prime/p7/run_story/analysis.py`: narrator request/protocol, closed story validation, fallback analysis, and versioning.
- Create `src/asterion/applications/prime/p7/run_story/operator_narrator.py`: bounded operator-owned Pi narrator adapter; repository configuration is resolved here, never in framework modules.
- Create `src/asterion/applications/prime/p7/run_story/renderer.py`: deterministic render assembly and packaged-asset digests.
- Create `src/asterion/applications/prime/p7/run_story/server.py`: loopback-only, read-only artifact catalog server.
- Create `src/asterion/applications/prime/p7/run_story/cli.py`: `compile`, `analyze`, `render`, and `serve` commands with public-safe errors.
- Create `src/asterion/applications/prime/p7/run_story/assets/index.html`: stable semantic report shell.
- Create `src/asterion/applications/prime/p7/run_story/assets/styles.css`: approved professional poster layout and responsive rules.
- Create `src/asterion/applications/prime/p7/run_story/assets/app.js`: catalog navigation, Canvas playback, diff overlay, and synchronized story selection.
- Create `src/asterion/applications/prime/p7/run_story/assets/header-art.png`: approved ARC-AGI-3 decorative header art.
- Modify `src/asterion/runtimes/pi_rpc.py`: expose one common native-Pi-to-runtime usage normalizer.
- Modify `src/asterion/agents/prime/session.py`: consume the common normalizer instead of defining a Prime-specific copy.
- Modify `src/asterion/runtimes/pi_observation.py`: reuse the same common usage-field validation.
- Modify `src/asterion/applications/prime/p7/private_trace.py`: accumulate validated Pi usage records in the sealed private trace.
- Modify `src/asterion/applications/prime/runtime_binding.py`: retain `usage.reported` privately before projecting the P7 public receipt-only stream.
- Modify `src/asterion/cli.py`: route the top-level `arc-story` command before the generic parser.
- Modify `pyproject.toml`: include report assets in wheel and source distribution artifacts.
- Modify `.gitignore`: ignore only the generated `/artifacts/` tree.
- Create `tests/test_prime_arc_agi_3_run_story.py`: one bounded test module covering deterministic facts, privacy, narration, render, and HTTP boundaries.

### Task 0: Normalize Pi usage in the public runtime adapter and persist it for P7

**Files:**
- Modify: `src/asterion/runtimes/pi_rpc.py`
- Modify: `src/asterion/agents/prime/session.py`
- Modify: `src/asterion/runtimes/pi_observation.py`
- Modify: `src/asterion/applications/prime/p7/private_trace.py`
- Modify: `src/asterion/applications/prime/runtime_binding.py`
- Modify: `tests/test_pi_session.py`
- Modify: `tests/test_asterion_prime_session.py`
- Modify: `tests/test_prime_p7_native_provider.py`

**Interfaces:**
- Consumes: native Pi `message_end` payloads with `message.role == "assistant"` and `message.usage.{input,output}`.
- Produces: `normalize_pi_usage(payload: Mapping[str, object]) -> Mapping[str, int] | None`; public runtime events with exact payload keys `input_tokens` and `output_tokens`; `P7PrivateTraceReceipt.record_usage(*, input_tokens: int, output_tokens: int) -> None`; sealed private trace entries of kind `arc.usage.reported`; unchanged P7 receipt-only public stream.

- [ ] **Step 1: Add common-adapter and P7 projection regressions**

```python
def test_normalize_pi_usage_projects_public_runtime_fields(self) -> None:
    payload = {"message": {"role": "assistant", "usage": {"input": 120, "output": 31}}}
    self.assertEqual(
        normalize_pi_usage(payload),
        {"input_tokens": 120, "output_tokens": 31},
    )
    self.assertIsNone(normalize_pi_usage({"message": {"role": "user"}}))
    with self.assertRaisesRegex(ValueError, "Pi usage event is invalid"):
        normalize_pi_usage({"message": {"role": "assistant", "usage": {"input": True, "output": 1}}})

def test_p7_projector_persists_usage_without_widening_public_stream(self) -> None:
    fixture = P7RuntimeFixture()
    fixture.native_events = (
        run_event(1, "run.started", {"capabilities": ["prime.tool.ipython"]}),
        run_event(2, "usage.reported", {"input_tokens": 120, "output_tokens": 31}),
        run_event(3, "run.completed", {"status": "completed"}),
    )
    projected = asyncio.run(fixture.collect_projected_events())
    self.assertEqual(tuple(event.type for event in projected),
                     ("run.started", "artifact.created", "run.completed"))
    entries = validate_trace(fixture.trace_entries())
    usage = [entry for entry in entries if entry.kind == "arc.usage.reported"]
    self.assertEqual(len(usage), 1)
    self.assertEqual(usage[0].payload, {"input_tokens": 120, "output_tokens": 31})
    self.assertNotIn("usage.reported", repr(projected))
```

- [ ] **Step 2: Run the focused common-adapter and P7 tests and confirm failure**

Run: `uv run python -m unittest -v tests.test_pi_session.PiRpcSessionTests.test_normalize_pi_usage_projects_public_runtime_fields tests.test_prime_p7_native_provider.TestPrimeP7NativeProvider.test_p7_projector_persists_usage_without_widening_public_stream`

Expected: `ERROR` because the common normalizer does not exist, and `FAIL` because the P7 projector discards usage without recording it.

- [ ] **Step 3: Implement common Pi usage normalization and remove the Prime-specific copy**

```python
def normalize_pi_usage(payload: Mapping[str, object]) -> Mapping[str, int] | None:
    message = payload.get("message")
    if not isinstance(message, Mapping) or message.get("role") != "assistant":
        return None
    usage = message.get("usage")
    if usage is None:
        return None
    if not isinstance(usage, Mapping):
        raise ValueError("Pi usage event is invalid")
    input_tokens, output_tokens = usage.get("input"), usage.get("output")
    if (
        isinstance(input_tokens, bool) or type(input_tokens) is not int or input_tokens < 0
        or isinstance(output_tokens, bool) or type(output_tokens) is not int or output_tokens < 0
    ):
        raise ValueError("Pi usage event is invalid")
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}
```

Replace `AsterionPrimeSession._assistant_usage(payload)` with `normalize_pi_usage(payload)` and map its `ValueError` to the existing safe `_NativeDiagnostic.USAGE_MALFORMED`. Reuse the helper in `pi_observation.py` while keeping that module's call-association logic unchanged.

- [ ] **Step 4: Implement validated private usage recording**

```python
def record_usage(self, *, input_tokens: int, output_tokens: int) -> None:
    if (
        self._accessed
        or isinstance(input_tokens, bool)
        or type(input_tokens) is not int
        or input_tokens < 0
        or isinstance(output_tokens, bool)
        or type(output_tokens) is not int
        or output_tokens < 0
    ):
        raise P7PrivateTraceReceiptError("P7 usage evidence is invalid")
    self._recorder.append(
        "arc.usage.reported",
        P7_TRACE_IDENTITIES,
        {"input_tokens": input_tokens, "output_tokens": output_tokens},
    )
```

In `_P7SolveEventProjector.__call__`, handle usage before the existing discard branch:

```python
if event.type == "usage.reported":
    try:
        self._trace.record_usage(
            input_tokens=event.payload["input_tokens"],
            output_tokens=event.payload["output_tokens"],
        )
    except (KeyError, P7PrivateTraceReceiptError):
        sequence += 1
        yield RunEvent(request.run_id, sequence, "run.failed",
                       {"code": "p7_usage_invalid", "message": "P7 usage evidence is invalid."})
        return
    continue
```

- [ ] **Step 5: Run the focused usage tests**

Run: `uv run python -m unittest -v tests.test_pi_session.PiRpcSessionTests.test_normalize_pi_usage_projects_public_runtime_fields tests.test_asterion_prime_session.TestAsterionPrimeSession.test_session_emits_one_valid_terminal_and_closes_lease tests.test_prime_p7_native_provider.TestPrimeP7NativeProvider.test_p7_projector_persists_usage_without_widening_public_stream`

Expected: all three tests report `ok`.

- [ ] **Step 6: Commit common normalization and private P7 persistence**

```bash
git add src/asterion/runtimes/pi_rpc.py src/asterion/runtimes/pi_observation.py src/asterion/agents/prime/session.py src/asterion/applications/prime/p7/private_trace.py src/asterion/applications/prime/runtime_binding.py tests/test_pi_session.py tests/test_asterion_prime_session.py tests/test_prime_p7_native_provider.py
git commit -m "feat: normalize and retain Pi usage evidence"
```

### Task 1: Closed fact model and explicit evidence reader

**Files:**
- Create: `src/asterion/applications/prime/p7/run_story/__init__.py`
- Create: `src/asterion/applications/prime/p7/run_story/model.py`
- Create: `src/asterion/applications/prime/p7/run_story/evidence.py`
- Create: `tests/test_prime_arc_agi_3_run_story.py`

**Interfaces:**
- Consumes: `validate_trace(entries: tuple[PrimeTraceEntry, ...])` from `asterion.agents.prime.trace`; explicit `Path` containing `summary.json`, one recording, worker cells, trace, and optional seal.
- Produces: `RunEvidence`, `FrameFact`, `ActionFact`, `ReasoningCellFact`, `read_run_evidence(run_root: Path) -> RunEvidence`, `canonical_json(value: object) -> bytes`, and `content_id(prefix: str, value: object) -> str`.

- [ ] **Step 1: Write the minimal completed and partial evidence fixtures in the test module**

```python
class TestPrimeArcAgi3RunStory(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_reads_completed_evidence_without_copying_private_content(self) -> None:
        run_root = write_completed_fixture(self.root, worker_secret="RAW-WORKER-SENTINEL")
        evidence = read_run_evidence(run_root)
        self.assertEqual(evidence.game_id, "fixture-game")
        self.assertEqual(evidence.run_id, "fixture-run")
        self.assertEqual(tuple(action.name for action in evidence.actions), ("ACTION1", "ACTION2"))
        self.assertEqual(evidence.worker_cell_count, 2)
        self.assertEqual(evidence.verification, "VERIFIED")
        self.assertNotIn("RAW-WORKER-SENTINEL", repr(evidence))

    def test_rejects_ambiguous_recording_and_symlink(self) -> None:
        run_root = write_completed_fixture(self.root)
        second = run_root / "recordings" / "other" / "duplicate.jsonl"
        second.parent.mkdir()
        second.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(RunStoryError, "evidence-invalid"):
            read_run_evidence(run_root)
        second.unlink()
        (run_root / "summary-link.json").symlink_to(run_root / "summary.json")
        with self.assertRaisesRegex(RunStoryError, "evidence-invalid"):
            assert_regular_file(run_root / "summary-link.json")
```

- [ ] **Step 2: Run the two tests and confirm the module is absent**

Run: `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_reads_completed_evidence_without_copying_private_content tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_rejects_ambiguous_recording_and_symlink`

Expected: `ERROR` with `ModuleNotFoundError: No module named 'asterion.applications.prime.p7.run_story'`.

- [ ] **Step 3: Implement frozen evidence types and canonical helpers**

```python
SCHEMA = "asterion.prime.arc-agi-3-run-story/v1"

class RunStoryError(ValueError):
    pass

@dataclass(frozen=True, slots=True)
class FrameFact:
    index: int
    timestamp: str | None
    state: str
    levels_completed: int
    grid: tuple[tuple[int, ...], ...]
    sha256: str

@dataclass(frozen=True, slots=True)
class ActionFact:
    index: int
    name: str
    before_frame: int
    after_frame: int
    before_sha256: str
    after_sha256: str
    levels_completed: int

@dataclass(frozen=True, slots=True)
class ReasoningCellFact:
    index: int
    is_error: bool
    code_sha256: str
    output_sha256: str

@dataclass(frozen=True, slots=True)
class RunEvidence:
    run_id: str
    game_id: str
    identities: Mapping[str, str]
    frames: tuple[FrameFact, ...]
    actions: tuple[ActionFact, ...]
    reasoning_cells: tuple[ReasoningCellFact, ...]
    score: str | None
    action_limit: int | None
    levels_completed: int
    terminal_reason: str
    verification: str
    replay_verified: bool
    sealed_trace: bool
    worker_cell_count: int
    usage: Mapping[str, int] | None
    source_digests: Mapping[str, str]

def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False,
                       sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

def content_id(prefix: str, value: object) -> str:
    return f"{prefix}-{sha256(canonical_json(value)).hexdigest()[:20]}"
```

- [ ] **Step 4: Implement fail-closed evidence parsing**

```python
def assert_regular_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise RunStoryError("evidence-invalid")
    return path

def read_run_evidence(run_root: Path) -> RunEvidence:
    if not run_root.is_absolute() or run_root.is_symlink() or not run_root.is_dir():
        raise RunStoryError("evidence-invalid")
    summary_path = assert_regular_file(run_root / "summary.json")
    trace_path = assert_regular_file(run_root / "trace" / "prime-trace.jsonl")
    recording_paths = tuple((run_root / "recordings").glob("*/*.jsonl"))
    if len(recording_paths) != 1:
        raise RunStoryError("evidence-invalid")
    recording_path = assert_regular_file(recording_paths[0])
    worker_path = assert_regular_file(run_root / "worker-cells.jsonl")
    summary = read_closed_summary(summary_path)
    trace = read_and_validate_trace(trace_path, run_root / "trace" / "prime-trace.seal.json", summary)
    frames, game_id = read_recording(recording_path)
    actions = reconcile_actions(trace, frames, summary)
    cells = read_reasoning_metadata(worker_path)
    return build_run_evidence(summary, game_id, frames, actions, cells,
                              evidence_digests(summary_path, trace_path, recording_path, worker_path))
```

The helper parsers must use exact key sets, reject booleans where integers are expected, validate one `64x64` palette-indexed grid per retained observation, collapse only byte-identical leading `RESET` duplicates, verify trace hash chaining/seal, require trace/recording action identity plus before/after frame digest correspondence, and sum all validated `arc.usage.reported` records. A trace with no usage records yields `usage=None` for backward compatibility.

- [ ] **Step 5: Run the focused tests**

Run: `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_reads_completed_evidence_without_copying_private_content tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_rejects_ambiguous_recording_and_symlink`

Expected: both tests report `ok`.

- [ ] **Step 6: Commit the evidence boundary**

```bash
git add src/asterion/applications/prime/p7/run_story/__init__.py src/asterion/applications/prime/p7/run_story/model.py src/asterion/applications/prime/p7/run_story/evidence.py tests/test_prime_arc_agi_3_run_story.py
git commit -m "feat: validate ARC run story evidence"
```

### Task 2: Immutable process-data compiler and catalog

**Files:**
- Create: `src/asterion/applications/prime/p7/run_story/storage.py`
- Create: `src/asterion/applications/prime/p7/run_story/compiler.py`
- Modify: `tests/test_prime_arc_agi_3_run_story.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `RunEvidence`, `canonical_json`, and `content_id` from Task 1.
- Produces: `CompiledBundle(run_root: Path, bundle_sha256: str, artifact: Mapping[str, object])`, `compile_run(run_root: Path, artifact_root: Path) -> CompiledBundle`, and `rebuild_catalog(artifact_root: Path) -> Path`.

- [ ] **Step 1: Add deterministic compilation and tamper/privacy tests**

```python
def test_compiles_deterministic_process_bundle_and_safe_catalog(self) -> None:
    # The completed fixture's sealed trace contains two authoritative Pi usage
    # records, each with 120 input and 31 output tokens.
    run_root = write_completed_fixture(self.root, worker_secret="RAW-WORKER-SENTINEL")
    artifact_root = self.root / "artifacts" / "arc-agi-3"
    first = compile_run(run_root, artifact_root)
    second = compile_run(run_root, artifact_root)
    self.assertEqual(first.bundle_sha256, second.bundle_sha256)
    self.assertEqual(first.run_root, second.run_root)
    run = json.loads((first.run_root / "data" / "run.json").read_text())
    self.assertEqual(run["action_count"], 2)
    self.assertIsNone(run["elapsed_seconds"])
    self.assertEqual(run["usage"], {"input_tokens": 240, "output_tokens": 62})
    actions = read_jsonl(first.run_root / "data" / "actions.jsonl")
    frames = read_jsonl(first.run_root / "data" / "frames.jsonl")
    diffs = read_jsonl(first.run_root / "data" / "diffs.jsonl")
    self.assertEqual((len(actions), len(frames), len(diffs)), (2, 3, 2))
    published = b"".join(path.read_bytes() for path in first.run_root.rglob("*") if path.is_file())
    self.assertNotIn(b"RAW-WORKER-SENTINEL", published)

def test_tamper_fails_before_final_publication(self) -> None:
    run_root = write_completed_fixture(self.root)
    trace = run_root / "trace" / "prime-trace.jsonl"
    trace.write_text(trace.read_text().replace("ACTION1", "ACTION4", 1), encoding="utf-8")
    artifact_root = self.root / "artifacts" / "arc-agi-3"
    with self.assertRaisesRegex(RunStoryError, "evidence-invalid"):
        compile_run(run_root, artifact_root)
    self.assertFalse((artifact_root / "games").exists())
```

- [ ] **Step 2: Run the new tests and confirm failure**

Run: `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_compiles_deterministic_process_bundle_and_safe_catalog tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_tamper_fails_before_final_publication`

Expected: `ERROR` because `compile_run` is not defined.

- [ ] **Step 3: Implement exact frame diffs and safe reasoning indices**

```python
def frame_diff(before: FrameFact, after: FrameFact) -> dict[str, object]:
    changes = [
        {"row": row, "column": column, "before": old, "after": new}
        for row, (left, right) in enumerate(zip(before.grid, after.grid, strict=True))
        for column, (old, new) in enumerate(zip(left, right, strict=True))
        if old != new
    ]
    rows = [item["row"] for item in changes]
    columns = [item["column"] for item in changes]
    return {
        "schema": SCHEMA,
        "action_index": after.index,
        "changed_cell_count": len(changes),
        "bounding_box": None if not changes else [min(rows), min(columns), max(rows), max(columns)],
        "changes": changes,
    }

def reasoning_record(cell: ReasoningCellFact) -> dict[str, object]:
    return {"schema": SCHEMA, "cell_index": cell.index, "status": "error" if cell.is_error else "ok",
            "code_sha256": cell.code_sha256, "output_sha256": cell.output_sha256,
            "purpose": "inspection"}
```

- [ ] **Step 4: Implement immutable staged publication and deterministic catalog refresh**

```python
@dataclass(frozen=True, slots=True)
class CompiledBundle:
    run_root: Path
    bundle_sha256: str
    artifact: Mapping[str, object]

def compile_run(run_root: Path, artifact_root: Path) -> CompiledBundle:
    evidence = read_run_evidence(run_root)
    destination = artifact_root / "games" / safe_id(evidence.game_id) / "runs" / safe_id(evidence.run_id)
    files = normalized_bundle_files(evidence)
    artifact = artifact_manifest(evidence, files)
    digest = sha256(canonical_json(artifact)).hexdigest()
    if destination.exists():
        validate_existing_bundle(destination, artifact)
        return CompiledBundle(destination, digest, artifact)
    publish_directory(destination, files | {"artifact.json": canonical_json(artifact)})
    rebuild_catalog(artifact_root)
    return CompiledBundle(destination, digest, artifact)
```

`publish_directory` must reject a symlink at every existing parent, create a sibling directory with `tempfile.mkdtemp`, set modes, write with `O_CREAT|O_EXCL|O_NOFOLLOW`, fsync files and directories, and finish with `os.replace`. `rebuild_catalog` must validate every discovered `artifact.json`, sort by `(game_id, run_id)`, and replace only `catalog.json`; malformed entries leave the old catalog unchanged.

- [ ] **Step 5: Ignore the generated visible artifact root**

Add exactly this root rule to `.gitignore`:

```gitignore
/artifacts/
```

- [ ] **Step 6: Run the compilation tests**

Run: `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_compiles_deterministic_process_bundle_and_safe_catalog tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_tamper_fails_before_final_publication`

Expected: both tests report `ok`.

- [ ] **Step 7: Commit the durable data bundle**

```bash
git add .gitignore src/asterion/applications/prime/p7/run_story/storage.py src/asterion/applications/prime/p7/run_story/compiler.py tests/test_prime_arc_agi_3_run_story.py
git commit -m "feat: compile durable ARC solve artifacts"
```

### Task 3: Versioned evidence-cited analysis with deterministic fallback

**Files:**
- Create: `src/asterion/applications/prime/p7/run_story/analysis.py`
- Modify: `tests/test_prime_arc_agi_3_run_story.py`

**Interfaces:**
- Consumes: validated bundle directory from `compile_run`; a callable satisfying `RunStoryNarrator.generate(request: RunStoryNarrationRequest) -> Mapping[str, object]`.
- Produces: `RunStoryNarrationRequest`, `RunStoryNarrator`, `AnalysisResult`, `analyze_bundle(bundle_root: Path, narrator: RunStoryNarrator | None) -> AnalysisResult`, and `validate_story(value: object, facts: Mapping[str, object]) -> Mapping[str, object]`.

- [ ] **Step 1: Add accepted, rejected, and fallback narration tests**

```python
def test_analysis_accepts_citations_but_cannot_mutate_facts(self) -> None:
    bundle = compile_run(write_completed_fixture(self.root), self.root / "artifacts" / "arc-agi-3")
    narrator = StubNarrator(valid_story(action_count=2))
    accepted = analyze_bundle(bundle.run_root, narrator)
    self.assertEqual(accepted.status, "accepted")
    self.assertEqual(accepted.story["episodes"][0]["citations"], {"actions": [1], "frames": [0, 1]})
    invalid = valid_story(action_count=2) | {"action_count": 999}
    rejected = analyze_bundle(bundle.run_root, StubNarrator(invalid))
    self.assertEqual(rejected.status, "rejected")
    self.assertEqual(rejected.story["kind"], "factual-fallback")

def test_analysis_rejects_unknown_citation_and_private_sentinel(self) -> None:
    bundle = compile_run(write_completed_fixture(self.root), self.root / "artifacts" / "arc-agi-3")
    bad = valid_story(action_count=2)
    bad["episodes"][0]["citations"]["actions"] = [7]
    bad["episodes"][0]["observation"] = "SECRET-PROMPT-SENTINEL"
    result = analyze_bundle(bundle.run_root, StubNarrator(bad))
    self.assertEqual(result.status, "rejected")
    self.assertNotIn("SECRET-PROMPT-SENTINEL", json.dumps(result.story))
```

- [ ] **Step 2: Run the analysis tests and confirm failure**

Run: `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_analysis_accepts_citations_but_cannot_mutate_facts tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_analysis_rejects_unknown_citation_and_private_sentinel`

Expected: `ERROR` because `analyze_bundle` is not defined.

- [ ] **Step 3: Implement the narrator request and closed episode validator**

```python
@dataclass(frozen=True, slots=True)
class RunStoryNarrationRequest:
    schema: str
    run: Mapping[str, object]
    actions: tuple[Mapping[str, object], ...]
    diffs: tuple[Mapping[str, object], ...]
    reasoning_evidence: tuple[Mapping[str, object], ...]

class RunStoryNarrator(Protocol):
    model_id: str
    def generate(self, request: RunStoryNarrationRequest) -> Mapping[str, object]: ...

@dataclass(frozen=True, slots=True)
class AnalysisResult:
    analysis_root: Path
    analysis_id: str
    status: str
    story: Mapping[str, object]

_EPISODE_KEYS = frozenset({"step_start", "step_end", "title", "observation", "hypothesis",
                           "experiment", "result", "model_update", "consequence", "citations",
                           "confidence", "decisive"})
_CONFIDENCE = frozenset({"fact", "strong-inference", "tentative"})

def validate_episode(value: object, *, action_count: int, frame_count: int) -> dict[str, object]:
    episode = require_exact_mapping(value, _EPISODE_KEYS)
    start = require_int(episode["step_start"], minimum=1, maximum=action_count)
    end = require_int(episode["step_end"], minimum=start, maximum=action_count)
    citations = require_exact_mapping(episode["citations"], frozenset({"actions", "frames"}))
    actions = require_sorted_unique_ints(citations["actions"], 1, action_count)
    frames = require_sorted_unique_ints(citations["frames"], 0, frame_count - 1)
    if not actions or not frames or episode["confidence"] not in _CONFIDENCE:
        raise RunStoryError("narration-invalid")
    for field in ("title", "observation", "hypothesis", "experiment", "result", "model_update", "consequence"):
        require_bounded_text(episode[field], minimum=1, maximum=320)
    return dict(episode)
```

- [ ] **Step 4: Implement versioned analysis and fallback behavior**

```python
def analyze_bundle(bundle_root: Path, narrator: RunStoryNarrator | None) -> AnalysisResult:
    facts = load_validated_bundle(bundle_root)
    fallback = factual_story(facts)
    status, model_id, story = "unavailable", None, fallback
    if narrator is not None:
        try:
            candidate = narrator.generate(narration_request(facts))
            story = validate_story(candidate, facts)
            status, model_id = "accepted", narrator.model_id
        except Exception:
            status, story = "rejected", fallback
    identity = {"schema": SCHEMA, "bundle_sha256": facts.bundle_sha256,
                "contract_version": "run-story-narrator/v1", "model_id": model_id,
                "status": status, "story_sha256": digest_json(story)}
    analysis_id = content_id("analysis", identity)
    root = publish_analysis(bundle_root, analysis_id, identity, story)
    rebuild_catalog(artifact_root_for(bundle_root))
    return AnalysisResult(root, analysis_id, status, story)
```

The factual fallback must group consecutive no-op/productive/completion transitions, answer the four post-run questions with `resolved: false` when unsupported, and never invent action semantics or a completion mechanism.

- [ ] **Step 5: Run the analysis tests**

Run: `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_analysis_accepts_citations_but_cannot_mutate_facts tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_analysis_rejects_unknown_citation_and_private_sentinel`

Expected: both tests report `ok`.

- [ ] **Step 6: Commit the versioned analysis layer**

```bash
git add src/asterion/applications/prime/p7/run_story/analysis.py tests/test_prime_arc_agi_3_run_story.py
git commit -m "feat: add evidence-cited ARC run analysis"
```

### Task 4: Operator-owned bounded Pi narrator

**Files:**
- Create: `src/asterion/applications/prime/p7/run_story/operator_narrator.py`
- Modify: `tests/test_prime_arc_agi_3_run_story.py`

**Interfaces:**
- Consumes: `RunStoryNarrationRequest` from Task 3; `PiRpcConfig`, `PiRpcSession`, and the repository's operator-owned `.env` configuration.
- Produces: `PiRunStoryNarrator`, `resolve_operator_narrator(repo_root: Path, environ: Mapping[str, str]) -> PiRunStoryNarrator`, and `build_narrator_payload(request: RunStoryNarrationRequest) -> str`.

- [ ] **Step 1: Add bounded configuration and projection tests**

```python
def test_operator_narrator_uses_fixed_controls_and_projects_no_secrets(self) -> None:
    captured: dict[str, object] = {}
    session = FakePiSession('{"schema":"run-story-narrator/v1","episodes":[],"understanding":[]}', captured)
    narrator = PiRunStoryNarrator(model_id="deepseek-v4-flash", session=session)
    payload = build_narrator_payload(minimal_narration_request())
    self.assertNotIn("DEEPSEEK_API_KEY", payload)
    self.assertNotIn(str(self.root), payload)
    narrator.generate(minimal_narration_request())
    self.assertLessEqual(len(captured["prompt"].encode("utf-8")), 131072)

def test_operator_narrator_missing_configuration_is_public_safe(self) -> None:
    with self.assertRaisesRegex(RunStoryError, "narrator-unavailable"):
        resolve_operator_narrator(self.root, {})
```

- [ ] **Step 2: Run the narrator tests and confirm failure**

Run: `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_operator_narrator_uses_fixed_controls_and_projects_no_secrets tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_operator_narrator_missing_configuration_is_public_safe`

Expected: `ERROR` because `PiRunStoryNarrator` is not defined.

- [ ] **Step 3: Implement the fixed narrator projection and adapter**

```python
_DEADLINE_SECONDS = 180.0
_MAX_PROMPT_BYTES = 131_072

@dataclass(frozen=True, slots=True)
class _NeverCancelled:
    @property
    def cancelled(self) -> bool:
        return False

@dataclass(frozen=True, slots=True)
class PiRunStoryNarrator:
    model_id: str
    session: PiRpcSession

    def generate(self, request: RunStoryNarrationRequest) -> Mapping[str, object]:
        prompt = build_narrator_payload(request)
        if len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES:
            raise RunStoryError("narrator-input-too-large")
        result = asyncio.run(
            self.session.run(
                prompt,
                signal=_NeverCancelled(),
                on_event=lambda event: None,
            )
        )
        try:
            value = json.loads(extract_single_json_object(result.final_text))
        except (ValueError, json.JSONDecodeError):
            raise RunStoryError("narration-invalid") from None
        if not isinstance(value, Mapping):
            raise RunStoryError("narration-invalid")
        return value
```

`build_narrator_payload` must include only normalized run/actions/diffs and the safe reasoning index; raw worker text is not included in the first delivery. It must instruct the model to return the exact closed `run-story-narrator/v1` JSON shape, cite indices, distinguish fact/inference, keep each field within 320 characters, and never reproduce private text. `resolve_operator_narrator` must load `.env` only in this application operator module, reuse the same Pi executable/model-selection path as the P7 operator, remove unrelated environment values, and expose no provider/model/cost/deadline command-line knobs.

- [ ] **Step 4: Run the narrator tests**

Run: `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_operator_narrator_uses_fixed_controls_and_projects_no_secrets tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_operator_narrator_missing_configuration_is_public_safe`

Expected: both tests report `ok`.

- [ ] **Step 5: Commit the operator narrator**

```bash
git add src/asterion/applications/prime/p7/run_story/operator_narrator.py tests/test_prime_arc_agi_3_run_story.py
git commit -m "feat: narrate ARC runs through bounded Pi"
```

### Task 5: Deterministic professional web renderer

**Files:**
- Create: `src/asterion/applications/prime/p7/run_story/renderer.py`
- Create: `src/asterion/applications/prime/p7/run_story/assets/index.html`
- Create: `src/asterion/applications/prime/p7/run_story/assets/styles.css`
- Create: `src/asterion/applications/prime/p7/run_story/assets/app.js`
- Create: `src/asterion/applications/prime/p7/run_story/assets/header-art.png`
- Modify: `tests/test_prime_arc_agi_3_run_story.py`

**Interfaces:**
- Consumes: validated bundle and selected `AnalysisResult` from Task 3; packaged assets loaded with `importlib.resources.files`.
- Produces: `RenderResult(render_root: Path, render_id: str, manifest: Mapping[str, object])` and `render_web(bundle_root: Path, analysis_id: str, *, theme_version: str = "poster-v1") -> RenderResult`.

- [ ] **Step 1: Add byte-determinism and data-binding tests**

```python
def test_render_is_deterministic_and_theme_change_preserves_data(self) -> None:
    bundle = compile_run(write_completed_fixture(self.root), self.root / "artifacts" / "arc-agi-3")
    analysis = analyze_bundle(bundle.run_root, StubNarrator(valid_story(action_count=2)))
    first = render_web(bundle.run_root, analysis.analysis_id)
    second = render_web(bundle.run_root, analysis.analysis_id)
    changed = render_web(bundle.run_root, analysis.analysis_id, theme_version="poster-v2")
    self.assertEqual(first.render_id, second.render_id)
    self.assertNotEqual(first.render_id, changed.render_id)
    self.assertEqual(first.manifest["bundle_sha256"], changed.manifest["bundle_sha256"])
    html = (first.render_root / "index.html").read_text(encoding="utf-8")
    self.assertIn("ARC-AGI-3", html)
    self.assertNotIn("3.267621", html)
```

- [ ] **Step 2: Run the render test and confirm failure**

Run: `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_render_is_deterministic_and_theme_change_preserves_data`

Expected: `ERROR` because `render_web` is not defined.

- [ ] **Step 3: Implement a data-only HTML shell and Canvas player**

Copy the approved 2172×724 source artwork without raster resampling:

```bash
cp .superpowers/brainstorm/6837-1788938711/content/arc-agi-3-recomposed-left.png src/asterion/applications/prime/p7/run_story/assets/header-art.png
```

The HTML shell must contain these stable regions and no run-specific numbers:

```html
<main id="report" data-manifest="render.json">
  <header class="masthead"><section id="identity"></section><img class="header-art" src="assets/header-art.png" alt=""><section id="verification"></section></header>
  <section class="stage"><div class="player"><canvas id="frame" width="640" height="640"></canvas><nav id="controls"></nav></div><article id="step-explanation"></article></section>
  <section id="solve-story" aria-label="解题过程"></section>
  <section id="understanding" aria-label="解题后对题目的理解"></section>
  <footer><article id="protocol-background"></article><article id="asterion-background"></article></footer>
</main>
```

The JavaScript must fetch `render.json`, then same-run relative `run.json`, `actions.jsonl`, `frames.jsonl`, `diffs.jsonl`, and `story.json`; render palette values through a constant ARC color table; expose play/pause, previous/next, speed, and diff toggle; and synchronize the active episode by citation range:

```javascript
const ARC = ["#000000", "#0074D9", "#FF4136", "#2ECC40", "#FFDC00", "#AAAAAA", "#F012BE", "#FF851B", "#7FDBFF", "#870C25", "#FFFFFF", "#39CCCC", "#B10DC9", "#001F3F", "#01FF70", "#85144B"];
function drawFrame(ctx, frame, changed) {
  const size = 10;
  frame.grid.forEach((row, y) => row.forEach((value, x) => {
    ctx.fillStyle = ARC[value] || "#ffffff";
    ctx.fillRect(x * size, y * size, size, size);
  }));
  if (changed) changed.forEach(({row, column}) => ctx.strokeRect(column * size + .5, row * size + .5, size - 1, size - 1));
}
```

The CSS must implement the approved dark professional poster: title left, integrated art centered with breathing room, compact verification at right, real-frame player as the visual center, unequal causal episode cards, explicit understanding block, and two compact background cards at the bottom. At `max-width: 900px`, it must collapse to one column in the same semantic order and never stretch the header art.

- [ ] **Step 4: Implement content-bound rendering**

```python
@dataclass(frozen=True, slots=True)
class RenderResult:
    render_root: Path
    render_id: str
    manifest: Mapping[str, object]

def render_web(bundle_root: Path, analysis_id: str, *, theme_version: str = "poster-v1") -> RenderResult:
    bundle = load_validated_bundle(bundle_root)
    analysis = load_validated_analysis(bundle_root, analysis_id)
    assets = load_packaged_assets(("index.html", "styles.css", "app.js", "header-art.png"))
    identity = {"schema": SCHEMA, "renderer_version": "web-v1", "theme_version": theme_version,
                "bundle_sha256": bundle.bundle_sha256, "analysis_sha256": analysis.analysis_sha256,
                "asset_sha256": {name: sha256(data).hexdigest() for name, data in sorted(assets.items())}}
    render_id = content_id("web", identity)
    manifest = render_manifest(identity, bundle_root, analysis_id)
    root = publish_render(bundle_root, render_id, assets, canonical_json(manifest))
    rebuild_catalog(artifact_root_for(bundle_root))
    return RenderResult(root, render_id, manifest)
```

- [ ] **Step 5: Run the render test**

Run: `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_render_is_deterministic_and_theme_change_preserves_data`

Expected: test reports `ok`.

- [ ] **Step 6: Commit the renderer and approved design assets**

```bash
git add src/asterion/applications/prime/p7/run_story/renderer.py src/asterion/applications/prime/p7/run_story/assets tests/test_prime_arc_agi_3_run_story.py
git commit -m "feat: render ARC solve story reports"
```

### Task 6: Stable loopback catalog URL and CLI

**Files:**
- Create: `src/asterion/applications/prime/p7/run_story/server.py`
- Create: `src/asterion/applications/prime/p7/run_story/cli.py`
- Modify: `src/asterion/cli.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_prime_arc_agi_3_run_story.py`

**Interfaces:**
- Consumes: Tasks 2-5 public functions.
- Produces: `validate_bind(host: str, port: int) -> tuple[str, int]`, `ArtifactApplication.handle(method: str, target: str) -> ArtifactResponse`, `serve_artifacts(artifact_root: Path, *, host: str = "127.0.0.1", port: int = 0, open_browser: bool = False) -> None`, and `main(argv: list[str] | None = None, *, stdout: TextIO, stderr: TextIO) -> int`.

- [ ] **Step 1: Add HTTP boundary and CLI routing tests**

```python
def test_server_is_read_only_utf8_and_rejects_escape(self) -> None:
    app = ArtifactApplication(populated_artifact_root(self.root))
    root = app.handle("GET", "/")
    self.assertEqual(root.status, 200)
    self.assertIn("text/html; charset=utf-8", root.headers["Content-Type"])
    self.assertEqual(app.handle("POST", "/").status, 405)
    self.assertEqual(app.handle("GET", "/../.env").status, 404)
    self.assertEqual(app.handle("GET", "/%2e%2e/.env").status, 404)
    self.assertEqual(app.handle("GET", "/missing").body, b'{"error":"not-found"}\n')

def test_cli_routes_arc_story_without_provider_discovery(self) -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    artifact_root = self.root / "artifacts" / "arc-agi-3"
    with unittest.mock.patch(
        "asterion.applications.prime.p7.run_story.cli.default_artifact_root",
        return_value=artifact_root,
    ):
        code = asterion_cli.main(
            ["arc-story", "compile", str(completed_fixture_path(self.root))],
            stdout=stdout,
            stderr=stderr,
        )
    self.assertEqual(code, 0)
    self.assertEqual(stderr.getvalue(), "")
```

- [ ] **Step 2: Run the boundary tests and confirm failure**

Run: `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_server_is_read_only_utf8_and_rejects_escape tests.test_prime_arc_agi_3_run_story.TestPrimeArcAgi3RunStory.test_cli_routes_arc_story_without_provider_discovery`

Expected: `ERROR` because the server and CLI route do not exist.

- [ ] **Step 3: Implement the loopback-only read-only application**

```python
_LOOPBACK = frozenset({"127.0.0.1", "::1"})

def validate_bind(host: str, port: int) -> tuple[str, int]:
    if host not in _LOOPBACK or type(port) is not int or not 0 <= port <= 65535:
        raise RunStoryError("server-bind-invalid")
    return host, port

class ArtifactApplication:
    def __init__(self, artifact_root: Path) -> None:
        self._root = validate_artifact_root(artifact_root)

    def handle(self, method: str, target: str) -> ArtifactResponse:
        if method not in {"GET", "HEAD"}:
            return public_response(method, 405, "application/json; charset=utf-8", b'{"error":"method-not-allowed"}\n')
        if not valid_target(target):
            return public_response(method, 404, "application/json; charset=utf-8", b'{"error":"not-found"}\n')
        return serve_catalog_or_rooted_file(self._root, method, target)
```

Every response must include `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and a CSP allowing only same-origin scripts/styles/images/connections. `/` is a checked-in catalog shell that loads `/catalog.json`; all other content resolves below the validated artifact root without URL decoding ambiguity or symlink traversal.

- [ ] **Step 4: Implement the four command actions and top-level route**

```python
if raw_argv[:1] == ["arc-story"]:
    from asterion.applications.prime.p7.run_story.cli import main as arc_story_main
    return arc_story_main(raw_argv[1:], stdout=stdout, stderr=stderr)
```

The command surface is exact:

```text
asterion arc-story compile ABSOLUTE_RUN_ROOT
asterion arc-story analyze GAME_ID RUN_ID
asterion arc-story render GAME_ID RUN_ID --analysis ANALYSIS_ID
asterion arc-story serve [--open-browser]
```

The operator integration derives `artifacts/arc-agi-3/` from the repository root by default. Tests inject the artifact root through `main(..., artifact_root=...)`, not a public CLI flag. `analyze` resolves the narrator internally and exposes no provider/model/budget/deadline flags. All failures print one closed reason code and return `2`.

- [ ] **Step 5: Package the static assets**

Add the following wheel artifact entry to `pyproject.toml`:

```toml
"src/asterion/applications/prime/p7/run_story/assets/*",
```

Add the same path to the sdist artifact list.

- [ ] **Step 6: Run the complete bounded feature test**

Run: `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story`

Expected: all tests report `ok` and the command ends with `OK`.

- [ ] **Step 7: Run distribution verification because packaged assets changed**

Run: `make promotion-check`

Expected: command exits `0`; no packaged-resource, entry-point, schema, or distribution failure is reported.

- [ ] **Step 8: Commit the viewer and CLI**

```bash
git add src/asterion/cli.py src/asterion/applications/prime/p7/run_story/server.py src/asterion/applications/prime/p7/run_story/cli.py pyproject.toml tests/test_prime_arc_agi_3_run_story.py
git commit -m "feat: serve ARC solve artifacts from one URL"
```

### Task 7: Generate and verify the first real run artifact

**Files:**
- Generate ignored files below: `artifacts/arc-agi-3/games/ls20-9607627b/runs/p7-live-20260909065351/`
- Generate ignored file: `artifacts/arc-agi-3/catalog.json`
- Modify: `docs/status/JOURNAL.md`

**Interfaces:**
- Consumes: the existing explicit run root `.asterion-private/prime-p7-live/p7-live-20260909065351` and Tasks 1-6 CLI.
- Produces: the first real normalized bundle, accepted or factual-fallback analysis, web render, stable local catalog URL, and durable journal evidence.

- [ ] **Step 1: Compile the real run without invoking a model**

Run: `uv run asterion arc-story compile "$(pwd)/.asterion-private/prime-p7-live/p7-live-20260909065351"`

Expected: exit `0` and one public-safe JSON line containing `game_id: ls20-9607627b`, `run_id: p7-live-20260909065351`, and a relative artifact location.

- [ ] **Step 2: Assert the real fact bundle values**

Run:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
root = Path("artifacts/arc-agi-3/games/ls20-9607627b/runs/p7-live-20260909065351")
run = json.loads((root / "data/run.json").read_text(encoding="utf-8"))
actions = (root / "data/actions.jsonl").read_text(encoding="utf-8").splitlines()
frames = (root / "data/frames.jsonl").read_text(encoding="utf-8").splitlines()
assert run["model_id"] == "deepseek-v4-flash"
assert run["action_count"] == 23
assert run["score"] == "3.267621"
assert run["reasoning_cell_count"] == 43
assert run["levels_completed"] == 1
assert run["verification"] == "VERIFIED"
assert run["elapsed_seconds"] is None
assert run["usage"] is None  # This run predates private Pi usage persistence.
assert len(actions) == 23 and len(frames) == 30
print("real bundle verified")
PY
```

Expected: `real bundle verified`.

- [ ] **Step 3: Generate a versioned analysis through the configured Asterion Pi model**

Run: `uv run asterion arc-story analyze ls20-9607627b p7-live-20260909065351`

Expected: exit `0`; output reports either `accepted` with a content-bound analysis ID, or the explicit safe `rejected`/`unavailable` factual fallback status. A rejected narration does not block rendering.

- [ ] **Step 4: Render the selected analysis**

Run: `uv run asterion arc-story render ls20-9607627b p7-live-20260909065351 --analysis "$(uv run python -c 'import json; from pathlib import Path; p=Path("artifacts/arc-agi-3/catalog.json"); print(json.loads(p.read_text())["runs"][0]["analyses"][-1]["analysis_id"])')"`

Expected: exit `0` and output contains one `web-...` render ID; existing process-data digests remain unchanged.

- [ ] **Step 5: Start the stable viewer and inspect the approved layout in the existing browser session**

Run: `uv run asterion arc-story serve --open-browser`

Expected: one loopback URL is printed, the existing authenticated browser profile opens or reuses a tab, and the catalog can switch runs/renders without changing the server URL. Verify the header image is integrated and centered, the real 64×64 frames animate without distortion, decisive story episodes stand out, the four-question understanding section is visible, and the two concise background cards are at the bottom.

- [ ] **Step 6: Run the bounded regression command once more**

Run: `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story`

Expected: all tests report `ok` and the command ends with `OK`.

- [ ] **Step 7: Record the generated evidence without committing ignored artifacts**

Append one journal line naming the real run, bundle ID, analysis ID/status, render ID, verification command, and fixed artifact root. Then commit only the journal change if it is not mixed with pre-existing user edits; otherwise leave the journal modification uncommitted and report that condition.

```bash
git add docs/status/JOURNAL.md
git commit -m "docs: record first ARC run story artifact"
```

## Completion Evidence

The delivery is complete only when all of the following are true:

- `uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story` passes.
- `make promotion-check` passes after packaged assets are added.
- The real bundle records exactly 23 actions and 30 visual frames (including multi-frame action animations), score `3.267621`, model `deepseek-v4-flash`, 43 reasoning cells, one completed level, sealed trace, and verified replay.
- `elapsed_seconds` remains null unless an authoritative field supplies it; `usage` is summed from persisted Pi records, while the existing legacy run remains null because those events were not retained at solve time.
- A byte scan of `artifact.json`, `data/`, `analyses/`, `renders/`, and `catalog.json` contains no raw worker content, prompt sentinel, credential sentinel, absolute private run path, or provider payload.
- Re-running `compile` returns the same bundle; re-running `render` with the same inputs returns the same render ID; changing only `theme_version` creates a new render while leaving every `data/` digest unchanged.
- One loopback-only URL lists the catalog and opens every generated run and render.
