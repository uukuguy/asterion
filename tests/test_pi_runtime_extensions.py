from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.runtime.defaults import PI_CAPABILITIES, default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runtime.host import RunRequest
from asterion.runtimes.pi_extensions import PiExtensionBinding


class PiExtensionBindingTests(unittest.TestCase):
    def test_extension_binding_is_exact_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            extension = Path(temp_dir, "extension.mjs")
            extension.write_text("export {};\n", encoding="utf-8")
            binding = PiExtensionBinding(
                extension_id="prime.ipython",
                path=extension.resolve(),
                capabilities=("prime.tool.ipython",),
                inherited_fds=(7,),
                environment={"ASTERION_PRIME_IPYTHON_FD": "7"},
            )

        self.assertEqual(binding.capabilities, ("prime.tool.ipython",))
        self.assertEqual(
            binding.command_args(), ("--extension", str(extension.resolve()))
        )
        self.assertNotIn("ASTERION_PRIME_IPYTHON_FD", repr(binding))
        self.assertNotIn("7", repr(binding.environment))
        with self.assertRaises(TypeError):
            binding.environment["SECRET"] = "sentinel"  # type: ignore[index]

    def test_extension_binding_snapshots_its_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            extension = Path(temp_dir, "extension.mjs")
            extension.write_text("export {};\n", encoding="utf-8")
            environment = {"ASTERION_PRIME_IPYTHON_FD": "7"}
            binding = PiExtensionBinding(
                extension_id="prime.ipython",
                path=extension.resolve(),
                capabilities=("prime.tool.ipython",),
                inherited_fds=(7,),
                environment=environment,
            )
            environment["ASTERION_PRIME_IPYTHON_FD"] = "SECRET-replaced"

        self.assertEqual(binding.environment["ASTERION_PRIME_IPYTHON_FD"], "7")
        self.assertNotIn("SECRET", repr(binding))

    def test_extension_binding_rejects_inexact_identity_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            extension = root / "extension.mjs"
            extension.write_text("export {};\n", encoding="utf-8")
            symlink = root / "extension-link.mjs"
            symlink.symlink_to(extension)
            cases = (
                {"extension_id": "Prime.IPython"},
                {"extension_id": "prime..ipython"},
                {"path": Path("extension.mjs")},
                {"path": symlink},
                {"path": root / "missing.mjs"},
                {"path": root},
            )
            for override in cases:
                with self.subTest(override=override), self.assertRaises(ValueError):
                    PiExtensionBinding(
                        extension_id=override.get("extension_id", "prime.ipython"),
                        path=override.get("path", extension),
                        capabilities=("prime.tool.ipython",),
                        inherited_fds=(7,),
                        environment={"ASTERION_PRIME_IPYTHON_FD": "7"},
                    )

    def test_extension_binding_rejects_inexact_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            extension = Path(temp_dir, "extension.mjs")
            extension.write_text("export {};\n", encoding="utf-8")
            cases: tuple[object, ...] = (
                (),
                ("prime.tool.ipython", "alpha.tool"),
                ("prime.tool.ipython", "prime.tool.ipython"),
                ("Prime.tool.ipython",),
                ["prime.tool.ipython"],
            )
            for capabilities in cases:
                with (
                    self.subTest(capabilities=capabilities),
                    self.assertRaises(ValueError),
                ):
                    PiExtensionBinding(
                        extension_id="prime.ipython",
                        path=extension.resolve(),
                        capabilities=capabilities,  # type: ignore[arg-type]
                        inherited_fds=(7,),
                        environment={"ASTERION_PRIME_IPYTHON_FD": "7"},
                    )

    def test_extension_binding_rejects_bad_file_descriptors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            extension = Path(temp_dir, "extension.mjs")
            extension.write_text("export {};\n", encoding="utf-8")
            cases: tuple[object, ...] = (
                (2,),
                (-1,),
                (8, 7),
                (7, 7),
                (True,),
                [7],
            )
            for inherited_fds in cases:
                with (
                    self.subTest(inherited_fds=inherited_fds),
                    self.assertRaises(ValueError),
                ):
                    PiExtensionBinding(
                        extension_id="prime.ipython",
                        path=extension.resolve(),
                        capabilities=("prime.tool.ipython",),
                        inherited_fds=inherited_fds,  # type: ignore[arg-type]
                        environment={"ASTERION_PRIME_IPYTHON_FD": "7"},
                    )

    def test_extension_binding_rejects_undeclared_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            extension = Path(temp_dir, "extension.mjs")
            extension.write_text("export {};\n", encoding="utf-8")
            cases: tuple[object, ...] = (
                {"UNDECLARED": "7"},
                {"ASTERION_PRIME_IPYTHON_FD": 7},
                [("ASTERION_PRIME_IPYTHON_FD", "7")],
            )
            for environment in cases:
                with (
                    self.subTest(environment=environment),
                    self.assertRaises(ValueError),
                ):
                    PiExtensionBinding(
                        extension_id="prime.ipython",
                        path=extension.resolve(),
                        capabilities=("prime.tool.ipython",),
                        inherited_fds=(7,),
                        environment=environment,  # type: ignore[arg-type]
                    )


