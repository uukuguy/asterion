from __future__ import annotations

import os
import json
import ast
import configparser
import shutil
import subprocess
import tempfile
import unittest
import zipfile
import sys
from pathlib import Path

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    ApplicationProviderError,
    InstalledApplication,
    InstalledApplicationProvider,
    resolve_installed_provider,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import CapabilityImplementationBinding
from asterion.capability_packages.model import (
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
    bind_prepared_package_authority,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.runtime.factory import RuntimeFactoryBinding, RuntimeFactoryRegistry


_FIXTURES = Path(__file__).parent / "fixtures/extensions"
_ACME_PAYLOAD = _FIXTURES / "distribution/payload"
_CONTOSO_PAYLOAD = _FIXTURES / "contoso_audit_distribution/payload"
_CONTOSO_ASSEMBLY = _FIXTURES / "contoso_audit_distribution/application/assembly.json"


class _CounterImplementation:
    def __init__(self) -> None:
        self.executions = 0

    async def execute(self, invocation: object) -> object:
        del invocation
        self.executions += 1
        raise AssertionError("implementation execution is outside composition")


class CrossPackageExtensionTests(unittest.TestCase):
    def test_rejects_authoritative_packages_with_swapped_bindings(self) -> None:
        acme_payload = open_portable_payload(_ACME_PAYLOAD)
        contoso_payload = open_portable_payload(_CONTOSO_PAYLOAD)
        acme_implementation = _CounterImplementation()
        contoso_implementation = _CounterImplementation()
        acme = _authoritative_snapshot(
            acme_payload,
            catalog_root=_ACME_PAYLOAD / "capabilities",
            implementation=CapabilityImplementationBinding(
                CapabilityRef("contoso.audit-record", "1.0.0"), acme_implementation
            ),
        )
        contoso = _authoritative_snapshot(
            contoso_payload,
            catalog_root=_CONTOSO_PAYLOAD / "capabilities",
            implementation=CapabilityImplementationBinding(
                CapabilityRef("acme.research", "1.0.0"), contoso_implementation
            ),
        )
        calls = 0

        def factory(context: object) -> object:
            nonlocal calls
            del context
            calls += 1
            raise AssertionError

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ApplicationProviderError):
                resolve_installed_provider(
                    _contoso_provider(Path(directory)),
                    runtime_factories=RuntimeFactoryRegistry(
                        (RuntimeFactoryBinding("contoso.inline", (), factory),)
                    ),
                    installed_packages=(acme, contoso),
                )
        self.assertEqual(
            (calls, acme_implementation.executions, contoso_implementation.executions),
            (0, 0, 0),
        )

    def test_rejects_authoritative_contoso_snapshot_that_claims_acme_resources(
        self,
    ) -> None:
        acme_payload = open_portable_payload(_ACME_PAYLOAD)
        contoso_payload = open_portable_payload(_CONTOSO_PAYLOAD)
        acme_implementation = _CounterImplementation()
        contoso_implementation = _CounterImplementation()
        acme = _authoritative_snapshot(
            acme_payload,
            catalog_root=_ACME_PAYLOAD / "capabilities",
            implementation=CapabilityImplementationBinding(
                CapabilityRef("acme.research", "1.0.0"), acme_implementation
            ),
        )
        hostile_contoso = _authoritative_snapshot(
            contoso_payload,
            catalog_root=_ACME_PAYLOAD / "capabilities",
            implementation=CapabilityImplementationBinding(
                CapabilityRef("acme.research", "1.0.0"), contoso_implementation
            ),
        )
        runtime_calls = 0

        def factory(context: object) -> object:
            nonlocal runtime_calls
            del context
            runtime_calls += 1
            raise AssertionError(
                "runtime factory is outside package authority validation"
            )

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ApplicationProviderError):
                resolve_installed_provider(
                    _contoso_provider(Path(directory)),
                    runtime_factories=RuntimeFactoryRegistry(
                        (RuntimeFactoryBinding("contoso.inline", (), factory),)
                    ),
                    installed_packages=(acme, hostile_contoso),
                )

        self.assertEqual(runtime_calls, 0)
        self.assertEqual(acme_implementation.executions, 0)
        self.assertEqual(contoso_implementation.executions, 0)

    def test_rejects_raw_contoso_snapshot_in_multi_package_application(self) -> None:
        acme_payload = open_portable_payload(_ACME_PAYLOAD)
        contoso_payload = open_portable_payload(_CONTOSO_PAYLOAD)
        acme_implementation = _CounterImplementation()
        contoso_implementation = _CounterImplementation()
        acme = _authoritative_snapshot(
            acme_payload,
            catalog_root=_ACME_PAYLOAD / "capabilities",
            implementation=CapabilityImplementationBinding(
                CapabilityRef("acme.research", "1.0.0"), acme_implementation
            ),
        )
        raw_contoso = _raw_snapshot(
            contoso_payload,
            catalog_root=_CONTOSO_PAYLOAD / "capabilities",
            implementation=CapabilityImplementationBinding(
                CapabilityRef("contoso.audit-record", "1.0.0"), contoso_implementation
            ),
        )
        runtime_calls = 0

        def factory(context: object) -> object:
            nonlocal runtime_calls
            del context
            runtime_calls += 1
            raise AssertionError(
                "runtime factory is outside package authority validation"
            )

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ApplicationProviderError):
                resolve_installed_provider(
                    _contoso_provider(Path(directory)),
                    runtime_factories=RuntimeFactoryRegistry(
                        (RuntimeFactoryBinding("contoso.inline", (), factory),)
                    ),
                    installed_packages=(acme, raw_contoso),
                )

        self.assertEqual(runtime_calls, 0)
        self.assertEqual(acme_implementation.executions, 0)
        self.assertEqual(contoso_implementation.executions, 0)

    def test_installed_wheels_compose_independent_of_install_order(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            core = _build(root, work / "core")
            acme = _build(
                root / "tests/fixtures/extensions/distribution", work / "acme"
            )
            contoso = _build(
                root / "tests/fixtures/extensions/contoso_audit_distribution",
                work / "contoso",
            )
            _assert_wheel_boundary(
                acme,
                "acme_sample_extension",
                {"asterion<0.2,>=0.1.0"},
                {
                    "asterion.application_index": {
                        "acme.research-application__1.0.0": "acme_sample_extension.application:create_application_provider"
                    },
                    "asterion.applications": {
                        "acme-sample": "acme_sample_extension.application:create_application_provider",
                        "acme-poison": "acme_sample_extension.poison:create_poison_application_provider",
                    },
                    "asterion.capability_packages": {
                        "acme.sample@1.0.0": "acme_sample_extension.capability:create_package",
                        "acme.poison@1.0.0": "acme_sample_extension.poison:create_poison_package",
                    },
                },
            )
            _assert_wheel_boundary(
                contoso,
                "contoso_audit_extension",
                {"asterion<0.2,>=0.1.0", "asterion-acme-sample-extension==1.0.0"},
                {
                    "asterion.application_index": {
                        "contoso.audited-research__1.0.0": "contoso_audit_extension.application:create_application_provider"
                    },
                    "asterion.applications": {
                        "contoso-audit": "contoso_audit_extension.application:create_application_provider"
                    },
                    "asterion.capability_packages": {
                        "contoso.audit@1.0.0": "contoso_audit_extension.capability:create_package"
                    },
                },
            )
            first = _run_order(work / "first", core, acme, contoso, (acme, contoso))
            second = _run_order(work / "second", core, acme, contoso, (contoso, acme))
            self.assertEqual(first, second)
            payload = json.loads(first)
            self.assertEqual(
                payload,
                {
                    "application_id": "contoso.audited-research",
                    "run_id": "cross-run",
                    "runtime_id": "contoso.inline",
                    "events": [
                        {
                            "type": "acme.research.completed",
                            "payload": {"status": "completed"},
                        },
                        {
                            "type": "contoso.audit.completed",
                            "payload": {"status": "completed"},
                        },
                    ],
                    "artifacts": [
                        {
                            "artifact_id": "acme-research-result",
                            "media_type": "application/vnd.acme.research+json",
                            "value": {"status": "completed"},
                        },
                        {
                            "artifact_id": "contoso-audit-result",
                            "media_type": "application/vnd.contoso.audit+json",
                            "value": {"status": "completed"},
                        },
                    ],
                },
            )
            self.assertNotIn(b"secret", first)
            self.assertNotIn(b"private-environment-sentinel", first)
            self.assertNotIn(b"poison", first)
            self.assertNotIn(str(work).encode(), first)
            missing = _run_missing(work / "missing", core, contoso)
            self.assertEqual(missing.returncode, 2)
            self.assertEqual(missing.stdout, "")
            self.assertEqual(missing.stderr, "asterion: command failed\n")
            self.assertNotIn("secret", missing.stdout + missing.stderr)
            self.assertNotIn(
                "private-environment-sentinel", missing.stdout + missing.stderr
            )
            self.assertNotIn("poison", missing.stdout + missing.stderr)
            self.assertNotIn(str(work), missing.stdout + missing.stderr)


def _authoritative_snapshot(
    payload: PortableCapabilityPayload,
    *,
    catalog_root: Path,
    implementation: CapabilityImplementationBinding,
) -> InstalledCapabilityPackage:
    return bind_prepared_package_authority(
        _raw_snapshot(
            payload,
            catalog_root=catalog_root,
            implementation=implementation,
        ),
        payload,
    )


def _raw_snapshot(
    payload: PortableCapabilityPayload,
    *,
    catalog_root: Path,
    implementation: CapabilityImplementationBinding,
) -> InstalledCapabilityPackage:
    return InstalledCapabilityPackage(
        package_ref=payload.manifest.package_ref,
        payload_sha256=payload.payload_sha256,
        source_id=f"{payload.manifest.package_ref.package_id}.fixture",
        source_kind="local-directory",
        catalog_roots=(catalog_root,),
        benchmark_suite_paths=(),
        implementations=(implementation,),
        benchmark_bindings=(),
    )


def _contoso_provider(root: Path) -> InstalledApplicationProvider:
    assembly = root / "assembly.json"
    shutil.copy2(_CONTOSO_ASSEMBLY, assembly)
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="contoso-audit",
        resource_root=root,
        applications=(
            InstalledApplication(
                application_id="contoso.audited-research",
                version="1.0.0",
                assembly_paths=(assembly,),
                capability_packages=(
                    CapabilityPackageRef("acme.sample", "1.0.0"),
                    CapabilityPackageRef("contoso.audit", "1.0.0"),
                ),
                runtime_ids=("contoso.inline",),
            ),
        ),
    )


