"""Focused public SDK contracts used by the extension reference."""

from __future__ import annotations

import ast
import configparser
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from asterion.application_sdk import (
    APPLICATION_PROVIDER_PROTOCOL,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)
from asterion.runtime.protocol import ProtocolError


class TestPublicApplicationSdk(unittest.TestCase):
    def test_exports_the_closed_public_surface(self) -> None:
        import asterion.application_sdk as sdk

        self.assertEqual(
            sdk.__all__,
            (
                "APPLICATION_PROVIDER_PROTOCOL",
                "InstalledApplication",
                "InstalledApplicationProvider",
                "CapabilityPackageRef",
                "RuntimeFactoryBinding",
                "RuntimeFactoryContext",
                "AgentRuntimeClient",
                "CancellationSignal",
                "RunEvent",
                "RunRequest",
                "RuntimeManifest",
                "parse_event_stream",
                "RuntimeFactoryError",
            ),
        )
        self.assertEqual(APPLICATION_PROVIDER_PROTOCOL, "asterion.application-provider/v1")

    def test_runtime_manifest_snapshots_and_validates_constructor_values(self) -> None:
        capabilities = ["acme.research"]
        manifest = RuntimeManifest("acme.inline", capabilities)  # type: ignore[arg-type]
        capabilities.append("poison.policy")

        self.assertEqual(manifest.capabilities, ("acme.research",))
        self.assertEqual(manifest.to_mapping(), {
            "protocol": "asterion.agent-runtime/v1",
            "runtime_id": "acme.inline",
            "capabilities": ["acme.research"],
        })
        with self.assertRaises(ProtocolError):
            RuntimeManifest("bad runtime", ())

    def test_runtime_manifest_rejects_string_and_hostile_capabilities(self) -> None:
        for capabilities in ("research.local", b"research.local", _HostileIterator()):
            with self.subTest(capabilities=type(capabilities).__name__):
                with self.assertRaisesRegex(
                    ProtocolError, "^runtime manifest capabilities are invalid$"
                ):
                    RuntimeManifest("acme.inline", capabilities)  # type: ignore[arg-type]

    def test_run_request_snapshots_and_validates_constructor_values(self) -> None:
        requested = ["research.local"]
        request = RunRequest("acme-run", "input", requested)  # type: ignore[arg-type]
        requested.append("poison.policy")

        self.assertEqual(request.requested_capabilities, ("research.local",))
        self.assertEqual(request.to_mapping()["requested_capabilities"], ["research.local"])
        with self.assertRaises(ProtocolError):
            RunRequest("", "input")

    def test_run_request_rejects_string_and_hostile_capabilities(self) -> None:
        for capabilities in ("research.local", b"research.local", _HostileIterator()):
            with self.subTest(capabilities=type(capabilities).__name__):
                with self.assertRaisesRegex(
                    ProtocolError, "^requested capabilities are invalid$"
                ):
                    RunRequest("acme-run", "input", capabilities)  # type: ignore[arg-type]

    def test_run_event_deep_freezes_payload_and_returns_fresh_json_mapping(self) -> None:
        payload = {
            "call_id": "acme-call",
            "name": "acme.research",
            "arguments": {"items": ["one"]},
        }
        event = RunEvent("acme-run", 1, "tool.call", payload)
        payload["arguments"]["items"].append("two")  # type: ignore[index]

        self.assertEqual(event.payload["arguments"], {"items": ["one"]})
        with self.assertRaises((AttributeError, TypeError)):
            event.payload["arguments"] = {}  # type: ignore[index]
        with self.assertRaises((AttributeError, TypeError)):
            event.payload["arguments"]["items"].append("two")  # type: ignore[index]

        first = event.to_mapping()
        first["payload"]["arguments"]["items"].append("two")  # type: ignore[index]
        self.assertEqual(
            event.to_mapping()["payload"]["arguments"], {"items": ["one"]}
        )

    def test_run_event_from_mapping_validates_and_snapshots_nested_payload(self) -> None:
        source = {
            "protocol": "asterion.agent-runtime/v1",
            "run_id": "acme-run",
            "sequence": 1,
            "type": "run.started",
            "payload": {"capabilities": ["research.local"]},
        }
        event = RunEvent.from_mapping(source)
        source["payload"]["capabilities"].append("poison.policy")  # type: ignore[index]

        self.assertEqual(event.payload, {"capabilities": ["research.local"]})
        with self.assertRaises(ProtocolError):
            RunEvent.from_mapping({**source, "sequence": 0})


