from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class CrossRuntimeExtensionTests(unittest.TestCase):
    def test_installed_extensions_preserve_public_results_and_runtime_boundaries(
        self,
    ) -> None:
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory).resolve()
            core = _build(repository, work / "core")
            acme = _build(
                repository / "tests/fixtures/extensions/distribution", work / "acme"
            )
            contoso = _build(
                repository / "tests/fixtures/extensions/contoso_audit_distribution",
                work / "contoso",
            )
            python = _install(work, core, acme, contoso)
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            environment["PRIVATE_ENV_SENTINEL"] = "private-environment-sentinel"

            acme_result = _run_cli(
                python,
                work,
                environment,
                "acme-sample",
                "acme.research-application@1.0.0",
                "acme.inline",
            )
            contoso_result = _run_cli(
                python,
                work,
                environment,
                "contoso-audit",
                "contoso.research-compat@1.0.0",
                "contoso.inline",
            )
            self.assertEqual(acme_result.stderr, "")
            self.assertEqual(contoso_result.stderr, "")
            acme_payload = json.loads(acme_result.stdout)
            contoso_payload = json.loads(contoso_result.stdout)
            self.assertEqual(
                (
                    acme_payload["application_id"],
                    acme_payload["runtime_id"],
                    acme_payload["run_id"],
                ),
                ("acme.research-application", "acme.inline", "cross-runtime"),
            )
            self.assertEqual(
                (
                    contoso_payload["application_id"],
                    contoso_payload["runtime_id"],
                    contoso_payload["run_id"],
                ),
                ("contoso.research-compat", "contoso.inline", "cross-runtime"),
            )
            self.assertEqual(
                _project_result(acme_payload),
                _project_result(contoso_payload),
            )
            self.assertEqual(
                _project_result(acme_payload),
                {
                    "events": [
                        {
                            "type": "acme.research.completed",
                            "payload": {"status": "completed"},
                        }
                    ],
                    "artifacts": [
                        {
                            "artifact_id": "acme-research-result",
                            "media_type": "application/vnd.acme.research+json",
                            "value": {"status": "completed"},
                        }
                    ],
                },
            )
            combined = (
                acme_result.stdout
                + contoso_result.stdout
                + acme_result.stderr
                + contoso_result.stderr
            )
            for sentinel in (
                "secret",
                "private-environment-sentinel",
                "poison",
                str(work),
            ):
                self.assertNotIn(sentinel, combined)

            probe = work / "probe.py"
            probe.write_text(_PROBE, encoding="utf-8")
            result = subprocess.run(
                (str(python), "-I", str(probe)),
                cwd=work,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"ok": True})
            self.assertEqual(result.stderr, "")


def _build(source: Path, output: Path) -> Path:
    subprocess.run(
        ("uv", "build", str(source), "--wheel", "--out-dir", str(output)),
        check=True,
        capture_output=True,
    )
    return next(output.glob("*.whl"))


def _install(root: Path, *wheels: Path) -> Path:
    venv = root / "venv"
    subprocess.run(("uv", "venv", str(venv)), check=True, capture_output=True)
    python = venv / "bin/python"
    subprocess.run(
        (
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            *(str(wheel) for wheel in wheels),
        ),
        check=True,
        capture_output=True,
    )
    return python


