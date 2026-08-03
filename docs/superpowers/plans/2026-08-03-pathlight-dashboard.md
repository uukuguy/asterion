# Pathlight Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-free, operator-local, read-only Pathlight API and Dashboard that presents verified workflow flow, evaluations, experiments, diagnoses, and explicit evidence gaps.

**Architecture:** A strict `DashboardSnapshot` is assembled once from explicitly named, validated Pathlight files. A loopback-only Python HTTP server exposes deterministic same-origin GET projections and package-local static assets; the browser never reads evidence files and gains no mutation or execution endpoint.

**Tech Stack:** Python 3.10+ standard library, existing Pathlight validators, semantic HTML, CSS, and dependency-free JavaScript; `unittest` for verification.

## Global Constraints

- Bind only `127.0.0.1`, `::1`, or `localhost`; reject all other hosts before opening a socket.
- Load only explicit absolute paths with the established exact filenames and closed Pathlight validators.
- Expose no prompt, answer, tool body, provider payload, credential, model/provider name, or local path.
- Provide only `GET` and `HEAD`; no execution, authorization, retry, scheduling, upload, or proposal approval endpoint.
- Load no application provider or Opik package and perform no external network operation.
- Preserve deterministic ordering, immutable inputs, fail-closed parsing, and the framework-to-product dependency direction.

---

### Task 1: Immutable Dashboard Snapshot

**Files:**
- Create: `src/asterion/pathlight/dashboard.py`
- Modify: `src/asterion/pathlight/__init__.py`
- Test: `tests/test_pathlight_dashboard.py`

**Interfaces:**
- Consumes: `WorkflowObservationBundle`, `EvaluationBundle`, `ExperimentBundle`, `DiagnosisBundle`, `project_trace_flow`.
- Produces: `DashboardSnapshot.build`, `DashboardSnapshot.to_mapping`, and `validate_dashboard_snapshot(mapping)`.

- [x] **Step 1: Write failing snapshot tests**

```python
def test_snapshot_is_deterministic_safe_and_marks_missing_flow(self) -> None:
    snapshot = DashboardSnapshot.build(
        workflow_bundles=(self.workflow_bundle,),
        evaluation_bundles=(self.evaluation_bundle,),
        experiment_bundles=(self.experiment_bundle,),
        diagnosis_bundles=(self.diagnosis_bundle,),
    )
    mapping = snapshot.to_mapping()
    self.assertEqual(validate_dashboard_snapshot(mapping), snapshot)
    self.assertEqual(mapping["schema"], "asterion.pathlight-dashboard-snapshot/v1")
    self.assertNotIn(self.sentinel_secret, json.dumps(mapping))
    self.assertTrue(mapping["summary"]["evidence_gap_count"] >= 1)
```

- [x] **Step 2: Run the focused test and confirm the contract is absent**

Run: `uv run python -m unittest -v tests.test_pathlight_dashboard`

Expected: FAIL because `DashboardSnapshot` is not defined.

- [x] **Step 3: Implement the closed snapshot contract**

```python
DASHBOARD_SNAPSHOT_SCHEMA = "asterion.pathlight-dashboard-snapshot/v1"

@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    traces: tuple[Mapping[str, object], ...]
    flows: tuple[Mapping[str, object], ...]
    evaluations: tuple[Mapping[str, object], ...]
    experiments: tuple[Mapping[str, object], ...]
    diagnoses: tuple[Mapping[str, object], ...]
    summary: Mapping[str, object]
    snapshot_sha256: str

    @classmethod
    def build(
        cls,
        *,
        workflow_bundles: tuple[WorkflowObservationBundle, ...] = (),
        evaluation_bundles: tuple[EvaluationBundle, ...] = (),
        experiment_bundles: tuple[ExperimentBundle, ...] = (),
        diagnosis_bundles: tuple[DiagnosisBundle, ...] = (),
    ) -> "DashboardSnapshot":
        return _build_dashboard_snapshot(
            workflow_bundles,
            evaluation_bundles,
            experiment_bundles,
            diagnosis_bundles,
        )
```

Use existing validators before copying any mapping. Sort every collection by its canonical digest/identity, reject duplicate identities, project flows only through `project_trace_flow`, calculate fixed integer counts, and content-address the unsigned canonical mapping. Represent an empty flow for a trace as an evidence gap; do not synthesize ContextFrame nodes.