def _build(source: Path, output: Path) -> Path:
    subprocess.run(
        ("uv", "build", str(source), "--wheel", "--out-dir", str(output)),
        check=True,
        capture_output=True,
    )
    return next(output.glob("*.whl"))


def _assert_wheel_boundary(
    wheel: Path,
    package: str,
    requirements: set[str],
    expected_entries: dict[str, dict[str, str]],
) -> None:
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read(
            next(name for name in archive.namelist() if name.endswith("/METADATA"))
        ).decode()
        entries = archive.read(
            next(
                name
                for name in archive.namelist()
                if name.endswith("/entry_points.txt")
            )
        ).decode()
        sources = {
            name: archive.read(name).decode()
            for name in archive.namelist()
            if name.endswith(".py")
        }
    assert {
        line.removeprefix("Requires-Dist: ")
        for line in metadata.splitlines()
        if line.startswith("Requires-Dist: ")
    } == requirements
    parser = configparser.ConfigParser()
    parser.read_string(entries)
    assert {
        section: dict(parser[section]) for section in parser.sections()
    } == expected_entries
    allowed = set(sys.stdlib_module_names) | {
        "__future__",
        package,
        "asterion.application_sdk",
        "asterion.capability_sdk",
    }
    for name, source in sources.items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.level:
                continue
            module = node.module if isinstance(node, ast.ImportFrom) else None
            for imported in (
                (module,)
                if module
                else tuple(alias.name for alias in getattr(node, "names", ()))
            ):
                assert imported is not None
                assert imported in allowed or imported.split(".", 1)[0] in allowed, (
                    name,
                    imported,
                )


