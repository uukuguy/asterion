# Native DCI Research Example Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one package-uniform Native library entry, `prepare_native_application`, register `native.dci-research@1.0.0` and `native.controlled-code@1.0.0` beside the unchanged `native.packages@1.0.0`, and prove it with a provider-free example plus one bounded live retrieval preset.

**Architecture:** The Native provider keeps `native.packages` first and gains two single-package assemblies. `prepare_native_application` calls `create_provider()` directly, resolves every application on that provider, and selects one application by id and version. `NativeApplication.run` opens that assembly's host capabilities through `HostServiceFactoryRegistry.open`, creates one runtime from the operator registry, and executes with `run_composed_application`. Package differences stay in the assembly files and the operator material.

**Tech Stack:** Python 3.12, `unittest` (`IsolatedAsyncioTestCase`), existing Asterion assembly and composed runner, Make, bash.

## Global Constraints

- Do not add a second Pi runner, and do not change `PiChildProcess`.
- Do not change `prepare_prime_application`, IPython, accepted notes, or Prime session ownership.
- Do not add a Native CLI, provider discovery, or a central application registry.
- Do not add `asterion.application_index` rows. Do not modify `pyproject.toml`.
- Do not add an `executor.controlled` host-service entry point.
- Do not import `asterion.capabilities.dci` or `asterion.capabilities.controlled_code` from `src/asterion/agents/native/` or from `src/asterion/applications/native/provider.py`.
- The Native entry does not read `.env`, does not spawn Pi, and does not construct `PiChildProcess`.
- The Native entry calls `run_composed_application`. It does not call `run_application`.
- `native.packages` stays the first application on provider `native`. Its assembly file stays unchanged.
- One model call is allowed only in Task 4, only through `make native-dci-example`, and only after that preset's readiness check passes.
- The live factory options use tools `read,grep` and `max_turns` `6`. They pass `cwd` and do not pass `cwd_host_capability`.
- Live stdout is one body-free JSON object. A readiness failure exits 2 and does not call the model.
- Do not push `main`. Do not edit `CURRENT-STATE.md`, `RESUME-NEXT-SESSION.md`, `DECISIONS.md`, `CLAUDE.md`, or `MEMORY.md`.
- Do not repair `examples/asterion_dci_basic_example.sh`, `make dci-preflight`, or `asterion-dci run`.
- Do not live-run `native.controlled-code` or `native.packages`.

---

## File map

- Create `src/asterion/applications/native/assemblies/native-dci-research.json`: DCI retrieval assembly. Application id `native.dci-research`.
- Create `src/asterion/applications/native/assemblies/native-controlled-code.json`: controlled-code assembly. Application id `native.controlled-code`.
- Modify `src/asterion/applications/native/provider.py`: register both applications after `native.packages`.
- Modify `tools/check_promotion.py`: allow both new assembly paths.
- Modify `tests/test_native_package_host.py`: select the new applications by id.
- Create `src/asterion/agents/native/__init__.py`: export the public entry names.
- Create `src/asterion/agents/native/application.py`: `prepare_native_application` and `NativeApplication.run`.
- Create `tests/test_native_application.py`: provider-free prepare and run for both packages.
- Create `examples/applications/native_dci.py`: thin caller, plus the live command added in Task 4.
- Modify `examples/README.md`: one sentence for the new file.
- Create `examples/native_dci_example.sh`: thin shell. It does not source `.env`.
- Modify `Makefile`: target `native-dci-example`.
- Modify `docs/status/INDEX.md` and `docs/status/JOURNAL.md` only in Task 4, after the provider-free tests and the one live attempt.

`src/asterion/agents/__init__.py` stays unchanged.

## Contracts the tasks share

`resolve_installed_provider` resolves every application on the provider. Preparing one single-package application still requires both builtin packages, because `native.packages` names `controlled-code@1.0.0` and `dci@1.0.0`. Loading a sibling does not execute it. Union the package refs in provider order, first seen wins. With `native.packages` first, that order is `controlled-code@1.0.0`, then `dci@1.0.0`.

`RuntimeFactoryRegistry.select` uses the binding manifest and does not call the factory. Preparation must not call the factory. `run` calls it once.

`HostServiceFactoryRegistry.open` requires `capability_ids` to be a sorted unique tuple. Pass `tuple(plan.host_capabilities)`. A registered factory opens an option-backed service. A managed async context manager supplies an operator-owned service. A capability cannot be in both maps. `corpus.local-root` is option-backed (`root`). `executor.controlled` has no entry point and is managed.

The factory context uses provider id `native`, the selected application identity, the assembly path, the operator's runtime options, and `host_services={}`. Opened host services go only to `run_composed_application`. An empty host-service map is what makes runtime option `cwd` legal. Do not put the corpus service on the factory context.

`NativeApplication.run` marks the owner consumed before it inspects the signal, opens a service, or calls the factory. A second `run` raises `NativeApplicationError` after a success, a cancellation, or an open failure. An already cancelled signal raises `NativeApplicationError` before open and before the factory. `HostServiceRegistryError` and `ApplicationRunError` propagate.

Corpus paths in tests must be `str(Path(tempfile.mkdtemp()).resolve())`. A symlink prefix such as unresolved `/tmp` fails the corpus opener.

Public names:

```python
class NativeApplicationError(ValueError): ...

@dataclass(frozen=True)
class NativeApplicationSpec:
    application_id: str
    application_version: str

@dataclass(frozen=True)
class NativeOperatorContext:
    runtime_factories: RuntimeFactoryRegistry
    runtime_options: Mapping[str, str]
    host_service_options: Mapping[str, Mapping[str, str]]
    managed_host_services: Mapping[str, AbstractAsyncContextManager[object]]

def prepare_native_application(
    spec: NativeApplicationSpec,
    operator: NativeOperatorContext,
) -> NativeApplication: ...

class NativeApplication:
    @property
    def capability_packages(self) -> tuple[CapabilityPackageRef, ...]: ...

    async def run(
        self,
        input_text: str,
        *,
        run_id: str,
        signal: CancellationSignal | None = None,
    ) -> ApplicationRunResult: ...
```

---

### Task 1: Register the two single-package applications

**Files:**

- Create: `src/asterion/applications/native/assemblies/native-dci-research.json`
- Create: `src/asterion/applications/native/assemblies/native-controlled-code.json`
- Modify: `src/asterion/applications/native/provider.py`
- Modify: `tools/check_promotion.py`
- Test: `tests/test_native_package_host.py`

**Interfaces:**

- Consumes: `create_provider()`, `resolve_installed_provider`, `CapabilityPackageRef`.
- Produces: provider `native` applications in this order: `native.packages@1.0.0`, `native.dci-research@1.0.0`, `native.controlled-code@1.0.0`. No new entry-point rows.

- [ ] **Step 1: Write the failing selection test**

Add this method to `NativePackageHostTests` in `tests/test_native_package_host.py`:

```python
def test_single_package_applications_register_beside_native_packages(self) -> None:
    from asterion.applications.native import create_provider

    provider = create_provider()
    self.assertEqual(
        tuple(
            (item.application_id, item.version) for item in provider.applications
        ),
        (
            ("native.packages", "1.0.0"),
            ("native.dci-research", "1.0.0"),
            ("native.controlled-code", "1.0.0"),
        ),
    )
    names = {
        entry.name
        for entry in metadata.entry_points(group="asterion.application_index")
    }
    self.assertIn("native.packages__1.0.0", names)
    self.assertNotIn("native.dci-research__1.0.0", names)
    self.assertNotIn("native.controlled-code__1.0.0", names)

    resolved = resolve_installed_provider(
        provider,
        runtime_factories=default_runtime_factory_registry(),
        installed_packages=_bound_packages(),
    )
    self.assertEqual(resolved.applications[0].application_id, "native.packages")
    by_id = {
        application.application_id: application
        for application in resolved.applications
    }
    dci = by_id["native.dci-research"]
    code = by_id["native.controlled-code"]
    self.assertEqual(
        dci.capability_packages,
        (CapabilityPackageRef("dci", "1.0.0"),),
    )
    self.assertEqual(
        dci.assemblies[0].plan.host_capabilities,
        ("corpus.local-root",),
    )
    self.assertEqual(
        tuple(ref.capability_id for ref in dci.assemblies[0].plan.capability_refs),
        ("dci.research", "policy.local-corpus"),
    )
    self.assertEqual(dci.assemblies[0].runtime_id, "pi.reference")
    self.assertEqual(
        code.capability_packages,
        (CapabilityPackageRef("controlled-code", "1.0.0"),),
    )
    self.assertEqual(
        code.assemblies[0].plan.host_capabilities,
        ("executor.controlled",),
    )
    self.assertEqual(
        tuple(ref.capability_id for ref in code.assemblies[0].plan.capability_refs),
        (
            "evaluation.code-quality",
            "observability.execution-audit",
            "policy.controlled-code-check",
            "workflow.code-quality",
        ),
    )
    self.assertEqual(code.assemblies[0].runtime_id, "pi.reference")
    provider_source = (SOURCE / "applications/native/provider.py").read_text(
        encoding="utf-8"
    )
    for name in FORBIDDEN_IMPORTS:
        self.assertNotIn(name, provider_source)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest -v tests.test_native_package_host.NativePackageHostTests.test_single_package_applications_register_beside_native_packages`

Expected: FAIL. The application tuple is `(('native.packages', '1.0.0'),)`.

- [ ] **Step 3: Add the assemblies, the provider entries, and the promotion paths**

Create `src/asterion/applications/native/assemblies/native-dci-research.json`:

```json
{
  "protocol": "asterion.application-assembly/v1",
  "application_id": "native.dci-research",
  "version": "1.0.0",
  "runtime_id": "pi.reference",
  "capability_packages": [
    {"package_id": "dci", "version": "1.0.0"}
  ],
  "capabilities": [
    {"capability_id": "dci.research", "version": "1.0.0"},
    {"capability_id": "policy.local-corpus", "version": "1.0.0"}
  ],
  "host_capabilities": ["corpus.local-root"],
  "host_policies": [],
  "host_events": [],
  "host_artifacts": []
}
```

Create `src/asterion/applications/native/assemblies/native-controlled-code.json`:

```json
{
  "protocol": "asterion.application-assembly/v1",
  "application_id": "native.controlled-code",
  "version": "1.0.0",
  "runtime_id": "pi.reference",
  "capability_packages": [
    {"package_id": "controlled-code", "version": "1.0.0"}
  ],
  "capabilities": [
    {"capability_id": "evaluation.code-quality", "version": "1.0.0"},
    {"capability_id": "observability.execution-audit", "version": "1.0.0"},
    {"capability_id": "policy.controlled-code-check", "version": "1.0.0"},
    {"capability_id": "workflow.code-quality", "version": "1.0.0"}
  ],
  "host_capabilities": ["executor.controlled"],
  "host_policies": [],
  "host_events": [],
  "host_artifacts": []
}
```

Replace `create_provider` in `src/asterion/applications/native/provider.py` with:

```python
def create_provider() -> InstalledApplicationProvider:
    """Return the Native applications. native.packages stays first."""

    root = Path(str(resources.files("asterion"))).resolve()
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="native",
        resource_root=root,
        applications=(
            InstalledApplication(
                application_id="native.packages",
                version="1.0.0",
                assembly_paths=(
                    root / "applications/native/assemblies/native-packages.json",
                ),
                capability_packages=(
                    CapabilityPackageRef("controlled-code", "1.0.0"),
                    CapabilityPackageRef("dci", "1.0.0"),
                ),
                runtime_ids=("pi.reference",),
            ),
            InstalledApplication(
                application_id="native.dci-research",
                version="1.0.0",
                assembly_paths=(
                    root / "applications/native/assemblies/native-dci-research.json",
                ),
                capability_packages=(CapabilityPackageRef("dci", "1.0.0"),),
                runtime_ids=("pi.reference",),
            ),
            InstalledApplication(
                application_id="native.controlled-code",
                version="1.0.0",
                assembly_paths=(
                    root
                    / "applications/native/assemblies/native-controlled-code.json",
                ),
                capability_packages=(
                    CapabilityPackageRef("controlled-code", "1.0.0"),
                ),
                runtime_ids=("pi.reference",),
            ),
        ),
    )
```

Keep the existing imports. Do not import either capability implementation module.

In `tools/check_promotion.py`, add these entries immediately after the `native-packages.json` entry:

```python
    'applications/native/assemblies/native-controlled-code.json':
        'asterion.application-assembly/v1',
    'applications/native/assemblies/native-dci-research.json':
        'asterion.application-assembly/v1',
```

Do not edit `native-packages.json`. Do not edit `pyproject.toml`.

- [ ] **Step 4: Run the selection test and the promotion path check**

Run: `uv run python -m unittest -v tests.test_native_package_host`

Expected: `OK`.

Run: `uv run python -c "import runpy; runpy.run_path('tools/check_promotion.py', run_name='promotion_path_check')"`

Expected: exit 0. This runs the module-level path-set assert and does not call npm.

Then run: `make promotion-check`

Expected: exit 0, or a failure that happens only after the path-set assert because `node` or the npm cache is absent. If the failure text is a symmetric difference of assembly paths, add the missing path to `expected` and rerun. Do not treat a path mismatch as an environment failure. Do not start a model.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/native/assemblies/native-dci-research.json \
  src/asterion/applications/native/assemblies/native-controlled-code.json \
  src/asterion/applications/native/provider.py \
  tools/check_promotion.py \
  tests/test_native_package_host.py
git commit -m "feat: register native single-package applications"
```

---

### Task 2: Add the standard Native entry

**Files:**

- Create: `tests/test_native_application.py`
- Create: `src/asterion/agents/native/__init__.py`
- Create: `src/asterion/agents/native/application.py`

**Interfaces:**

- Consumes: Task 1 provider order and both new application ids.
- Produces: `prepare_native_application(spec, operator) -> NativeApplication`, `NativeApplication.run(input_text, *, run_id, signal=None) -> ApplicationRunResult`, `NativeApplication.capability_packages`, and `NativeApplicationError`.

- [ ] **Step 1: Write the failing entry test**

Create `tests/test_native_application.py`:

```python
"""Provider-free prepare and run for the standard Native entry."""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.runtime.factory import RuntimeFactoryBinding, RuntimeFactoryRegistry
from asterion.runtime.host import RunEvent, RuntimeManifest
from asterion.services.registry import HostServiceFactoryRegistry, HostServiceRegistryError


