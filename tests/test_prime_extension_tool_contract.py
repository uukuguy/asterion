from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from asterion.agents.prime.tool_registry import CORE_TOOL_REGISTRY
from asterion.runtime.pinned_extension import _validate_source
from asterion.applications.prime.p7.tool_registry import P7_TOOL_REGISTRY, P7_LEGACY_TOOL_REGISTRY


PROJECT = Path(__file__).resolve().parents[1]
RESOURCES = PROJECT / "src/asterion/applications/prime/resources"
PACKAGE = PROJECT / "packages/typescript/asterion-prime-extension"


class TestPrimeExtensionToolContract(unittest.TestCase):
    def test_explicit_bundles_match_their_complete_python_tool_registries(self) -> None:
        for name, registry, module in (
            ("ipython-extension.mjs", CORE_TOOL_REGISTRY, "coreOnlyModule"),
            ("p7-research-extension.mjs", P7_TOOL_REGISTRY, "p7ResearchModule"),
            ("p7-legacy-extension.mjs", P7_LEGACY_TOOL_REGISTRY, "p7LegacyModule"),
        ):
            with self.subTest(artifact=name):
                script = (
                    "import * as extension from " + json.dumps((RESOURCES / name).as_uri())
                    + "; process.stdout.write(JSON.stringify(extension[" + json.dumps(module) + "].registry));"
                )
                result = subprocess.run(
                    ["node", "--input-type=module", "-e", script], cwd=PROJECT,
                    check=True, capture_output=True, text=True,
                )
                self.assertEqual(json.loads(result.stdout), json.loads(registry.environment_value()))
                if name == "ipython-extension.mjs":
                    source = (RESOURCES / name).read_text()
                    self.assertNotIn("p7_workspace", source)
                    self.assertNotIn("p7_execute_plan", source)
                    self.assertNotIn("prime.p7.application-tools", source)

    def test_pin_accepts_real_default_export_forms_and_rejects_lookalikes(self) -> None:
        for source in (
            b"export default function register() {}",
            b"function register(){}export{register as default};",
            b"function register(){}const named=1;export{named,register as default};",
        ):
            with self.subTest(source=source):
                try:
                    _validate_source("external.mjs", source)
                except ValueError:
                    self.fail("pin rejected a genuine local ESM default export")
        for source in (
            b"function register(){}export{register};",
            b"function register(){}export{register as named};",
            b"const label='export default';export{};",
            b"function register(){}export{register as default bogus};",
            b"function register(){}export{register as default}from './neighbor.mjs';",
            b"import value from 'package';function register(){}export{register as default};",
            b"const dependency=import('node:fs');function register(){}export{register as default};",
        ):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    _validate_source("external.mjs", source)

    def test_external_application_builds_from_installed_core_bundle_and_loads_its_own_wheel(self) -> None:
        """The application has no checkout source or unpublished npm SDK dependency."""
        with tempfile.TemporaryDirectory(prefix="prime-independent-tools-") as temporary:
            root = Path(temporary).resolve()
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)

            def run(*args: str) -> subprocess.CompletedProcess[str]:
                result = subprocess.run(args, cwd=root, env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result

            run("uv", "build", "--wheel", "--out-dir", str(root / "framework-dist"), str(PROJECT))
            wheel = next((root / "framework-dist").glob("*.whl"))
            run("uv", "venv", str(root / "venv"))
            python = str(root / "venv/bin/python")
            run("uv", "pip", "install", "--python", python, "--no-deps", str(wheel))
            # Only importlib.resources from the installed wheel supplies the core.
            core = Path(run(python, "-c", "from importlib.resources import files; "
                "print(files('asterion.applications.prime').joinpath('resources/ipython-extension.mjs'))").stdout.strip())
            self.assertTrue(core.is_relative_to(root / "venv"))
            application = root / "application"
            resources = application / "src/independent_prime_app/resources"
            resources.mkdir(parents=True)
            (resources.parent / "__init__.py").write_text("")
            (application / "pyproject.toml").write_text(
                '[build-system]\nrequires=["hatchling"]\nbuild-backend="hatchling.build"\n'
                '[project]\nname="independent-prime-app"\nversion="0.1.0"\n'
                '[tool.hatch.build.targets.wheel]\npackages=["src/independent_prime_app"]\n'
            )
            source = root / "independent-extension.ts"
            source.write_text(
                'import { registerPrime } from ' + json.dumps(str(core)) + ';\n'
                'const registry = {module_id:"independent.tools",capability_id:"independent.tool.query",'
                'tool_names:["independent_query","ipython"]};\n'
                'const module: {registry: typeof registry; createTools(bridge: unknown): readonly object[]; '
                'registerContextHooks(pi: {on(event: string, hook: () => void): void}): void} = {\n'
                ' registry, createTools: () => [{name:"independent_query",label:"query",description:"Read application state.",'
                'parameters:{type:"object",properties:{},additionalProperties:false},'
                'execute:async()=>({content:[{type:"text",text:"query-result"}],details:{}})}],\n'
                ' registerContextHooks(pi) {pi.on("context",()=>{});}\n};\n'
                'export default function register(pi: unknown, dependencies: unknown) {'
                'registerPrime(pi,dependencies,module);}\n'
            )
            run(str(PACKAGE / "node_modules/.bin/esbuild"), str(source), "--bundle", "--platform=node",
                "--format=esm", "--target=node20", "--supported:template-literal=false",
                "--legal-comments=none", "--minify-syntax", "--minify-whitespace",
                "--outfile=" + str(resources / "application-extension.mjs"))
            run("uv", "build", "--wheel", "--out-dir", str(root / "application-dist"), str(application))
            run("uv", "pip", "install", "--python", python, "--no-deps",
                str(next((root / "application-dist").glob("*.whl"))))
            installed = root / "verify-installed.py"
            installed.write_text(_INSTALLED_APPLICATION_PROBE)
            result = run(python, str(installed))
            self.assertEqual(json.loads(result.stdout), {"tools": ["independent_query", "ipython"], "hooks": ["context"]})


_INSTALLED_APPLICATION_PROBE = r'''
import json
import os
from importlib.resources import files
from pathlib import Path
import subprocess
import tempfile
from asterion.agents.prime.application import PrimeToolModuleArtifact
from asterion.agents.prime.tool_registry import PrimeApplicationToolRegistry, TOOL_REGISTRY_ENV
from asterion.runtime.pinned_extension import ExtensionBinding, ExtensionLease

registry = PrimeApplicationToolRegistry("independent.tools", "independent.tool.query", ("independent_query", "ipython"))
artifact = PrimeToolModuleArtifact(Path(files("independent_prime_app").joinpath("resources/application-extension.mjs")), registry)
loader = Path(files("asterion.runtimes").joinpath("resources/asterion_pi_extension_loader.mjs"))
# Supply the existing pinned loader's host mechanics without an installed Pi or model process.
host = loader.parent / "node_modules/@earendil-works/pi-coding-agent"
host.mkdir(parents=True)
(host / "package.json").write_text(json.dumps({"name":"@earendil-works/pi-coding-agent", "type":"module", "exports":"./index.js"}))
(host / "index.js").write_text("export const buildSessionContext=()=>({messages:[]}); export const convertToLlm=x=>x; export const serializeConversation=()=>'';")
ai_host = host.parent / "pi-ai"
ai_host.mkdir()
(ai_host / "package.json").write_text(json.dumps({"type":"module", "exports":"./index.js"}))
(ai_host / "index.js").write_text("export const getCurrentSystemMessage=()=>undefined;")
with tempfile.TemporaryFile() as bridge:
    binding = ExtensionBinding(extension_id="prime.ipython", path=artifact.path,
        capabilities=("prime.tool.ipython",), inherited_fds=(bridge.fileno(),),
        environment={"ASTERION_PRIME_IPYTHON_FD":str(bridge.fileno()), TOOL_REGISTRY_ENV:registry.environment_value()})
    lease = ExtensionLease.open(binding, loader)
    try:
        lease.validate_launch()
        script = "import load from " + json.dumps(loader.as_uri()) + "; const tools=[],hooks=[]; await load({registerTool:t=>tools.push(t.name),on:e=>hooks.push(e)}); process.stdout.write(JSON.stringify({tools:tools.sort(),hooks}));"
        result = subprocess.run(["node","--input-type=module","-e",script],
            env={**os.environ, **lease.environment}, pass_fds=lease.inherited_fds,
            check=True, capture_output=True, text=True)
        print(result.stdout)
    finally:
        lease.close()
'''


if __name__ == "__main__":
    unittest.main()
