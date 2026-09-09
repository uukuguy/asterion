from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.runtime.defaults import PI_CAPABILITIES, default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runtime.host import RunRequest
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.pi_extensions import PiExtensionBinding


NODE_PI_HARNESS = r'''
import { pathToFileURL } from "node:url";
const position = process.argv.lastIndexOf("--extension");
const loader = await import(pathToFileURL(process.argv[position + 1]).href);
const tools = [];
await loader.default({ registerTool: (tool) => tools.push(tool) });
let input = "";
for await (const chunk of process.stdin) { input += chunk; if (input.includes("\n")) break; }
const request = JSON.parse(input.trim());
const answer = tools[0]?.name ?? "missing";
for (const event of [
  {type: "response", id: request.id, success: true},
  {type: "agent_start"},
  {type: "turn_start"},
  {type: "message_update", assistantMessageEvent: {type: "text_delta", delta: answer}},
  {type: "message_end", message: {role: "assistant", stopReason: "stop", usage: {input: 1, output: 1}}},
  {type: "agent_end"},
]) console.log(JSON.stringify(event));
'''


class PiExtensionBindingTests(unittest.TestCase):
    def test_preflight_carries_immutable_canonical_binding_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            first_path = root / "first" / "extension.mjs"
            second_path = root / "second" / "extension.mjs"
            first_path.parent.mkdir()
            second_path.parent.mkdir()
            first_path.write_text("export default function extension() {}\n")
            second_path.write_text("export default function extension() {}\n")
            first = PiExtensionBinding(
                extension_id="prime.ipython",
                path=first_path,
                capabilities=("prime.tool.ipython",),
                inherited_fds=(),
                environment={},
            )
            second = PiExtensionBinding(
                extension_id="prime.ipython",
                path=second_path,
                capabilities=("prime.tool.ipython",),
                inherited_fds=(),
                environment={},
            )
            lease = first.preflight()
            self.addCleanup(lease.close)

            self.assertRegex(first.binding_fingerprint, r"^[0-9a-f]{64}$")
            self.assertEqual(lease.binding_fingerprint, first.binding_fingerprint)
            self.assertNotEqual(first.binding_fingerprint, second.binding_fingerprint)
            with self.assertRaises(AttributeError):
                lease.binding_fingerprint = second.binding_fingerprint  # type: ignore[misc]
            with self.assertRaises(AttributeError):
                lease._binding_fingerprint = second.binding_fingerprint
            with self.assertRaises(AttributeError):
                del lease._initialized
            self.assertEqual(lease.binding_fingerprint, first.binding_fingerprint)

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
        self.assertFalse(hasattr(binding, "command_args"))
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

    def test_extension_binding_rejects_reserved_loader_environment_before_io(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            extension = Path(temp_dir, "extension.mjs").resolve()
            extension.write_text("export default () => {};\n", encoding="utf-8")
            for extension_id in ("pi", "pi.extension"):
                with (
                    self.subTest(extension_id=extension_id),
                    patch("asterion.runtimes.pi_extensions.os.open") as opened,
                    patch("asterion.runtimes.pi_extensions.os.dup") as duplicated,
                    self.assertRaises(ValueError),
                ):
                    PiExtensionBinding(
                        extension_id=extension_id,
                        path=extension,
                        capabilities=(f"{extension_id}.tool",),
                        inherited_fds=(7,),
                        environment={"ASTERION_PI_EXTENSION_SOURCE_FD": "7"},
                    )
                opened.assert_not_called()
                duplicated.assert_not_called()


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

        self.assertEqual(runtime._command[-2], "--extension")
        self.assertEqual(
            Path(runtime._command[-1]).name,
            "asterion_pi_extension_loader.mjs",
        )
        self.assertNotIn(str(extension), runtime._command)
        self.assertEqual(
            runtime.manifest.capabilities,
            (*PI_CAPABILITIES, "prime.tool.ipython"),
        )
        self.assertNotIn(descriptor, runtime._inherited_fds)
        self.assertEqual(len(runtime._inherited_fds), 2)
        self.assertNotEqual(
            runtime._env["ASTERION_PRIME_IPYTHON_FD"], str(descriptor)
        )
        self.assertEqual(runtime._env["BASE_RUNTIME_VALUE"], "base")
        self.assertEqual(
            runtime._env["ASTERION_PI_EXTENSION_SOURCE_NAME"], extension.name
        )
        runtime.close()

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

    def test_factory_rejects_unsupported_extension_source_forms(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            sources = (
                ("extension.ts", "export default () => {};\n"),
                (
                    "relative.mjs",
                    'import value from "./dependency.mjs"; export default () => value;\n',
                ),
                (
                    "bare.mjs",
                    'import value from "package"; export default () => value;\n',
                ),
                (
                    "dynamic.mjs",
                    'export default async () => import("node:fs");\n',
                ),
            )
            factory = default_runtime_factory_registry().select("pi.reference").factory
            for name, source in sources:
                extension = root / name
                extension.write_text(source, encoding="utf-8")
                binding = PiExtensionBinding(
                    extension_id="prime.ipython",
                    path=extension,
                    capabilities=("prime.tool.ipython",),
                    inherited_fds=(),
                    environment={},
                )
                with (
                    self.subTest(name=name),
                    patch("asterion.runtime.defaults.PiRuntimeClient") as client,
                    self.assertRaises(RuntimeFactoryError),
                ):
                    factory(
                        self._context(
                            root,
                            host_services={"prime.ipython": binding},
                            extension_host_capability="prime.ipython",
                        )
                    )
                client.assert_not_called()

    def test_factory_rejects_multiline_and_compact_reexports_before_client(
        self,
    ) -> None:
        def close_lease(**kwargs: object) -> object:
            kwargs["extension_lease"].close()  # type: ignore[union-attr]
            return object()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            sources = (
                'export {\n  value\n} from "./dependency.mjs";\n'
                "export default () => {};\n",
                'export *\nfrom "package";\nexport default () => {};\n',
                'export {value}from "./dependency.mjs";\n'
                "export default () => {};\n",
                'export*from "./dependency.mjs";\nexport default () => {};\n',
            )
            factory = default_runtime_factory_registry().select("pi.reference").factory
            for index, source in enumerate(sources):
                extension = root / f"multiline-{index}.mjs"
                extension.write_text(source, encoding="utf-8")
                binding = PiExtensionBinding(
                    extension_id="prime.ipython",
                    path=extension,
                    capabilities=("prime.tool.ipython",),
                    inherited_fds=(),
                    environment={},
                )
                with (
                    self.subTest(index=index),
                    patch(
                        "asterion.runtime.defaults.PiRuntimeClient",
                        side_effect=close_lease,
                    ) as client,
                    self.assertRaises(RuntimeFactoryError),
                ):
                    factory(
                        self._context(
                            root,
                            host_services={"prime.ipython": binding},
                            extension_host_capability="prime.ipython",
                        )
                    )
                client.assert_not_called()

    def test_factory_rejects_comment_bearing_sources_before_client(self) -> None:
        def close_lease(**kwargs: object) -> object:
            kwargs["extension_lease"].close()  # type: ignore[union-attr]
            return object()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            cases = (
                (
                    "after-export",
                    'export/*gap*/{value}from "./dependency.mjs";\n',
                ),
                (
                    "before-braces",
                    'export /*gap*/ {value}from "./dependency.mjs";\n',
                ),
                (
                    "inside-braces",
                    'export {/*gap*/value}from "./dependency.mjs";\n',
                ),
                (
                    "around-star",
                    'export /*gap*/ * /*gap*/ from "./dependency.mjs";\n',
                ),
                (
                    "around-from",
                    'export {value}/*gap*/from/*gap*/"./dependency.mjs";\n',
                ),
                (
                    "before-specifier",
                    'export {value}from /*gap*/ "package";\n',
                ),
            )
            factory = default_runtime_factory_registry().select("pi.reference").factory
            for label, prefix in cases:
                extension = root / f"comment-{label}.mjs"
                extension.write_text(
                    prefix + "export default () => {};\n", encoding="utf-8"
                )
                binding = PiExtensionBinding(
                    extension_id="prime.ipython",
                    path=extension,
                    capabilities=("prime.tool.ipython",),
                    inherited_fds=(),
                    environment={},
                )
                with (
                    self.subTest(label=label),
                    patch(
                        "asterion.runtimes.pi_extensions.os.dup", wraps=os.dup
                    ) as duplicated,
                    patch(
                        "asterion.runtime.defaults.PiRuntimeClient",
                        side_effect=close_lease,
                    ) as client,
                    self.assertRaises(RuntimeFactoryError),
                ):
                    factory(
                        self._context(
                            root,
                            host_services={"prime.ipython": binding},
                            extension_host_capability="prime.ipython",
                        )
                    )
                client.assert_not_called()
                duplicated.assert_not_called()

    def test_factory_accepts_minimal_self_contained_p7_extension(self) -> None:
        source = '''
export default function registerPrimeIpython(pi) {
  pi.registerTool({
    name: "prime_ipython",
    execute: async () => ({ content: [] }),
  });
}
'''
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            extension = root / "prime-ipython.mjs"
            extension.write_text(source, encoding="utf-8")
            binding = PiExtensionBinding(
                extension_id="prime.ipython",
                path=extension,
                capabilities=("prime.tool.ipython",),
                inherited_fds=(),
                environment={},
            )
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

        self.assertEqual(runtime._env["ASTERION_PI_EXTENSION_SOURCE_NAME"], extension.name)
        self.assertEqual(runtime._command[-2], "--extension")
        runtime.close()

    def test_factory_rejects_every_dependency_syntax_form(self) -> None:
        def close_lease(**kwargs: object) -> object:
            kwargs["extension_lease"].close()  # type: ignore[union-attr]
            return object()

        cases = (
            (
                "namespace-compact",
                'export*as namespace from "./dependency.mjs";\n',
            ),
            (
                "namespace-spaced",
                'export * as namespace from "./dependency.mjs";\n',
            ),
            ("named-compact", 'export{value}from "./dependency.mjs";\n'),
            ("star-compact", 'export*from "./dependency.mjs";\n'),
            (
                "named-multiline",
                'export {\n value\n}\nfrom\n"./dependency.mjs";\n',
            ),
            (
                "namespace-multiline",
                'export\n*\nas\nnamespace\nfrom\n"package";\n',
            ),
            ("node-reexport", 'export {readFileSync} from "node:fs";\n'),
            ("relative-import", 'import value from "./dependency.mjs";\n'),
            ("bare-import", 'import {value} from "package";\n'),
            ("relative-side-effect", 'import "./dependency.mjs";\n'),
            ("bare-side-effect", 'import "package";\n'),
            ("relative-dynamic", 'const value = import("./dependency.mjs");\n'),
            ("node-dynamic", 'const value = import("node:fs");\n'),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            factory = default_runtime_factory_registry().select("pi.reference").factory
            for label, prefix in cases:
                extension = root / f"dependency-{label}.mjs"
                extension.write_text(
                    prefix + "export default () => {};\n", encoding="utf-8"
                )
                binding = PiExtensionBinding(
                    extension_id="prime.ipython",
                    path=extension,
                    capabilities=("prime.tool.ipython",),
                    inherited_fds=(),
                    environment={},
                )
                with (
                    self.subTest(label=label),
                    patch(
                        "asterion.runtimes.pi_extensions.os.dup", wraps=os.dup
                    ) as duplicated,
                    patch(
                        "asterion.runtime.defaults.PiRuntimeClient",
                        side_effect=close_lease,
                    ) as client,
                    self.assertRaises(RuntimeFactoryError),
                ):
                    factory(
                        self._context(
                            root,
                            host_services={"prime.ipython": binding},
                            extension_host_capability="prime.ipython",
                        )
                    )
                client.assert_not_called()
                duplicated.assert_not_called()

    def test_factory_accepts_node_imports_and_harmless_literal_words(self) -> None:
        cases = (
            'import {readFileSync} from "node:fs";\n',
            'import*as fs from "node:fs";\n',
            'import "node:fs";\n',
            'import {\nreadFileSync as read\n}\nfrom\n"node:fs";\n',
            'const phrase = "import value from ./dependency.mjs";\n'
            "const reverse = 'from then import';\n"
            'const template = `export * from "package" and import("package")`;\n'
            'const markers = "https://example.invalid/a/*literal*/";\n',
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            factory = default_runtime_factory_registry().select("pi.reference").factory
            for index, prefix in enumerate(cases):
                extension = root / f"supported-{index}.mjs"
                extension.write_text(
                    prefix + "export default () => {};\n", encoding="utf-8"
                )
                binding = PiExtensionBinding(
                    extension_id="prime.ipython",
                    path=extension,
                    capabilities=("prime.tool.ipython",),
                    inherited_fds=(),
                    environment={},
                )
                with self.subTest(index=index):
                    runtime = factory(
                        self._context(
                            root,
                            host_services={"prime.ipython": binding},
                            extension_host_capability="prime.ipython",
                        )
                    )
                    runtime.close()

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
        extension.write_text("export default () => {};\n", encoding="utf-8")
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
    async def test_replaced_extension_path_executes_pinned_original_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            extension = root / "extension.mjs"
            extension.write_text(
                'export default (pi) => pi.registerTool({name: "original"});\n',
                encoding="utf-8",
            )
            binding = PiExtensionBinding(
                extension_id="prime.ipython",
                path=extension,
                capabilities=("prime.tool.ipython",),
                inherited_fds=(),
                environment={},
            )
            runtime = self._node_runtime(root, binding)
            owned_fds = runtime._inherited_fds
            extension.unlink()
            extension.write_text(
                'export default (pi) => pi.registerTool({name: "replacement"});\n',
                encoding="utf-8",
            )

            events = [
                event
                async for event in runtime.run(
                    RunRequest(
                        run_id="pinned-source",
                        input_text="test",
                        requested_capabilities=("prime.tool.ipython",),
                    )
                )
            ]

        deltas = [event.payload["text"] for event in events if event.type == "text.delta"]
        self.assertEqual(deltas, ["original"])
        for descriptor in owned_fds:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    async def test_reused_host_fd_cannot_substitute_the_pinned_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            extension = root / "extension.mjs"
            extension.write_text(
                'import {readFileSync} from "node:fs"; '
                'export default (pi) => pi.registerTool({name: '
                'readFileSync(Number(process.env.ASTERION_PRIME_IPYTHON_FD), '
                '"utf8").trim()});\n',
                encoding="utf-8",
            )
            original_read, original_write = os.pipe()
            os.write(original_write, b"original-resource")
            os.close(original_write)
            binding = PiExtensionBinding(
                extension_id="prime.ipython",
                path=extension,
                capabilities=("prime.tool.ipython",),
                inherited_fds=(original_read,),
                environment={"ASTERION_PRIME_IPYTHON_FD": str(original_read)},
            )
            runtime = self._node_runtime(root, binding)
            pinned_fd = int(runtime._env["ASTERION_PRIME_IPYTHON_FD"])
            self.assertNotEqual(pinned_fd, original_read)
            os.close(original_read)
            replacement_read, replacement_write = os.pipe()
            if replacement_read != original_read:
                os.dup2(replacement_read, original_read)
                os.close(replacement_read)
            os.write(replacement_write, b"replacement-resource")
            os.close(replacement_write)
            try:
                events = [
                    event
                    async for event in runtime.run(
                        RunRequest(
                            run_id="pinned-resource",
                            input_text="test",
                            requested_capabilities=("prime.tool.ipython",),
                        )
                    )
                ]
            finally:
                os.close(original_read)

        deltas = [event.payload["text"] for event in events if event.type == "text.delta"]
        self.assertEqual(deltas, ["original-resource"])

    async def test_loader_replacement_is_rejected_before_process_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            extension = PiExtensionFactoryTests._extension(root)
            installed_loader = (
                Path(__file__).parents[1]
                / "src/asterion/runtimes/resources/asterion_pi_extension_loader.mjs"
            )
            loader = root / "asterion_pi_extension_loader.mjs"
            shutil.copyfile(installed_loader, loader)
            binding = PiExtensionBinding(
                extension_id="prime.ipython",
                path=extension,
                capabilities=("prime.tool.ipython",),
                inherited_fds=(),
                environment={},
            )
            with patch(
                "asterion.runtime.defaults.pi_extension_loader_path",
                return_value=loader,
            ):
                runtime = self._node_runtime(root, binding)
            loader.unlink()
            loader.write_text("export default () => {};\n", encoding="utf-8")

            with (
                patch(
                    "asterion.runtimes.pi.asyncio.create_subprocess_exec"
                ) as process,
                self.assertRaises(ProtocolError),
            ):
                _ = [
                    event
                    async for event in runtime.run(
                        RunRequest(
                            run_id="replaced-loader",
                            input_text="test",
                            requested_capabilities=("prime.tool.ipython",),
                        )
                    )
                ]
            process.assert_not_called()

    async def test_public_events_redact_adversarial_extension_channels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            extension = PiExtensionFactoryTests._extension(root)
            secret = "SECRET-extension-value"
            private_path = str(extension)
            script = r'''
import json, os, sys
request = json.loads(sys.stdin.readline())
secret = os.environ["ASTERION_PRIME_IPYTHON_TOKEN"]
private_path = PRIVATE_PATH
metadata = "|".join((
    os.environ["ASTERION_PI_EXTENSION_SOURCE_FD"],
    os.environ["ASTERION_PI_EXTENSION_SOURCE_NAME"],
    os.environ["ASTERION_PI_EXTENSION_SOURCE_SHA256"],
))
source_fd = int(os.environ["ASTERION_PI_EXTENSION_SOURCE_FD"])
print(secret + private_path + metadata, file=sys.stderr, flush=True)
events = (
    {"type": "response", "id": request["id"], "success": True},
    {"type": "provider_request_context", "provider": secret, "model": private_path,
     "messages": [{"role": "user", "content": metadata}]},
    {"type": "agent_start"},
    {"type": "turn_start"},
    {"type": "tool_execution_start", "toolCallId": "call-1", "toolName": "grep",
     "args": {secret: private_path, "metadata": metadata, "fd": source_fd}},
    {"type": "tool_execution_end", "toolCallId": "call-1", "isError": False,
     "result": {private_path: secret, "metadata": metadata, "fd": source_fd}},
    {"type": "message_update", "assistantMessageEvent": {
        "type": "text_delta", "delta": "safe:" + secret + private_path + metadata}},
    {"type": "message_end", "message": {"role": "assistant", "stopReason": "stop",
     "usage": {"input": source_fd, "output": 1},
     "content": secret + private_path + metadata}},
    {"type": "agent_end"},
)
for event in events: print(json.dumps(event), flush=True)
'''.replace("PRIVATE_PATH", json.dumps(private_path))
            binding = PiExtensionBinding(
                extension_id="prime.ipython",
                path=extension,
                capabilities=("prime.tool.ipython",),
                inherited_fds=(),
                environment={"ASTERION_PRIME_IPYTHON_TOKEN": secret},
            )
            runtime = self._python_runtime(root, binding, script)
            source_fd = runtime._env["ASTERION_PI_EXTENSION_SOURCE_FD"]
            events = [
                event
                async for event in runtime.run(
                    RunRequest(
                        run_id="adversarial-redaction",
                        input_text="test",
                        requested_capabilities=("prime.tool.ipython",),
                    )
                )
            ]

        rendered = repr([event.to_mapping() for event in events])
        for sensitive in (
            secret,
            private_path,
            "ASTERION_PRIME_IPYTHON_TOKEN",
            "ASTERION_PI_EXTENSION_SOURCE_FD",
            "ASTERION_PI_EXTENSION_SOURCE_NAME",
            "ASTERION_PI_EXTENSION_SOURCE_SHA256",
        ):
            self.assertNotIn(sensitive, rendered)
        self.assertNotIn(f"{source_fd}|", rendered)
        tool_call = next(event for event in events if event.type == "tool.call")
        tool_result = next(event for event in events if event.type == "tool.result")
        usage = next(event for event in events if event.type == "usage.reported")
        self.assertEqual(tool_call.payload["arguments"]["fd"], "<redacted>")
        self.assertEqual(tool_result.payload["output"]["fd"], "<redacted>")
        self.assertEqual(usage.payload["input_tokens"], int(source_fd))
        self.assertIn("<redacted>", rendered)

    async def test_redaction_preserves_protocol_controls_matching_environment(
        self,
    ) -> None:
        script = r'''
import json, os, sys
request = json.loads(sys.stdin.readline())
values = {
    "event_type": os.environ["ASTERION_PRIME_IPYTHON_EVENT_TYPE"],
    "response": os.environ["ASTERION_PRIME_IPYTHON_RESPONSE"],
    "one": os.environ["ASTERION_PRIME_IPYTHON_ONE"],
    "call_fragment": os.environ["ASTERION_PRIME_IPYTHON_CALL_FRAGMENT"],
}
call_id = values["call_fragment"] + values["one"]
free_text = "|".join(values.values())
events = (
    {"type": "response", "id": request["id"], "success": True},
    {"type": "agent_start"},
    {"type": "turn_start"},
    {"type": "tool_execution_start", "toolCallId": call_id, "toolName": "grep",
     "args": dict(values)},
    {"type": "tool_execution_end", "toolCallId": call_id, "isError": False,
     "result": dict(values)},
    {"type": "message_update", "assistantMessageEvent": {
        "type": "text_delta", "delta": free_text}},
    {"type": "message_end", "message": {"role": "assistant", "stopReason": "stop",
     "usage": {"input": 1, "output": 1}, "content": free_text}},
    {"type": "agent_end"},
)
for event in events: print(json.dumps(event), flush=True)
'''
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            binding = PiExtensionBinding(
                extension_id="prime.ipython",
                path=PiExtensionFactoryTests._extension(root),
                capabilities=("prime.tool.ipython",),
                inherited_fds=(),
                environment={
                    "ASTERION_PRIME_IPYTHON_EVENT_TYPE": "type",
                    "ASTERION_PRIME_IPYTHON_RESPONSE": "response",
                    "ASTERION_PRIME_IPYTHON_ONE": "1",
                    "ASTERION_PRIME_IPYTHON_CALL_FRAGMENT": "call-",
                },
            )
            runtime = self._python_runtime(root, binding, script)
            events = [
                event
                async for event in runtime.run(
                    RunRequest(
                        run_id="control-safe-redaction",
                        input_text="test",
                        requested_capabilities=("prime.tool.ipython",),
                    )
                )
            ]

        tool_call = next(event for event in events if event.type == "tool.call")
        tool_result = next(event for event in events if event.type == "tool.result")
        text_delta = next(event for event in events if event.type == "text.delta")
        usage = next(event for event in events if event.type == "usage.reported")
        self.assertEqual(tool_call.payload["call_id"], "call-1")
        self.assertEqual(tool_result.payload["call_id"], "call-1")
        self.assertEqual(
            set(tool_call.payload["arguments"].values()), {"<redacted>"}
        )
        self.assertEqual(set(tool_result.payload["output"].values()), {"<redacted>"})
        self.assertEqual(text_delta.payload["text"], "<redacted>|" * 3 + "<redacted>")
        self.assertEqual(usage.payload, {"input_tokens": 1, "output_tokens": 1})
        self.assertEqual(events[-1].type, "run.completed")

    async def test_extension_errors_are_redacted_and_close_every_lease_fd(self) -> None:
        scripts = (
            r'''
import json, os, sys
request = json.loads(sys.stdin.readline())
secret = os.environ["ASTERION_PRIME_IPYTHON_TOKEN"]
print(secret, file=sys.stderr, flush=True)
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
print(json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": secret}}), flush=True)
print(json.dumps({"type": "message_end", "message": {"role": "assistant", "stopReason": "error", "usage": {"input": 1, "output": 1}, "content": secret}}), flush=True)
print(json.dumps({"type": "agent_end"}), flush=True)
''',
            r'''
import os, sys
sys.stdin.readline()
secret = os.environ["ASTERION_PRIME_IPYTHON_TOKEN"]
print(secret, file=sys.stderr, flush=True)
print(secret, flush=True)
''',
        )
        for index, script in enumerate(scripts):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir).resolve()
                extension = PiExtensionFactoryTests._extension(root)
                secret = f"SECRET-extension-error-{index}"
                binding = PiExtensionBinding(
                    extension_id="prime.ipython",
                    path=extension,
                    capabilities=("prime.tool.ipython",),
                    inherited_fds=(),
                    environment={"ASTERION_PRIME_IPYTHON_TOKEN": secret},
                )
                runtime = self._python_runtime(root, binding, script)
                owned_fds = runtime._inherited_fds
                with self.assertRaises(ProtocolError) as raised:
                    _ = [
                        event
                        async for event in runtime.run(
                            RunRequest(
                                run_id=f"redacted-error-{index}",
                                input_text="test",
                                requested_capabilities=("prime.tool.ipython",),
                            )
                        )
                    ]
                self.assertNotIn(secret, str(raised.exception))
                self.assertNotIn(str(extension), str(raised.exception))
                for descriptor in owned_fds:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)

    async def test_prestart_cancellation_closes_every_extension_lease_fd(self) -> None:
        class Cancelled:
            cancelled = True

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            binding = PiExtensionBinding(
                extension_id="prime.ipython",
                path=PiExtensionFactoryTests._extension(root),
                capabilities=("prime.tool.ipython",),
                inherited_fds=(),
                environment={},
            )
            runtime = self._python_runtime(root, binding, "raise AssertionError")
            owned_fds = runtime._inherited_fds
            with self.assertRaisesRegex(ProtocolError, "cancelled"):
                _ = [
                    event
                    async for event in runtime.run(
                        RunRequest(
                            run_id="cancelled-extension",
                            input_text="test",
                            requested_capabilities=("prime.tool.ipython",),
                        ),
                        signal=Cancelled(),
                    )
                ]

        for descriptor in owned_fds:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    async def test_runtime_passes_only_bound_environment_and_descriptors(self) -> None:
        script = r'''
import json, os, pathlib, sys
request = json.loads(sys.stdin.readline())
fd = int(os.environ["ASTERION_PRIME_IPYTHON_FD"])
os.fstat(fd)
source_fd = int(os.environ["ASTERION_PI_EXTENSION_SOURCE_FD"])
os.fstat(source_fd)
assert os.environ["ASTERION_PRIME_IPYTHON_TOKEN"] == "SECRET-extension-value"
assert sys.argv[-2] == "--extension"
assert pathlib.Path(sys.argv[-1]).name == "asterion_pi_extension_loader.mjs"
assert os.environ["EXPECTED_EXTENSION"] not in sys.argv
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

    @staticmethod
    def _node_runtime(root: Path, binding: PiExtensionBinding):
        context = PiExtensionFactoryTests._context(
            root,
            host_services={"prime.ipython": binding},
            command=json.dumps(
                [
                    str(Path(shutil.which("node") or "node").resolve()),
                    "--input-type=module",
                    "-e",
                    NODE_PI_HARNESS,
                    "--",
                ],
                separators=(",", ":"),
            ),
            environment="{}",
            extension_host_capability="prime.ipython",
        )
        return (
            default_runtime_factory_registry().select("pi.reference").factory(context)
        )

    @staticmethod
    def _python_runtime(root: Path, binding: PiExtensionBinding, script: str):
        context = PiExtensionFactoryTests._context(
            root,
            host_services={"prime.ipython": binding},
            command=json.dumps(
                [str(Path(sys.executable).resolve()), "-u", "-c", script],
                separators=(",", ":"),
            ),
            environment="{}",
            extension_host_capability="prime.ipython",
        )
        return default_runtime_factory_registry().select("pi.reference").factory(context)


if __name__ == "__main__":
    unittest.main()