class PiExtensionFactoryTests(unittest.TestCase):
    def test_factory_resolves_one_exact_extension_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            extension = self._extension(root)
            with tempfile.TemporaryFile() as inherited:
                descriptor = inherited.fileno()
                binding = self._binding(extension, descriptor)
                runtime = (
                    default_runtime_factory_registry()
                    .select("pi.reference")
                    .factory(
                        self._context(
                            root,
                            host_services={"prime.ipython": binding},
                            extension_host_capability="prime.ipython",
                        )
                    )
                )

        self.assertEqual(runtime._command[-2:], ("--extension", str(extension)))
        self.assertEqual(
            runtime.manifest.capabilities,
            (*PI_CAPABILITIES, "prime.tool.ipython"),
        )
        self.assertEqual(runtime._inherited_fds, (descriptor,))
        self.assertEqual(
            runtime._env,
            {
                "BASE_RUNTIME_VALUE": "base",
                "ASTERION_PRIME_IPYTHON_FD": str(descriptor),
            },
        )

    def test_factory_rejects_missing_multiple_or_mismatched_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            first = self._binding(self._extension(root, "first.mjs"))
            second = PiExtensionBinding(
                extension_id="other.extension",
                path=self._extension(root, "second.mjs"),
                capabilities=("other.tool",),
                inherited_fds=(),
                environment={},
            )
            overlapping = PiExtensionBinding(
                extension_id="prime.ipython",
                path=self._extension(root, "overlap.mjs"),
                capabilities=("filesystem.read",),
                inherited_fds=(),
                environment={},
            )
            cases = (
                ({}, "prime.ipython"),
                ({"prime.ipython": object()}, "prime.ipython"),
                ({"wrong.identity": first}, "wrong.identity"),
                ({"prime.ipython": first, "other.extension": second}, "prime.ipython"),
                ({"prime.ipython": overlapping}, "prime.ipython"),
            )
            factory = default_runtime_factory_registry().select("pi.reference").factory
            for services, selected in cases:
                with (
                    self.subTest(services=tuple(services)),
                    patch("asterion.runtime.defaults.PiRuntimeClient") as client,
                    self.assertRaises(RuntimeFactoryError),
                ):
                    factory(
                        self._context(
                            root,
                            host_services=services,
                            extension_host_capability=selected,
                        )
                    )
                client.assert_not_called()

    def test_factory_rejects_extension_environment_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            binding = self._binding(self._extension(root))
            with (
                patch("asterion.runtime.defaults.PiRuntimeClient") as client,
                self.assertRaises(RuntimeFactoryError),
            ):
                default_runtime_factory_registry().select("pi.reference").factory(
                    self._context(
                        root,
                        host_services={"prime.ipython": binding},
                        environment=json.dumps(
                            {"ASTERION_PRIME_IPYTHON_FD": "SECRET-override"},
                            separators=(",", ":"),
                        ),
                        extension_host_capability="prime.ipython",
                    )
                )
            client.assert_not_called()

    def test_factory_preflight_rejects_a_closed_inherited_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            read_fd, write_fd = os.pipe()
            binding = self._binding(self._extension(root), read_fd)
            os.close(read_fd)
            try:
                with (
                    patch("asterion.runtime.defaults.PiRuntimeClient") as client,
                    self.assertRaises(RuntimeFactoryError),
                ):
                    default_runtime_factory_registry().select(
                        "pi.reference"
                    ).factory(
                        self._context(
                            root,
                            host_services={"prime.ipython": binding},
                            extension_host_capability="prime.ipython",
                        )
                    )
                client.assert_not_called()
            finally:
                os.close(write_fd)

    def test_factory_without_extension_preserves_reference_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            unselected = self._binding(self._extension(root))
            runtime = (
                default_runtime_factory_registry()
                .select("pi.reference")
                .factory(
                    self._context(
                        root,
                        host_services={"prime.ipython": unselected},
                    )
                )
            )

        self.assertEqual(runtime.manifest.capabilities, PI_CAPABILITIES)
        self.assertNotIn("--extension", runtime._command)
        self.assertEqual(runtime._inherited_fds, ())
        self.assertEqual(runtime._env, {"BASE_RUNTIME_VALUE": "base"})

    @staticmethod
    def _extension(root: Path, name: str = "extension.mjs") -> Path:
        extension = root / name
        extension.write_text("export {};\n", encoding="utf-8")
        return extension

    @staticmethod
    def _binding(extension: Path, descriptor: int = 7) -> PiExtensionBinding:
        return PiExtensionBinding(
            extension_id="prime.ipython",
            path=extension,
            capabilities=("prime.tool.ipython",),
            inherited_fds=(descriptor,),
            environment={"ASTERION_PRIME_IPYTHON_FD": str(descriptor)},
        )

    @staticmethod
    def _context(
        root: Path,
        *,
        host_services: dict[str, object] | None = None,
        **overrides: str,
    ) -> RuntimeFactoryContext:
        cwd = root / "cwd"
        cwd.mkdir(exist_ok=True)
        options = {
            "command": json.dumps(
                [str(Path(sys.executable).resolve()), "-u", "-c", "pass"],
                separators=(",", ":"),
            ),
            "cwd": str(cwd),
            "environment": '{"BASE_RUNTIME_VALUE":"base"}',
            "evidence_root": str(root / "evidence"),
            "max_turns": "4",
            "tools": "read,grep",
            **overrides,
        }
        return RuntimeFactoryContext(
            provider_id="provider",
            application_id="application",
            application_version="1.0.0",
            runtime_id="pi.reference",
            assembly_path=root / "assembly.json",
            options=options,
            host_services={} if host_services is None else host_services,
        )


class PiExtensionProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_passes_only_bound_environment_and_descriptors(self) -> None:
        script = r'''
import json, os, sys
request = json.loads(sys.stdin.readline())
fd = int(os.environ["ASTERION_PRIME_IPYTHON_FD"])
os.fstat(fd)
assert os.environ["ASTERION_PRIME_IPYTHON_TOKEN"] == "SECRET-extension-value"
assert sys.argv[-2:] == ["--extension", os.environ["EXPECTED_EXTENSION"]]
assert "SECRET_UNDECLARED" not in os.environ
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
print(json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "safe"}}), flush=True)
print(json.dumps({"type": "message_end", "message": {"role": "assistant", "stopReason": "stop", "usage": {"input": 1, "output": 1}}}), flush=True)
print(json.dumps({"type": "agent_end"}), flush=True)
'''
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            extension = PiExtensionFactoryTests._extension(root)
            read_fd, write_fd = os.pipe()
            try:
                binding = PiExtensionBinding(
                    extension_id="prime.ipython",
                    path=extension,
                    capabilities=("prime.tool.ipython",),
                    inherited_fds=(read_fd,),
                    environment={
                        "ASTERION_PRIME_IPYTHON_FD": str(read_fd),
                        "ASTERION_PRIME_IPYTHON_TOKEN": "SECRET-extension-value",
                    },
                )
                context = PiExtensionFactoryTests._context(
                    root,
                    host_services={"prime.ipython": binding},
                    command=json.dumps(
                        [str(Path(sys.executable).resolve()), "-u", "-c", script],
                        separators=(",", ":"),
                    ),
                    environment=json.dumps(
                        {"EXPECTED_EXTENSION": str(extension)},
                        separators=(",", ":"),
                    ),
                    extension_host_capability="prime.ipython",
                )
                runtime = (
                    default_runtime_factory_registry()
                    .select("pi.reference")
                    .factory(context)
                )
                with patch.dict(os.environ, {"SECRET_UNDECLARED": "sentinel"}):
                    events = [
                        event
                        async for event in runtime.run(
                            RunRequest(
                                run_id="extension-run",
                                input_text="test",
                                requested_capabilities=("prime.tool.ipython",),
                            )
                        )
                    ]
            finally:
                os.close(read_fd)
                os.close(write_fd)

        rendered = repr([event.to_mapping() for event in events])
        self.assertNotIn("SECRET", rendered)
        self.assertNotIn(str(extension), rendered)
        self.assertNotIn("ASTERION_PRIME_IPYTHON", rendered)
        self.assertEqual(events[-1].type, "run.completed")


if __name__ == "__main__":
    unittest.main()
