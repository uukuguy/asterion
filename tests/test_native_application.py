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
        self.assertIn('--with "python-dotenv>=1.0.0"', shell)
        self.assertIn("\nnative-dci-example:\n", makefile)
        self.assertIn(
            '$(UV_BIN) run --with "python-dotenv>=1.0.0" python examples/applications/native_dci.py --live',
            makefile,
        )
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
        self.assertEqual(
            __import__("json").loads(options["command"]),
            [config.node, config.cli, "--mode", "rpc"],
        )
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


if __name__ == "__main__":
    unittest.main()