- [x] **Step 4: Run snapshot and existing Pathlight contract tests**

Run: `uv run python -m unittest -v tests.test_pathlight_dashboard tests.test_pathlight_flow tests.test_pathlight_query tests.test_pathlight_runtime_observation`

Expected: PASS.

- [x] **Step 5: Commit the snapshot boundary**

```bash
git add src/asterion/pathlight/dashboard.py src/asterion/pathlight/__init__.py tests/test_pathlight_dashboard.py
git commit -m "feat: add Pathlight Dashboard snapshot"
```

### Task 2: Loopback-Only Read API

**Files:**
- Create: `src/asterion/pathlight/dashboard_server.py`
- Modify: `tests/test_pathlight_dashboard.py`

**Interfaces:**
- Consumes: `DashboardSnapshot.to_mapping()`.
- Produces: `DashboardApplication(snapshot).response(method, target)` and `serve_dashboard(snapshot, host, port)`.

- [x] **Step 1: Write failing route and security tests**

```python
def test_api_is_read_only_same_origin_and_path_free(self) -> None:
    app = DashboardApplication(self.snapshot)
    response = app.response("GET", "/api/pathlight/v1/snapshot")
    self.assertEqual(response.status, 200)
    self.assertEqual(response.headers["Cache-Control"], "no-store")
    self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
    self.assertNotIn(str(self.private_root), response.body.decode())
    self.assertEqual(app.response("POST", "/api/pathlight/v1/snapshot").status, 405)

def test_non_loopback_host_is_rejected_before_server_creation(self) -> None:
    with self.assertRaises(PathlightError):
        validate_dashboard_bind("0.0.0.0", 8123)
```

- [x] **Step 2: Run the focused tests and confirm the server is absent**

Run: `uv run python -m unittest -v tests.test_pathlight_dashboard`

Expected: FAIL because `DashboardApplication` is not defined.

- [x] **Step 3: Implement pure route dispatch and the HTTP adapter**

```python
@dataclass(frozen=True, slots=True)
class DashboardResponse:
    status: int
    media_type: str
    headers: Mapping[str, str]
    body: bytes

class DashboardApplication:
    def response(self, method: str, target: str) -> DashboardResponse:
        return _dispatch_dashboard_request(self._snapshot, method, target)

def validate_dashboard_bind(host: str, port: int) -> tuple[str, int]:
    if host not in {"127.0.0.1", "::1", "localhost"} or not 0 <= port <= 65535:
        raise PathlightError("Pathlight Dashboard bind is invalid")
    return host, port

def serve_dashboard(snapshot: DashboardSnapshot, *, host: str, port: int) -> None:
    checked_host, checked_port = validate_dashboard_bind(host, port)
    _serve_http(DashboardApplication(snapshot), checked_host, checked_port)
```

Route only the exact API paths, exact trace UUID segments, `/`, `/app.js`, and `/styles.css`. Ignore query strings only after strict parsing; reject traversal, encoded slashes, fragments, unknown methods, and oversized targets. Use `ThreadingHTTPServer` only after bind validation, suppress request logging that could reveal targets, and emit fixed error bodies.

- [x] **Step 4: Run API, protocol, and redaction tests**

Run: `uv run python -m unittest -v tests.test_pathlight_dashboard tests.test_pathlight_protocol tests.test_pathlight_private_file`

Expected: PASS.

- [x] **Step 5: Commit the read API**

```bash
git add src/asterion/pathlight/dashboard_server.py tests/test_pathlight_dashboard.py
git commit -m "feat: serve read-only Pathlight Dashboard API"
```

### Task 3: Workflow-First Dashboard Interface

**Files:**
- Create: `src/asterion/pathlight/dashboard_assets/index.html`
- Create: `src/asterion/pathlight/dashboard_assets/app.js`
- Create: `src/asterion/pathlight/dashboard_assets/styles.css`
- Modify: `src/asterion/pathlight/dashboard_server.py`
- Modify: `tests/test_pathlight_dashboard.py`

**Interfaces:**
- Consumes: `GET /api/pathlight/v1/snapshot` and exact trace/flow routes.
- Produces: keyboard-accessible trace selection, flow timeline, node inspector, evaluation, experiment, and diagnosis views.