def _run_cli(
    python: Path,
    cwd: Path,
    environment: dict[str, str],
    provider: str,
    application: str,
    runtime: str,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        (
            str(python.parent / "asterion"),
            "run",
            "--provider",
            provider,
            "--application",
            application,
            "--runtime",
            runtime,
            "--run-id",
            "cross-runtime",
            "--input",
            "secret",
        ),
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return result


def _project_result(payload: dict[str, object]) -> dict[str, object]:
    return {"events": payload["events"], "artifacts": payload["artifacts"]}


_PROBE = textwrap.dedent(
    """
    import asyncio
    import json
    from dataclasses import replace

    from asterion.applications.discovery import load_application_provider
    from asterion.applications.provider import resolve_installed_provider
    from asterion.capability_packages import (
        CapabilityPackageRef,
        load_prepared_capability_source,
        prepare_capability_source,
    )
    from asterion.capability_packages.sources.distribution import DistributionCapabilityPackageSource
    from asterion.runner.application import ApplicationRunError
    from asterion.runner.composed import run_composed_application
    from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryRegistry
    from asterion.runtime.host import RunRequest, parse_event_stream

    class Signal:
        def __init__(self, cancelled=False): self.cancelled = cancelled

    class SpyRuntime:
        def __init__(self, runtime): self.runtime, self.manifest, self.calls = runtime, runtime.manifest, 0
        def run(self, request, *, signal=None):
            self.calls += 1
            return self.runtime.run(request, signal=signal)

    class SpyImplementation:
        def __init__(self): self.calls = 0
        async def execute(self, invocation):
            self.calls += 1
            raise AssertionError("implementation invoked")

    def package(ref):
        source = DistributionCapabilityPackageSource()
        prepared = prepare_capability_source(ref, (source,), None)
        return load_prepared_capability_source(prepared)

    def app(provider, application_id):
        return next(value for value in provider.applications if value.application_id == application_id)

    def runtime(provider, application):
        assembly = application.assemblies[0]
        return assembly.runtime_binding.factory(RuntimeFactoryContext(
            provider_id=provider.provider_id, application_id=application.application_id,
            application_version=application.version, runtime_id=assembly.runtime_id,
            assembly_path=assembly.path, options={}, host_services={},
        ))

    async def events(client, signal):
        values = [event.to_mapping() async for event in client.run(RunRequest("runtime-run", "secret"), signal=signal)]
        return [event.to_mapping() for event in parse_event_stream(values)]

    async def after_started(client):
        signal = Signal()
        iterator = client.run(RunRequest("runtime-toggle", "secret"), signal=signal)
        first = await anext(iterator)
        signal.cancelled = True
        values = [first.to_mapping(), *[event.to_mapping() async for event in iterator]]
        return [event.to_mapping() for event in parse_event_stream(values)]

    async def reject(plan, runtime, expected):
        spies = {ref: SpyImplementation() for ref in plan.capability_refs}
        try:
            await run_composed_application(plan, implementations=tuple(spies.items()), runtime=runtime,
                run_id="boundary", input_text="secret", host_services={})
        except ApplicationRunError as error:
            assert str(error) == expected
        else:
            raise AssertionError("boundary accepted")
        assert runtime.calls == 0
        assert all(value.calls == 0 for value in spies.values())

    async def main():
        acme_package = package(CapabilityPackageRef("acme.sample", "1.0.0"))
        contoso_package = package(CapabilityPackageRef("contoso.audit", "1.0.0"))
        registry = RuntimeFactoryRegistry(())
        acme_provider = resolve_installed_provider(load_application_provider("acme-sample"), runtime_factories=registry, installed_packages=(acme_package, contoso_package))
        contoso_provider = resolve_installed_provider(load_application_provider("contoso-audit"), runtime_factories=registry, installed_packages=(acme_package, contoso_package))
        acme_app = app(acme_provider, "acme.research-application")
        contoso_app = app(contoso_provider, "contoso.research-compat")
        acme_runtime, contoso_runtime = runtime(acme_provider, acme_app), runtime(contoso_provider, contoso_app)
        normal = [await events(acme_runtime, Signal()), await events(contoso_runtime, Signal())]
        assert [[(event["sequence"], event["type"]) for event in stream] for stream in normal] == [[(1, "run.started"), (2, "text.delta"), (3, "run.completed")]] * 2
        assert all(stream[0]["payload"] == {"capabilities": []} for stream in normal)
        assert all(stream[1]["payload"]["text"] for stream in normal)
        assert all(stream[2]["payload"] == {"status": "completed"} for stream in normal)
        cancelled = [await events(acme_runtime, Signal(True)), await events(contoso_runtime, Signal(True))]
        toggled = [await after_started(acme_runtime), await after_started(contoso_runtime)]
        def expected(run_id):
            return [{"protocol":"asterion.agent-runtime/v1","run_id":run_id,"sequence":1,"type":"run.started","payload":{"capabilities":[]}}, {"protocol":"asterion.agent-runtime/v1","run_id":run_id,"sequence":2,"type":"run.completed","payload":{"status":"cancelled"}}]
        assert cancelled == [expected("runtime-run"), expected("runtime-run")]
        assert toggled == [expected("runtime-toggle"), expected("runtime-toggle")]
        await reject(replace(acme_app.assemblies[0].plan, host_capabilities=("compat.missing-service",)), SpyRuntime(acme_runtime), "application host service is unavailable")
        await reject(replace(contoso_app.assemblies[0].plan, host_capabilities=("compat.missing-service",)), SpyRuntime(contoso_runtime), "application host service is unavailable")
        await reject(acme_app.assemblies[0].plan, SpyRuntime(contoso_runtime), "application runtime identity does not match")
        await reject(contoso_app.assemblies[0].plan, SpyRuntime(acme_runtime), "application runtime identity does not match")

    asyncio.run(main())
    print(json.dumps({"ok": True}))
    """
)