def _run_order(
    root: Path, core: Path, acme: Path, contoso: Path, order: tuple[Path, Path]
) -> bytes:
    subprocess.run(("uv", "venv", str(root / "venv")), check=True, capture_output=True)
    python = root / "venv/bin/python"
    subprocess.run(
        (
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            str(core),
            *(str(item) for item in order),
        ),
        check=True,
        capture_output=True,
    )
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PRIVATE_ENV_SENTINEL"] = "private-environment-sentinel"
    result = subprocess.run(
        (
            str(root / "venv/bin/asterion"),
            "run",
            "--provider",
            "contoso-audit",
            "--application",
            "contoso.audited-research@1.0.0",
            "--runtime",
            "contoso.inline",
            "--run-id",
            "cross-run",
            "--input",
            "secret",
        ),
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    assert result.stderr == b""
    return result.stdout


def _run_missing(
    root: Path, core: Path, contoso: Path
) -> subprocess.CompletedProcess[str]:
    subprocess.run(("uv", "venv", str(root / "venv")), check=True, capture_output=True)
    python = root / "venv/bin/python"
    subprocess.run(
        (
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            str(core),
            str(contoso),
        ),
        check=True,
        capture_output=True,
    )
    counts = root / "counts"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PRIVATE_ENV_SENTINEL"] = "private-environment-sentinel"
    environment["CONTOSO_COUNT_FILE"] = str(counts)
    result = subprocess.run(
        (
            str(root / "venv/bin/asterion"),
            "run",
            "--provider",
            "contoso-audit",
            "--application",
            "contoso.audited-research@1.0.0",
            "--runtime",
            "contoso.inline",
            "--run-id",
            "cross-run",
            "--input",
            "secret",
        ),
        cwd=root,
        env=environment,
        text=True,
        check=False,
        capture_output=True,
    )
    assert not counts.exists()
    return result