- [x] **Step 1: Write failing asset and redaction tests**

```python
def test_packaged_interface_contains_product_views_without_external_resources(self) -> None:
    app = DashboardApplication(self.snapshot)
    html = app.response("GET", "/").body.decode()
    script = app.response("GET", "/app.js").body.decode()
    css = app.response("GET", "/styles.css").body.decode()
    self.assertIn("Pathlight Dashboard", html)
    self.assertIn("ContextFrame", html + script)
    self.assertIn("证据缺口", html + script)
    self.assertNotRegex(html + script + css, r"https?://|@import|localStorage")
```

- [x] **Step 2: Run the focused test and confirm assets are absent**

Run: `uv run python -m unittest -v tests.test_pathlight_dashboard`

Expected: FAIL with a 404 asset response.

- [x] **Step 3: Implement the static application**

```javascript
const state = { snapshot: null, traceId: null, selectedNode: null, tab: "flow" };

async function loadSnapshot() {
  const response = await fetch("/api/pathlight/v1/snapshot", { cache: "no-store" });
  if (!response.ok) throw new Error("snapshot-unavailable");
  state.snapshot = await response.json();
  render();
}
```

Build semantic regions for the status bar, trace list, central ordered flow, node inspector, and evaluation/experiment/diagnosis tabs. Render all dynamic values through `textContent`; never use `innerHTML`. Show `missing` as a first-class amber evidence-gap row. Add focus-visible styles, skip link, ARIA labels, responsive single-column layout, and reduced-motion rules. Do not add icons, remote fonts, analytics, persistence, or mutation controls.

- [x] **Step 4: Run interface, server, and wheel file tests**

Run: `uv run python -m unittest -v tests.test_pathlight_dashboard`

Expected: PASS and all three assets are returned with exact media types.

- [x] **Step 5: Commit the interface**

```bash
git add src/asterion/pathlight/dashboard_assets src/asterion/pathlight/dashboard_server.py tests/test_pathlight_dashboard.py
git commit -m "feat: add workflow-first Pathlight Dashboard"
```

### Task 4: Provider-Free Foreground CLI

**Files:**
- Modify: `src/asterion/cli_pathlight.py`
- Modify: `tests/test_pathlight_cli.py`
- Modify: `tests/test_pathlight_dashboard.py`

**Interfaces:**
- Consumes: existing exact-file readers, `DashboardSnapshot.build`, and `serve_dashboard`.
- Produces: `asterion pathlight dashboard [--evidence-file FILE] [--evaluation-file FILE] [--experiment-file FILE] [--diagnosis-file FILE] [--host 127.0.0.1] [--port 0] [--open]`.

- [x] **Step 1: Write failing CLI preflight tests**

```python
def test_dashboard_cli_validates_all_inputs_before_serving_without_provider(self) -> None:
    with patch("asterion.cli_pathlight.serve_dashboard") as serve:
        code = main(
            ["pathlight", "dashboard", "--evaluation-file", str(self.evaluations)],
            entry_points=(FailIfLoadedEntryPoint(),),
            stdout=io.StringIO(),
        )
    self.assertEqual(code, 0)
    serve.assert_called_once()
```

Add cases for non-loopback hosts, relative paths, wrong basenames, tampered input, empty input, provider-loading sentinels, and browser opening only when `--open` is supplied.

- [x] **Step 2: Run CLI tests and confirm the command is absent**

Run: `uv run python -m unittest -v tests.test_pathlight_cli tests.test_pathlight_dashboard`

Expected: FAIL because `dashboard` is not a recognized Pathlight command.

- [x] **Step 3: Implement explicit input assembly and foreground serving**

```python
if args.command == "dashboard":
    snapshot = DashboardSnapshot.build(
        workflow_bundles=_read_workflow_inputs(args.evidence_file),
        evaluation_bundles=_read_evaluation_inputs(args.evaluation_file),
        experiment_bundles=_read_experiment_inputs(args.experiment_file),
        diagnosis_bundles=_read_diagnosis_inputs(args.diagnosis_file),
    )
    serve_dashboard(snapshot, host=args.host, port=args.port, open_browser=args.open)
    return {"status": "stopped", "snapshot_sha256": snapshot.snapshot_sha256}
```