SOURCE = Path(__file__).resolve().parents[1] / "src" / "asterion"
QUESTION = "native-dci-question"
CODE_TARGET = "src/main.py"
FORBIDDEN_IMPORTS = (
    "asterion.capabilities.controlled_code",
    "asterion.capabilities.dci",
)


class _Signal:
    def __init__(self, cancelled: bool) -> None:
        self._cancelled = cancelled

    @property
    def cancelled(self) -> bool:
        return self._cancelled


class _Runtime:
    def __init__(self) -> None:
        self.manifest = RuntimeManifest(
            runtime_id="pi.reference",
            capabilities=("filesystem.read",),
        )
        self.requests: list[object] = []

    async def run(
        self,
        request: object,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del signal
        self.requests.append(request)
        run_id = request.run_id
        yield RunEvent(run_id, 1, "run.started", {"capabilities": []})
        yield RunEvent(
            run_id,
            2,
            "artifact.created",
            {
                "artifact": {
                    "artifact_id": "answer",
                    "kind": "answer",
                    "media_type": "text/plain",
                    "uri": "final.txt",
                }
            },
        )
        yield RunEvent(run_id, 3, "run.completed", {"status": "completed"})


class _Factory:
    def __init__(self, runtime: _Runtime) -> None:
        self.runtime = runtime
        self.calls: list[object] = []

    def __call__(self, context: object) -> _Runtime:
        self.calls.append(context)
        return self.runtime


class _Execution:
    status = "succeeded"
    exit_code = 0
    stdout_bytes = 1
    stderr_bytes = 2
    stdout_truncated = False
    stderr_truncated = False
    duration_ms = 3
    failure_class = None


class _Executor:
    def __init__(self) -> None:
        self.opened = False
        self.requests: list[object] = []

    async def __aenter__(self) -> "_Executor":
        self.opened = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False

    async def execute(self, request: object, *, signal: object | None = None) -> _Execution:
        del signal
        self.requests.append(request)
        return _Execution()


def _corpus() -> str:
    return str(Path(tempfile.mkdtemp()).resolve())


def _registry(factory: _Factory) -> RuntimeFactoryRegistry:
    return RuntimeFactoryRegistry(
        (
            RuntimeFactoryBinding(
                runtime_id="pi.reference",
                capabilities=("filesystem.read",),
                factory=factory,
            ),
        )
    )


class NativeApplicationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from asterion.agents.native.application import (
            NativeApplicationSpec,
            NativeOperatorContext,
            prepare_native_application,
        )

        self.NativeApplicationSpec = NativeApplicationSpec
        self.NativeOperatorContext = NativeOperatorContext
        self.prepare = prepare_native_application
        self.runtime = _Runtime()
        self.factory = _Factory(self.runtime)
        self.opens: list[dict[str, object]] = []
        real_open = HostServiceFactoryRegistry.open

        @asynccontextmanager
        async def spy_open(registry, **kwargs):
            self.opens.append(kwargs)
            async with real_open(registry, **kwargs) as services:
                yield services

        patcher = patch.object(HostServiceFactoryRegistry, "open", spy_open)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _operator(self, *, options, managed):
        return self.NativeOperatorContext(
            runtime_factories=_registry(self.factory),
            runtime_options={},
            host_service_options=options,
            managed_host_services=managed,
        )

    def _prepare(self, application_id: str, *, options, managed):
        return self.prepare(
            self.NativeApplicationSpec(
                application_id=application_id,
                application_version="1.0.0",
            ),
            self._operator(options=options, managed=managed),
        )

    def test_entry_source_does_not_import_package_implementations(self) -> None:
        paths = (
            SOURCE / "agents/native/__init__.py",
            SOURCE / "agents/native/application.py",
            SOURCE / "applications/native/provider.py",
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for name in FORBIDDEN_IMPORTS:
                self.assertNotIn(name, text)
            self.assertNotIn("PiChildProcess", text)
            self.assertNotIn("load_dotenv", text)
        entry = (SOURCE / "agents/native/application.py").read_text(encoding="utf-8")
        self.assertIn("run_composed_application", entry)
        self.assertNotIn("run_application", entry)
        self.assertNotIn(".env", entry)

    async def test_dci_research_runs_one_retrieval_without_preparing_the_runtime(self) -> None:
        corpus = _corpus()
        self.addCleanup(lambda: __import__("shutil").rmtree(corpus, ignore_errors=True))
        application = self._prepare(
            "native.dci-research",
            options={"corpus.local-root": {"root": corpus}},
            managed={},
        )
        self.assertEqual(self.factory.calls, [])
        self.assertEqual(
            application.capability_packages,
            (CapabilityPackageRef("dci", "1.0.0"),),
        )
        self.assertNotIn(
            CapabilityPackageRef("controlled-code", "1.0.0"),
            application.capability_packages,
        )

        result = await application.run(QUESTION, run_id="native-dci-test")

        self.assertEqual(len(self.factory.calls), 1)
        context = self.factory.calls[0]
        self.assertEqual(context.provider_id, "native")
        self.assertEqual(context.application_id, "native.dci-research")
        self.assertEqual(context.application_version, "1.0.0")
        self.assertEqual(list(context.host_services), [])
        self.assertNotIn("cwd_host_capability", context.options)
        self.assertEqual(len(self.opens), 1)
        self.assertEqual(
            self.opens[0]["options"]["corpus.local-root"]["root"],
            corpus,
        )
        self.assertEqual(dict(self.opens[0]["managed"]), {})
        self.assertEqual(self.runtime.requests[0].input_text, QUESTION)
        self.assertEqual(
            self.runtime.requests[0].requested_capabilities,
            ("filesystem.read",),
        )
        self.assertIn(
            "research.completed",
            [event["type"] for event in result.events],
        )
        self.assertIn(
            "application/vnd.dci.research+json",
            [artifact["media_type"] for artifact in result.artifacts],
        )

    async def test_relative_and_missing_corpus_fail_before_the_runtime_factory(self) -> None:
        from asterion.agents.native.application import NativeApplicationError

        for root in ("corpus", str(Path(_corpus()) / "missing")):
            self.factory.calls.clear()
            self.opens.clear()
            application = self._prepare(
                "native.dci-research",
                options={"corpus.local-root": {"root": root}},
                managed={},
            )
            with self.assertRaises(HostServiceRegistryError):
                await application.run(QUESTION, run_id="native-dci-test")
            self.assertEqual(self.factory.calls, [])
            with self.assertRaises(NativeApplicationError):
                await application.run(QUESTION, run_id="native-dci-again")

    async def test_cancelled_dci_run_fails_before_open_and_blocks_a_second_run(self) -> None:
        from asterion.agents.native.application import NativeApplicationError

        application = self._prepare(
            "native.dci-research",
            options={"corpus.local-root": {"root": _corpus()}},
            managed={},
        )
        with self.assertRaises(NativeApplicationError):
            await application.run(
                QUESTION,
                run_id="native-dci-test",
                signal=_Signal(True),
            )
        self.assertEqual(self.opens, [])
        self.assertEqual(self.factory.calls, [])
        with self.assertRaises(NativeApplicationError):
            await application.run(QUESTION, run_id="native-dci-again")

    async def test_second_dci_run_fails(self) -> None:
        from asterion.agents.native.application import NativeApplicationError

        corpus = _corpus()
        application = self._prepare(
            "native.dci-research",
            options={"corpus.local-root": {"root": corpus}},
            managed={},
        )
        await application.run(QUESTION, run_id="native-dci-test")
        with self.assertRaises(NativeApplicationError):
            await application.run(QUESTION, run_id="native-dci-again")
        self.assertEqual(len(self.factory.calls), 1)

    async def test_controlled_code_uses_the_managed_executor(self) -> None:
        executor = _Executor()
        application = self._prepare(
            "native.controlled-code",
            options={},
            managed={"executor.controlled": executor},
        )
        self.assertEqual(self.factory.calls, [])
        self.assertFalse(executor.opened)
        self.assertEqual(
            application.capability_packages,
            (CapabilityPackageRef("controlled-code", "1.0.0"),),
        )
        self.assertNotIn(
            CapabilityPackageRef("dci", "1.0.0"),
            application.capability_packages,
        )

        result = await application.run(CODE_TARGET, run_id="native-code-test")

        self.assertEqual(len(self.factory.calls), 1)
        self.assertEqual(list(self.factory.calls[0].host_services), [])
        self.assertTrue(executor.opened)
        self.assertEqual(executor.requests[0].target, CODE_TARGET)
        self.assertEqual(self.runtime.requests, [])
        types = [event["type"] for event in result.events]
        media = [artifact["media_type"] for artifact in result.artifacts]
        self.assertIn("workflow.code-quality.completed", types)
        self.assertIn("audit.execution-recorded", types)
        self.assertIn("application/vnd.dci.code-quality+json", media)
        self.assertIn("application/vnd.dci.code-quality-verdict+json", media)

    async def test_cancelled_controlled_code_run_fails_before_open(self) -> None:
        from asterion.agents.native.application import NativeApplicationError

        executor = _Executor()
        application = self._prepare(
            "native.controlled-code",
            options={},
            managed={"executor.controlled": executor},
        )
        with self.assertRaises(NativeApplicationError):
            await application.run(
                CODE_TARGET,
                run_id="native-code-test",
                signal=_Signal(True),
            )
        self.assertFalse(executor.opened)
        self.assertEqual(self.factory.calls, [])
        self.assertEqual(self.opens, [])
        with self.assertRaises(NativeApplicationError):
            await application.run(CODE_TARGET, run_id="native-code-again")

    def test_host_service_keys_must_match_the_selected_assembly(self) -> None:
        from asterion.agents.native.application import NativeApplicationError

        executor = _Executor()
        corpus = _corpus()
        prepared = self._prepare(
            "native.packages",
            options={"corpus.local-root": {"root": corpus}},
            managed={"executor.controlled": executor},
        )
        self.assertFalse(executor.opened)
        self.assertEqual(self.factory.calls, [])
        self.assertEqual(
            prepared.capability_packages,
            (
                CapabilityPackageRef("controlled-code", "1.0.0"),
                CapabilityPackageRef("dci", "1.0.0"),
            ),
        )
        cases = (
            ("native.packages", {"corpus.local-root": {"root": corpus}}, {}),
            (
                "native.packages",
                {},
                {"executor.controlled": executor},
            ),
            (
                "native.dci-research",
                {"corpus.local-root": {"root": corpus}},
                {"corpus.local-root": executor},
            ),
            ("native.dci-research", {}, {}),
            ("native.missing", {"corpus.local-root": {"root": corpus}}, {}),
        )
        for application_id, options, managed in cases:
            with self.subTest(application_id=application_id):
                with self.assertRaises(NativeApplicationError) as raised:
                    self._prepare(
                        application_id,
                        options=options,
                        managed=managed,
                    )
                self.assertIsNone(raised.exception.__cause__)
        with self.assertRaises(NativeApplicationError) as raised:
            self.prepare(
                self.NativeApplicationSpec(
                    application_id="native.dci-research",
                    application_version="9.9.9",
                ),
                self._operator(
                    options={"corpus.local-root": {"root": corpus}},
                    managed={},
                ),
            )
        self.assertIsNone(raised.exception.__cause__)
        with self.assertRaises(NativeApplicationError) as raised:
            self.prepare(
                self.NativeApplicationSpec(
                    application_id="native.dci-research",
                    application_version="1.0.0",
                ),
                self.NativeOperatorContext(
                    runtime_factories=RuntimeFactoryRegistry(()),
                    runtime_options={},
                    host_service_options={"corpus.local-root": {"root": corpus}},
                    managed_host_services={},
                ),
            )
        self.assertIsNone(raised.exception.__cause__)
        self.assertFalse(executor.opened)
        self.assertEqual(self.factory.calls, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest -v tests.test_native_application`

Expected: ERROR, `ModuleNotFoundError: No module named 'asterion.agents.native'`.

- [ ] **Step 3: Implement the entry**

Create `src/asterion/agents/native/__init__.py`:

```python
"""Standard library entry for Native applications."""

from asterion.agents.native.application import (
    NativeApplication,
    NativeApplicationError,
    NativeApplicationSpec,
    NativeOperatorContext,
    prepare_native_application,
)

__all__ = (
    "NativeApplication",
    "NativeApplicationError",
    "NativeApplicationSpec",
    "NativeOperatorContext",
    "prepare_native_application",
)
```

Create `src/asterion/agents/native/application.py`:

```python
"""One prepare and run door for every Native application."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from asterion.applications.first_party_packages import builtin_capability_registrations
from asterion.applications.native.provider import create_provider
from asterion.applications.provider import (
    ApplicationProviderError,
    InstalledApplication,
    InstalledApplicationProvider,
)
from asterion.applications.selection import (
    parse_application_selector,
    select_installed_application,
)
from asterion.applications.provider import resolve_installed_provider
from asterion.capability_packages.preparation import (
    load_prepared_capability_source,
    prepare_capability_source,
)
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource
from asterion.runner.application import ApplicationRunResult
from asterion.runner.composed import run_composed_application
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryRegistry
from asterion.runtime.host import CancellationSignal
from asterion.services.registry import HostServiceFactoryRegistry


class NativeApplicationError(ValueError):
    """Raised when Native preparation or a run contract fails."""


@dataclass(frozen=True)
class NativeApplicationSpec:
    application_id: str
    application_version: str


@dataclass(frozen=True)
class NativeOperatorContext:
    runtime_factories: RuntimeFactoryRegistry
    runtime_options: Mapping[str, str]
    host_service_options: Mapping[str, Mapping[str, str]]
    managed_host_services: Mapping[str, AbstractAsyncContextManager[object]]


class NativeApplication:
    def __init__(
        self,
        application: InstalledApplication,
        operator: NativeOperatorContext,
    ) -> None:
        self._application = application
        self._operator = operator
        self._consumed = False

    @property
    def capability_packages(self) -> tuple[CapabilityPackageRef, ...]:
        return self._application.capability_packages

    async def run(
        self,
        input_text: str,
        *,
        run_id: str,
        signal: CancellationSignal | None = None,
    ) -> ApplicationRunResult:
        if self._consumed:
            raise NativeApplicationError("native application run is already consumed")
        self._consumed = True
        if signal is not None and signal.cancelled:
            raise NativeApplicationError("native application run was cancelled")
        assembly = self._application.assemblies[0]
        plan = assembly.plan
        async with HostServiceFactoryRegistry().open(
            provider_id="native",
            application_id=self._application.application_id,
            application_version=self._application.version,
            capability_ids=tuple(plan.host_capabilities),
            options=self._operator.host_service_options,
            managed=self._operator.managed_host_services,
        ) as host_services:
            binding = self._operator.runtime_factories.select(assembly.runtime_id)
            runtime = binding.factory(
                RuntimeFactoryContext(
                    provider_id="native",
                    application_id=self._application.application_id,
                    application_version=self._application.version,
                    runtime_id=assembly.runtime_id,
                    assembly_path=assembly.path,
                    options=self._operator.runtime_options,
                    host_services={},
                )
            )
            return await run_composed_application(
                plan,
                implementations=self._application.implementations,
                runtime=runtime,
                run_id=run_id,
                input_text=input_text,
                host_services=host_services,
                signal=signal,
            )


def prepare_native_application(
    spec: NativeApplicationSpec,
    operator: NativeOperatorContext,
) -> NativeApplication:
    """Validate one Native application without starting a runtime."""

    try:
        provider = create_provider()
        resolved = resolve_installed_provider(
            provider,
            runtime_factories=operator.runtime_factories,
            installed_packages=_installed_packages(provider),
        )
        selected = select_installed_application(
            resolved,
            parse_application_selector(
                f"{spec.application_id}@{spec.application_version}"
            ),
        )
    except ApplicationProviderError:
        raise NativeApplicationError("native application is unavailable") from None
    if len(selected.assemblies) != 1:
        raise NativeApplicationError("native application assembly is unavailable")
    host_ids = set(selected.assemblies[0].plan.host_capabilities)
    option_keys = set(operator.host_service_options)
    managed_keys = set(operator.managed_host_services)
    if option_keys & managed_keys or option_keys | managed_keys != host_ids:
        raise NativeApplicationError(
            "native application host services do not match"
        )
    return NativeApplication(selected, operator)


def _installed_packages(provider: InstalledApplicationProvider):
    refs: list[CapabilityPackageRef] = []
    for application in provider.applications:
        for ref in application.capability_packages:
            if ref not in refs:
                refs.append(ref)
    source = BuiltinCapabilitySource(builtin_capability_registrations())
    return tuple(
        load_prepared_capability_source(
            prepare_capability_source(ref, (source,), None)
        )
        for ref in refs
    )
```

Do not store the runtime on `NativeApplication`. Do not call a `close` method. Do not branch on `application_id` or on a host capability id. The source text must not contain `asterion.capabilities.dci`, `asterion.capabilities.controlled_code`, `PiChildProcess`, `load_dotenv`, `.env`, or the contiguous string `run_application`.

- [ ] **Step 4: Run the entry tests**

Run: `uv run python -m unittest -v tests.test_native_application tests.test_native_package_host`

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_native_application.py \
  src/asterion/agents/native/__init__.py \
  src/asterion/agents/native/application.py
git commit -m "feat: add the native application entry"
```

---

### Task 3: Add the provider-free DCI example

**Files:**

- Create: `examples/applications/native_dci.py`
- Modify: `examples/README.md`
- Modify: `tests/test_native_application.py`

**Interfaces:**

- Consumes: `prepare_native_application`, `NativeApplicationSpec`, `NativeOperatorContext`, `NativeApplication.run`.
- Produces: `run_native_dci_research(*, runtime_factories, runtime_options, corpus_root, question, run_id) -> ApplicationRunResult` and module constant `QUESTION`.

- [ ] **Step 1: Write the failing example test**

Append this class to `tests/test_native_application.py`:

```python
class NativeDciExampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_example_calls_the_standard_entry(self) -> None:
        import importlib.util
        import inspect

        path = Path(__file__).resolve().parents[1] / "examples/applications/native_dci.py"
        spec = importlib.util.spec_from_file_location("native_dci_example", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        helper_source = inspect.getsource(module.run_native_dci_research)
        for banned in (
            "load_dotenv",
            ".env",
            "PiChildProcess",
            "resolve_assembly",
            "HostServiceFactoryRegistry",
            "applications[0]",
        ):
            self.assertNotIn(banned, helper_source)
        self.assertIn("prepare_native_application", helper_source)
        self.assertEqual(
            module.QUESTION,
            "Answer the following question using only wiki_dump.jsonl in the current directory. Do not use web search. Use rg instead of grep for fast searching. Question: In which street did the Great Fire of London originate?",
        )

        runtime = _Runtime()
        factory = _Factory(runtime)
        corpus = _corpus()
        self.addCleanup(lambda: __import__("shutil").rmtree(corpus, ignore_errors=True))
        result = await module.run_native_dci_research(
            runtime_factories=_registry(factory),
            runtime_options={},
            corpus_root=corpus,
            question=QUESTION,
            run_id="native-dci-example-test",
        )
        self.assertEqual(len(factory.calls), 1)
        self.assertEqual(list(factory.calls[0].host_services), [])
        self.assertEqual(runtime.requests[0].input_text, QUESTION)
        self.assertIn(
            "research.completed",
            [event["type"] for event in result.events],
        )
        readme = (Path(__file__).resolve().parents[1] / "examples/README.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("prepare_native_application", readme)
        self.assertIn("native_dci.py", readme)
        self.assertIn("every Native application", readme)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m unittest -v tests.test_native_application.NativeDciExampleTests`

Expected: ERROR, missing `examples/applications/native_dci.py`.

- [ ] **Step 3: Add the example and the README sentence**

Create `examples/applications/native_dci.py`:

```python
"""Run native.dci-research through the standard Native entry."""

from __future__ import annotations

from collections.abc import Mapping

from asterion.agents.native.application import (
    NativeApplicationSpec,
    NativeOperatorContext,
    prepare_native_application,
)
from asterion.runner.application import ApplicationRunResult
from asterion.runtime.factory import RuntimeFactoryRegistry


QUESTION = (
    "Answer the following question using only wiki_dump.jsonl in the current "
    "directory. Do not use web search. Use rg instead of grep for fast "
    "searching. Question: In which street did the Great Fire of London originate?"
)


async def run_native_dci_research(
    *,
    runtime_factories: RuntimeFactoryRegistry,
    runtime_options: Mapping[str, str],
    corpus_root: str,
    question: str,
    run_id: str,
) -> ApplicationRunResult:
    """Prepare and run one DCI retrieval. The caller owns the registry."""

    application = prepare_native_application(
        NativeApplicationSpec(
            application_id="native.dci-research",
            application_version="1.0.0",
        ),
        NativeOperatorContext(
            runtime_factories=runtime_factories,
            runtime_options=runtime_options,
            host_service_options={
                "corpus.local-root": {"root": corpus_root},
            },
            managed_host_services={},
        ),
    )
    return await application.run(question, run_id=run_id)
```

In `examples/README.md`, keep the existing paragraphs. Add this paragraph after the first one:

```markdown
`applications/native_dci.py` runs the Native DCI retrieval application through
`prepare_native_application`. The same entry runs every Native application.
```

Do not edit `examples/applications/dci_research.py` or `examples/applications/controlled_code.py`. Do not add a second example script.

- [ ] **Step 4: Run the example test**

Run: `uv run python -m unittest -v tests.test_native_application tests.test_native_package_host`

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add examples/applications/native_dci.py examples/README.md tests/test_native_application.py
git commit -m "feat: add the native dci research example"
```

---

### Task 4: Add the one-question live preset

**Files:**

- Modify: `examples/applications/native_dci.py`
- Create: `examples/native_dci_example.sh`
- Modify: `Makefile`
- Modify: `tests/test_native_application.py`
- Modify: `docs/status/INDEX.md`
- Modify: `docs/status/JOURNAL.md`

**Interfaces:**

- Consumes: `run_native_dci_research` and `QUESTION` from Task 3.
- Produces: `resolve_live_configuration(root, env, *, which) -> LiveConfiguration`, `live_runtime_options(config) -> dict[str, str]`, `run_live(*, root, env, prepare, which) -> int`, and Make target `native-dci-example`.

The provider-free tests in this task must not call a model. The only model call is the final `make native-dci-example` step, and only when readiness returns a configuration.

- [ ] **Step 1: Write the failing preset tests**

Append this class to `tests/test_native_application.py`:

```python
class NativeDciLivePresetTests(unittest.IsolatedAsyncioTestCase):
    def _load(self):
        import importlib.util

        path = Path(__file__).resolve().parents[1] / "examples/applications/native_dci.py"
        spec = importlib.util.spec_from_file_location("native_dci_live", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_shell_and_makefile_are_thin(self) -> None:
        root = Path(__file__).resolve().parents[1]
        shell = (root / "examples/native_dci_example.sh").read_text(encoding="utf-8")
        makefile = (root / "Makefile").read_text(encoding="utf-8")
        self.assertIn("examples/applications/native_dci.py --live", shell)
        self.assertNotIn("source ", shell)
        self.assertNotIn("set -a", shell)
        self.assertIn("\nnative-dci-example:\n", makefile)
        self.assertIn("bash examples/native_dci_example.sh", makefile)
        entry = (SOURCE / "agents/native/application.py").read_text(encoding="utf-8")
        self.assertNotIn("load_dotenv", entry)
        example = (root / "examples/applications/native_dci.py").read_text(encoding="utf-8")
        self.assertIn("override=False", example)
        self.assertNotIn("PiChildProcess", example)

    def test_missing_provider_does_not_call_prepare(self) -> None:
        module = self._load()
        root = Path(tempfile.mkdtemp()).resolve()
        calls: list[object] = []

        def prepare(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("prepare")

        import asyncio
        import contextlib
        import io

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = asyncio.run(
                module.run_live(
                    root=root,
                    env={"DCI_MODEL": "deepseek-flash"},
                    prepare=prepare,
                    which=lambda name: None,
                )
            )
        self.assertEqual(code, 2)
        self.assertEqual(calls, [])
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue().strip(), "missing DCI_PROVIDER")

    def test_runtime_failure_is_body_free_and_hides_the_exception(self) -> None:
        import asyncio
        import contextlib
        import io

        from asterion.runner.application import ApplicationRunError

        module = self._load()
        config = module.LiveConfiguration(
            provider="deepseek",
            model="deepseek-flash",
            node="/usr/bin/node",
            cli="/tmp/cli.js",
            corpus="/tmp/wiki_corpus",
            agent_dir="/tmp/agent",
            evidence_root="/tmp/outputs/native-dci-example",
            environment={"PI_CODING_AGENT_DIR": "/tmp/agent"},
        )
        options = module.live_runtime_options(config)
        self.assertEqual(options["tools"], "read,grep")
        self.assertEqual(options["max_turns"], "6")
        self.assertEqual(options["cwd"], config.corpus)
        self.assertNotIn("cwd_host_capability", options)
        self.assertNotIn("bash", options["tools"])
        self.assertNotIn("thinking_level", options)

        def prepare(*args, **kwargs):
            del args, kwargs
            raise ApplicationRunError("SECRET-PROVIDER-PAYLOAD")

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = asyncio.run(
                module.execute_live(config, prepare=prepare, run_id="native-dci-test")
            )
        self.assertEqual(code, 1)
        payload = __import__("json").loads(stdout.getvalue())
        self.assertEqual(
            set(payload),
            {"application_id", "run_id", "status"},
        )
        self.assertEqual(payload["application_id"], "native.dci-research")
        self.assertEqual(payload["run_id"], "native-dci-test")
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(stderr.getvalue().strip(), "native-dci-example: run failed")
        self.assertNotIn("SECRET-PROVIDER-PAYLOAD", stdout.getvalue())
        self.assertNotIn("SECRET-PROVIDER-PAYLOAD", stderr.getvalue())

    def test_ready_configuration_matches_the_factory_path_rule(self) -> None:
        import os
        import stat

        from asterion.runtime.defaults import RuntimeFactoryError, _pi_exact_path

        module = self._load()
        root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        node = root / "bin" / "node"
        node.parent.mkdir()
        node.write_text("#!/bin/sh\n", encoding="utf-8")
        node.chmod(node.stat().st_mode | stat.S_IEXEC)
        checkout = root / "pi"
        cli = checkout / "packages/coding-agent/dist/cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("cli", encoding="utf-8")
        agent = root / "agent"
        agent.mkdir()
        corpus = root / "corpus" / "wiki_corpus"
        corpus.mkdir(parents=True)
        (corpus / "wiki_dump.jsonl").write_text("{}\n", encoding="utf-8")
        self.assertEqual(_pi_exact_path(str(node), require_directory=False), node)
        self.assertEqual(_pi_exact_path(str(corpus), require_directory=True), corpus)
        config = module.resolve_live_configuration(
            root,
            {
                "DCI_PROVIDER": "deepseek",
                "DCI_MODEL": "deepseek-flash",
                "DCI_PI_AGENT_DIR": str(agent),
            },
            which=lambda name: str(node) if name == "node" else None,
        )
        self.assertEqual(config.corpus, str(corpus))
        self.assertEqual(config.node, str(node))
        self.assertEqual(config.evidence_root, str(root / "outputs" / "native-dci-example"))
        self.assertEqual(config.environment["PI_CODING_AGENT_DIR"], str(agent))
        self.assertTrue((root / "outputs").is_dir())
        fallback = module.resolve_live_configuration(
            root,
            {
                "DCI_PROVIDER": "deepseek",
                "DCI_MODEL": "deepseek-flash",
                "DCI_PI_DIR": str(root / "missing-pi"),
                "DCI_PI_AGENT_DIR": str(agent),
            },
            which=lambda name: str(node) if name == "node" else None,
        )
        self.assertEqual(fallback.cli, str(cli))
        linked_root = root / "linked-root"
        linked_root.mkdir()
        os.symlink(corpus, linked_root / "wiki_corpus", target_is_directory=True)
        with self.assertRaises(module.ReadinessFailure) as raised:
            module.resolve_live_configuration(
                root,
                {
                    "DCI_PROVIDER": "deepseek",
                    "DCI_MODEL": "deepseek-flash",
                    "DCI_PI_AGENT_DIR": str(agent),
                    "ASTERION_DCI_CORPUS_ROOT": str(linked_root),
                },
                which=lambda name: str(node) if name == "node" else None,
            )
        self.assertEqual(raised.exception.reason, "corpus is unavailable")
        with self.assertRaises(RuntimeFactoryError):
            _pi_exact_path(str(linked_root / "wiki_corpus"), require_directory=True)
        with self.assertRaises(module.ReadinessFailure) as raised:
            module.resolve_live_configuration(
                root,
                {
                    "DCI_PROVIDER": "deepseek",
                    "DCI_MODEL": "deepseek-flash",
                    "DCI_PI_AGENT_DIR": str(agent),
                },
                which=lambda name: None,
            )
        self.assertEqual(raised.exception.reason, "node executable is unavailable")
        with self.assertRaises(module.ReadinessFailure) as raised:
            module.resolve_live_configuration(
                root,
                {"DCI_PROVIDER": "deepseek"},
                which=lambda name: (_ for _ in ()).throw(AssertionError("which")),
            )
        self.assertEqual(raised.exception.reason, "missing DCI_MODEL")
        with self.assertRaises(module.ReadinessFailure) as raised:
            module.resolve_live_configuration(
                root,
                {
                    "DCI_PROVIDER": "deepseek",
                    "DCI_MODEL": "deepseek-flash",
                    "DCI_PI_AGENT_DIR": str(root / "missing-agent"),
                },
                which=lambda name: str(node) if name == "node" else None,
            )
        self.assertEqual(raised.exception.reason, "agent directory is unavailable")
        outputs = root / "outputs"
        __import__("shutil").rmtree(outputs)
        os.symlink(agent, outputs, target_is_directory=True)
        with self.assertRaises(module.ReadinessFailure) as raised:
            module.resolve_live_configuration(
                root,
                {
                    "DCI_PROVIDER": "deepseek",
                    "DCI_MODEL": "deepseek-flash",
                    "DCI_PI_AGENT_DIR": str(agent),
                },
                which=lambda name: str(node) if name == "node" else None,
            )
        self.assertEqual(raised.exception.reason, "evidence parent is unavailable")
        empty = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: __import__("shutil").rmtree(empty, ignore_errors=True))
        with self.assertRaises(module.ReadinessFailure) as raised:
            module.resolve_live_configuration(
                empty,
                {"DCI_PROVIDER": "deepseek", "DCI_MODEL": "deepseek-flash"},
                which=lambda name: str(node),
            )
        self.assertEqual(raised.exception.reason, "pi checkout is unavailable")
```

- [ ] **Step 2: Run the preset tests to verify they fail**

Run: `uv run python -m unittest -v tests.test_native_application.NativeDciLivePresetTests`

Expected: ERROR or FAIL because `run_live`, `examples/native_dci_example.sh`, and the Make target do not exist yet.

- [ ] **Step 3: Add the live command, the shell, and the Make target**

Append this code to `examples/applications/native_dci.py`. Keep `run_native_dci_research` and `QUESTION` unchanged.

```python
import asyncio
import json
import os
import shutil
import stat
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ReadinessFailure(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LiveConfiguration:
    provider: str
    model: str
    node: str
    cli: str
    corpus: str
    agent_dir: str
    evidence_root: str
    environment: dict[str, str]


def repository_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "asterion").is_dir():
            return parent
    raise ReadinessFailure("evidence parent is unavailable")


def path_is_exact(value: str, *, require_directory: bool) -> bool:
    if type(value) is not str:
        return False
    path = Path(value)
    if (
        not path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts[1:])
        or str(path.resolve(strict=False)) != value
    ):
        return False
    current = Path(path.anchor)
    try:
        details = current.stat(follow_symlinks=False)
    except OSError:
        return False
    for component in path.parts[1:]:
        current /= component
        try:
            details = current.stat(follow_symlinks=False)
        except FileNotFoundError:
            return current == path and not require_directory
        except OSError:
            return False
        if stat.S_ISLNK(details.st_mode):
            return False
    if require_directory and not stat.S_ISDIR(details.st_mode):
        return False
    return True


def _real_directory(path: Path) -> bool:
    try:
        details = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode)


def _regular_file(path: Path) -> bool:
    try:
        details = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(details.st_mode) and not stat.S_ISLNK(details.st_mode)


def _required(env: Mapping[str, str], name: str, reason: str) -> str:
    value = env.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ReadinessFailure(reason)
    return value


def _pi_checkout(root: Path, env: Mapping[str, str]) -> Path:
    configured = env.get("DCI_PI_DIR")
    candidates = []
    if isinstance(configured, str) and configured.strip():
        candidates.append(Path(configured).expanduser())
    candidates.append(root / "pi")
    for checkout in candidates:
        cli = checkout / "packages/coding-agent/dist/cli.js"
        if _real_directory(checkout) and _regular_file(cli):
            return checkout
    raise ReadinessFailure("pi checkout is unavailable")


def _node_path(which) -> str:
    found = which("node")
    if not isinstance(found, str) or not found:
        raise ReadinessFailure("node executable is unavailable")
    node = Path(found).resolve()
    text = str(node)
    if not path_is_exact(text, require_directory=False):
        raise ReadinessFailure("node executable is unavailable")
    try:
        details = node.stat(follow_symlinks=False)
    except OSError:
        raise ReadinessFailure("node executable is unavailable") from None
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or stat.S_IMODE(details.st_mode) & 0o111 == 0
        or not os.access(node, os.X_OK)
    ):
        raise ReadinessFailure("node executable is unavailable")
    return text


def resolve_live_configuration(root: Path, env: Mapping[str, str], *, which=shutil.which) -> LiveConfiguration:
    """Return one live configuration or raise a public readiness failure."""

    provider = _required(env, "DCI_PROVIDER", "missing DCI_PROVIDER")
    model = _required(env, "DCI_MODEL", "missing DCI_MODEL")
    checkout = _pi_checkout(root, env)
    cli = checkout / "packages/coding-agent/dist/cli.js"
    if not cli.is_absolute():
        cli = Path.cwd() / cli
    node = _node_path(which)
    raw_agent = env.get("DCI_PI_AGENT_DIR")
    agent = Path(raw_agent).expanduser() if isinstance(raw_agent, str) and raw_agent else Path("~/.pi/agent").expanduser()
    if not agent.is_absolute() or not _real_directory(agent):
        raise ReadinessFailure("agent directory is unavailable")
    configured_corpus = env.get("ASTERION_DCI_CORPUS_ROOT")
    if isinstance(configured_corpus, str) and Path(configured_corpus).is_absolute():
        corpus = Path(configured_corpus) / "wiki_corpus"
    else:
        corpus = root / "corpus" / "wiki_corpus"
    corpus_text = str(corpus)
    if (
        not path_is_exact(corpus_text, require_directory=True)
        or not (corpus / "wiki_dump.jsonl").is_file()
    ):
        raise ReadinessFailure("corpus is unavailable")
    outputs = root / "outputs"
    if not outputs.exists():
        outputs.mkdir(mode=0o755)
    elif not _real_directory(outputs):
        raise ReadinessFailure("evidence parent is unavailable")
    evidence = outputs / "native-dci-example"
    if evidence.exists() and not _real_directory(evidence):
        raise ReadinessFailure("evidence parent is unavailable")
    evidence_text = str(evidence)
    if not path_is_exact(evidence_text, require_directory=False):
        raise ReadinessFailure("evidence parent is unavailable")
    environment = {str(key): str(value) for key, value in env.items()}
    environment["PI_CODING_AGENT_DIR"] = str(agent)
    return LiveConfiguration(
        provider=provider,
        model=model,
        node=node,
        cli=str(cli),
        corpus=corpus_text,
        agent_dir=str(agent),
        evidence_root=evidence_text,
        environment=environment,
    )


def live_runtime_options(config: LiveConfiguration) -> dict[str, str]:
    return {
        "command": json.dumps(
            [config.node, config.cli],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "cwd": config.corpus,
        "environment": json.dumps(
            config.environment,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "evidence_root": config.evidence_root,
        "max_turns": "6",
        "tools": "read,grep",
        "provider": config.provider,
        "model": config.model,
    }


def public_status_line(run_id: str, status: str) -> str:
    return json.dumps(
        {
            "application_id": "native.dci-research",
            "run_id": run_id,
            "status": status,
        },
        sort_keys=True,
    )


async def execute_live(config: LiveConfiguration, *, prepare=None, run_id: str) -> int:
    try:
        if prepare is not None:
            prepare(config)
            raise RuntimeError("live prepare injection returned")
        from asterion.runtime.defaults import default_runtime_factory_registry

        await run_native_dci_research(
            runtime_factories=default_runtime_factory_registry(),
            runtime_options=live_runtime_options(config),
            corpus_root=config.corpus,
            question=QUESTION,
            run_id=run_id,
        )
    except Exception:
        print(public_status_line(run_id, "failed"))
        print("native-dci-example: run failed", file=sys.stderr)
        return 1
    print(public_status_line(run_id, "completed"))
    return 0


async def run_live(*, root: Path, env: Mapping[str, str], prepare=None, which=shutil.which) -> int:
    try:
        config = resolve_live_configuration(root, env, which=which)
    except ReadinessFailure as error:
        print(error.reason, file=sys.stderr)
        return 2
    return await execute_live(
        config,
        prepare=prepare,
        run_id="native-dci-" + uuid.uuid4().hex,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["--live"]:
        print("native-dci-example: use --live", file=sys.stderr)
        return 2
    root = repository_root()
    env_file = root / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=False)
    return asyncio.run(run_live(root=root, env=os.environ))


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `examples/native_dci_example.sh` with mode `0755`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec uv run python examples/applications/native_dci.py --live
```

In `Makefile`, add `native-dci-example` to the existing `.PHONY` line that lists `dci-basic-example`:

```makefile
.PHONY: dci-basic-example dci-runtime-context-example native-dci-example
```

After the `dci-runtime-context-example` recipe, add this target. The recipe line starts with a tab:

```makefile
native-dci-example:
	bash examples/native_dci_example.sh
```

Do not attach this target to `verify.native-verified-loop.small`.

Move `import asyncio`, `import json`, `import os`, `import shutil`, `import stat`, `import sys`, `import uuid`, `from dataclasses import dataclass`, `from pathlib import Path`, and `from dotenv import load_dotenv` to the top of `examples/applications/native_dci.py` with the other imports. Do not leave a second import block in the middle of the file. `main` is the only function that calls `load_dotenv`. `run_native_dci_research` does not.

The live command does not construct `PiChildProcess`. It does not print `config.environment`, the `.env` file, or the exception from `execute_live`. It does not pass a thinking level. It does not grant `bash` or `rg`. It does not run `make setup-pi`.

- [ ] **Step 4: Run the provider-free tests**

Run: `uv run python -m unittest -v tests.test_native_application tests.test_native_package_host`

Expected: `OK`.

Run: `uv run python -c "import runpy; runpy.run_path('tools/check_promotion.py', run_name='promotion_path_check')"`

Expected: exit 0.

Do not run `make native-dci-example` in this step.

- [ ] **Step 5: Run the live preset once**

Run: `make native-dci-example`

If stderr is a readiness reason and the exit code is 2, stop. Do not run the command again. Do not run `make setup-pi`. Do not call the model. Record the public reason. Public reasons are `missing DCI_PROVIDER`, `missing DCI_MODEL`, `pi checkout is unavailable`, `node executable is unavailable`, `agent directory is unavailable`, `corpus is unavailable`, and `evidence parent is unavailable`.

If readiness passes, this command is the one authorized model call. Expected stdout is one JSON line with keys `application_id`, `run_id`, and `status`. `application_id` is `native.dci-research`. `run_id` starts with `native-dci-`. Status `completed` exits 0. Status `failed` exits 1 and stderr is `native-dci-example: run failed`. Do not print the model answer or the provider payload in the terminal summary. Evidence stays under `outputs/native-dci-example`, which is gitignored.

- [ ] **Step 6: Record the result and commit**

In `docs/status/INDEX.md`, keep both links in the current milestone bullet for this spec and this plan. Replace the sentence `Implementation has not started.`

If Step 5 exited 2, the replacement sentence is:

`Implementation is in. The live preset stopped at readiness and did not call the model. The public reason is in the journal.`

Append this journal line under `## 2026-10-21`, using the current hour and minute and the stderr reason:

```markdown
- HH:MM Native application entry is in. The live preset exited 2. Reason: <stderr reason>. The model was not called.
```

If Step 5 exited 0 or 1, the replacement sentence is:

`Implementation is in. The live preset ran once. The exit code and status are in the journal.`

Append:

```markdown
- HH:MM Native application entry is in. The live preset ran once. Exit <code>. Status <completed or failed>.
```

Do not write the model answer, a credential, or the environment into the journal.

```bash
git add examples/applications/native_dci.py examples/native_dci_example.sh Makefile \
  tests/test_native_application.py docs/status/INDEX.md docs/status/JOURNAL.md
git commit -m "feat: add the native dci live preset"
```

Do not commit `outputs/`. Do not push.

---

## Out of scope

- A second Pi runner or a change to `PiChildProcess`.
- A change to `prepare_prime_application`.
- A Native CLI, provider scan, or `asterion.application_index` row.
- A separate entry, runner, or example script per package.
- A live run of `native.controlled-code` or `native.packages`.
- Repair of `examples/asterion_dci_basic_example.sh`, `make dci-preflight`, or `asterion-dci run`.
- Changes to the `native.packages` assembly, P7, or the six `prime-*-native` citation packages.
- A benchmark, an official card, a Judge, or an L9 rerun.
- A new `DECISIONS.md` record.