class TestInstalledPublicExtension(unittest.TestCase):
    def test_reference_wheel_runs_outside_the_repository(self) -> None:
        root = Path(__file__).resolve().parents[1]
        fixture = root / "tests/fixtures/extensions/distribution"
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            dist = work / "dist"
            extension_dist = work / "extension-dist"
            venv = work / "venv"
            outside = work / "outside"
            outside.mkdir()
            _run(("uv", "build", str(root), "--wheel", "--out-dir", str(dist)))
            _run(("uv", "build", str(fixture), "--wheel", "--out-dir", str(extension_dist)))
            _run(("uv", "venv", str(venv)))
            core_wheel = next(dist.glob("asterion-*.whl"))
            extension_wheel = next(extension_dist.glob("asterion_acme_sample_extension-*.whl"))
            _run(
                (
                    "uv", "pip", "install", "--python", str(venv / "bin/python"),
                    "--no-deps", str(core_wheel), str(extension_wheel),
                )
            )
            _assert_extension_metadata(extension_wheel)
            command = str(venv / "bin/asterion")
            environment = _extension_environment()
            listing = _run(
                (command, "list"),
                cwd=outside,
                env={**environment, "ASTERION_TEST_FORBID_APPLICATION_IMPORT": "1"},
            )
            self.assertIn('"provider_id": "acme-sample"', listing.stdout)
            self.assertNotIn("acme poison provider imported", listing.stderr)
            selected = _run(
                (command, "list", "--provider", "acme-sample"),
                cwd=outside,
                env={**environment, "ASTERION_TEST_FORBID_CAPABILITY_IMPORT": "1"},
            )
            self.assertEqual(json.loads(selected.stdout)["provider_id"], "acme-sample")
            ownership = _run(
                (
                    str(venv / "bin/python"), "-c",
                    "from importlib import metadata; from pathlib import Path; "
                    "from asterion.applications.discovery import load_application_provider; "
                    "p=load_application_provider('acme-sample'); a=p.applications[0]; "
                    "d=metadata.distribution('asterion-acme-sample-extension'); "
                    "expected=Path(str(d.locate_file('asterion_applications/acme.sample/1.0.0'))).resolve(); "
                    "print(p.resource_root == expected and a.assembly_paths == (expected / 'assembly.json',))",
                ),
                cwd=outside,
                env=environment,
            )
            self.assertEqual(ownership.stdout, "True\n")
            index = _run(
                (
                    str(venv / "bin/python"), "-c",
                    "from asterion.applications.discovery import select_application_provider_id; "
                    "print(select_application_provider_id('acme.research-application@1.0.0'))",
                ),
                cwd=outside,
                env=environment,
            )
            self.assertEqual(index.stdout.strip(), "acme-sample")
            result = _run(
                (
                    command, "run", "--provider", "acme-sample",
                    "--application", "acme.research-application@1.0.0",
                    "--runtime", "acme.inline", "--run-id", "acme-reference-run",
                    "--input", "private-input-sentinel",
                ),
                cwd=outside,
                env=environment,
            )
            self.assertNotIn("private-input-sentinel", result.stdout + result.stderr)
            self.assertNotIn("private-environment-sentinel", result.stdout + result.stderr)
            self.assertNotIn("acme poison provider imported", result.stdout + result.stderr)
            self.assertEqual(
                json.loads(result.stdout),
                {
                    "application_id": "acme.research-application",
                    "artifacts": [{
                        "artifact_id": "acme-research-result",
                        "media_type": "application/vnd.acme.research+json",
                        "value": {"status": "completed"},
                    }],
                    "events": [{"payload": {"status": "completed"}, "type": "acme.research.completed"}],
                    "run_id": "acme-reference-run",
                    "runtime_id": "acme.inline",
                },
            )
            poison = subprocess.run(
                (command, "list", "--provider", "acme-poison"),
                cwd=outside,
                env=environment,
                text=True,
                check=False,
                capture_output=True,
            )
            self.assertEqual(poison.returncode, 2)
            self.assertEqual(poison.stdout, "")
            self.assertEqual(poison.stderr, "asterion: command failed\n")
            self.assertNotIn("private-input-sentinel", poison.stdout + poison.stderr)
            self.assertNotIn("private-environment-sentinel", poison.stdout + poison.stderr)
            self.assertNotIn("acme poison provider imported", poison.stdout + poison.stderr)


class _HostileIterator:
    def __iter__(self):
        raise RuntimeError("private hostile iterator")


def _run(
    command: tuple[str, ...], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True, check=True, capture_output=True)


def _assert_extension_metadata(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith("/METADATA"))
        entry_points_name = next(name for name in archive.namelist() if name.endswith("/entry_points.txt"))
        metadata = archive.read(metadata_name).decode()
        entry_points = archive.read(entry_points_name).decode()
    assert "Requires-Dist: asterion<0.2,>=0.1.0" in metadata
    parsed = configparser.ConfigParser()
    parsed.read_string(entry_points)
    assert {
        section: dict(parsed[section]) for section in parsed.sections()
    } == {
        "asterion.application_index": {
            "acme.research-application__1.0.0": "acme_sample_extension.application:create_application_provider",
        },
        "asterion.applications": {
            "acme-poison": "acme_sample_extension.poison:create_poison_application_provider",
            "acme-sample": "acme_sample_extension.application:create_application_provider",
        },
        "asterion.capability_packages": {
            "acme.poison@1.0.0": "acme_sample_extension.poison:create_poison_package",
            "acme.sample@1.0.0": "acme_sample_extension.capability:create_package",
        },
    }
    _assert_wheel_imports_are_public(wheel)


def _assert_wheel_imports_are_public(wheel: Path) -> None:
    allowed = set(sys.stdlib_module_names) | {"__future__", "acme_sample_extension"}
    allowed.update({"asterion.capability_sdk", "asterion.application_sdk"})
    with zipfile.ZipFile(wheel) as archive:
        sources = {
            name: archive.read(name).decode()
            for name in archive.namelist()
            if name.endswith(".py")
        }
    for name, source in sources.items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.level:
                continue
            module = node.module if isinstance(node, ast.ImportFrom) else None
            names = (module,) if module else tuple(alias.name for alias in getattr(node, "names", ()))
            for imported in names:
                assert imported is not None
                root = imported.split(".", 1)[0]
                assert imported in allowed or root in allowed, (name, imported)


def _extension_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PRIVATE_ENV_SENTINEL"] = "private-environment-sentinel"
    return environment