Preflight every file and build the complete snapshot before server creation. Keep the process in the foreground. Browser opening uses the exact loopback URL after the server has bound and is opt-in only. A normal `KeyboardInterrupt` closes the server without a traceback or provider load.

- [x] **Step 4: Run CLI and complete related Pathlight tests**

Run: `uv run python -m unittest -v tests.test_pathlight_cli tests.test_pathlight_dashboard tests.test_pathlight_query tests.test_pathlight_experiment tests.test_pathlight_diagnosis`

Expected: PASS.

- [x] **Step 5: Commit the CLI**

```bash
git add src/asterion/cli_pathlight.py tests/test_pathlight_cli.py tests/test_pathlight_dashboard.py
git commit -m "feat: launch Pathlight Dashboard locally"
```

### Task 5: Real Evidence Closure, Documentation, and Distribution Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-08-02-asterion-pathlight-design.md`
- Modify: `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/superpowers/plans/2026-08-03-pathlight-dashboard.md`
- Test: `tests/test_pathlight_dashboard.py`

**Interfaces:**
- Consumes: the latest immutable Pathlight DCI evaluation, experiment, and diagnosis files plus any available safe workflow evidence.
- Produces: a verified startup command and a truthful Dashboard state that distinguishes observed flows from missing historical ContextFrames.

- [ ] **Step 1: Add a real-input snapshot test without model execution**

```python
def test_latest_dci_safe_inputs_build_a_dashboard_snapshot(self) -> None:
    snapshot = build_dashboard_snapshot_from_paths(
        evaluation_paths=(LATEST_EVALUATIONS,),
        experiment_paths=(LATEST_EXPERIMENT,),
        diagnosis_paths=(LATEST_DIAGNOSIS,),
    )
    self.assertGreater(snapshot.summary["evaluation_count"], 0)
    self.assertGreater(snapshot.summary["evidence_gap_count"], 0)
```

Keep machine-specific paths out of committed tests; pass real paths through an opt-in verification command or construct the same safe bundle shapes in fixtures.

- [ ] **Step 2: Run all related tests and repository checks**

Run:

```bash
uv run python -m unittest -v \
  tests.test_pathlight_dashboard \
  tests.test_pathlight_cli \
  tests.test_pathlight_flow \
  tests.test_pathlight_query \
  tests.test_pathlight_runtime_observation \
  tests.test_pathlight_evaluation \
  tests.test_pathlight_experiment \
  tests.test_pathlight_diagnosis
make lint
make docs-check
make promotion-check
```

Expected: every command passes; no provider, model, Judge, Opik SDK, or external network operation occurs.

- [ ] **Step 3: Verify the built wheel in isolation**

```bash
uv build
python -m venv "$DASHBOARD_VERIFY_VENV"
"$DASHBOARD_VERIFY_VENV/bin/pip" install dist/asterion-0.1.0-py3-none-any.whl
"$DASHBOARD_VERIFY_VENV/bin/asterion" pathlight dashboard --help
```

Expected: the installed wheel contains HTML/JS/CSS assets, imports without Opik, and exposes the Dashboard command. Use a task-specific temporary venv path and remove it after verification.

- [ ] **Step 4: Start the real Dashboard in the foreground and inspect safe API responses**

Run the CLI with the latest immutable evaluation, experiment, and diagnosis files, bind to `127.0.0.1`, and use an ephemeral port. Query `/api/pathlight/v1/summary` and `/api/pathlight/v1/snapshot`; confirm the known DCI evaluation counts and that historical final-context gaps remain explicit. Stop with `Ctrl-C`. Do not execute or rerun any benchmark.

- [ ] **Step 5: Update Chinese status documentation and close the plan**

Record the exact snapshot digest, input record counts, verified commands, and the distinction between Dashboard readiness and still-missing historical final ContextFrames. Mark each plan checkbox complete only after its named evidence passes.

- [ ] **Step 6: Commit verified Dashboard closure**

```bash
git add docs/superpowers/specs/2026-08-02-asterion-pathlight-design.md \
  docs/status/PATHLIGHT-DCI-DIAGNOSIS.md \
  docs/superpowers/plans/2026-08-03-pathlight-dashboard.md
git commit -m "docs: verify Pathlight Dashboard closure"
```
