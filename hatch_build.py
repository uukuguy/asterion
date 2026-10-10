"""Bundle core and application tool modules into explicit installed Pi extensions."""

from __future__ import annotations

import hashlib
import json
from email.parser import BytesParser
from pathlib import Path
import subprocess
import tempfile

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


_PACKAGE = "packages/typescript/asterion-prime-extension"
_BUNDLE = "src/asterion/applications/prime/resources/ipython-extension.mjs"
_BUNDLES = (_BUNDLE, "src/asterion/applications/prime/resources/p7-research-extension.mjs",
            "src/asterion/applications/prime/resources/p7-legacy-extension.mjs")
_ATTESTATION = ".asterion-prime-extension-build.json"
_INPUTS = tuple(sorted((
    "hatch_build.py",
    "pyproject.toml",
    *(f"{_PACKAGE}/{name}" for name in (
        "package.json", "package-lock.json", "tsconfig.json",
        "tsconfig.contract.json", "test/pi-contract.ts",
        "scripts/build.mjs", "src/ipython-extension.ts", "src/tool-bridge.ts",
        "src/p7-tools.ts", "src/p7-research-extension.ts", "src/p7-legacy-extension.ts",
        "src/context-counter.ts", "src/context-projection.ts", "src/context-witness.ts",
        "src/context-memory.ts", "src/context-archive.ts", "src/context-metrics.ts",
        "src/tool-state-view.ts", "src/tool-schema.ts", "src/provider-prefix-metrics.ts",
    )),
)))


def _read(root: Path, name: str) -> bytes:
    path = root / name
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError("extension build closure is invalid")
    return path.read_bytes()


def _input_digests(root: Path) -> list[dict[str, str]]:
    return [
        {"path": name, "sha256": hashlib.sha256(_read(root, name)).hexdigest()}
        for name in _INPUTS
    ]


def _attestation(
    root: Path,
    bundles: dict[str, bytes] | None = None,
    inputs: list[dict[str, str]] | None = None,
) -> bytes:
    value = {
        "contract": "asterion.prime-extension-build/v1",
        "inputs": _input_digests(root) if inputs is None else inputs,
        "outputs": [
            {"path": name, "sha256": hashlib.sha256(
                _read(root, name) if bundles is None else bundles[name]
            ).hexdigest()}
            for name in _BUNDLES
        ],
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


class CustomBuildHook(BuildHookInterface):
    """Compile source builds; verify and reuse the bundle carried by an sdist."""

    _staging: tempfile.TemporaryDirectory[str] | None = None

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        del version
        root = Path(self.root)
        # PKG-INFO is the standard sdist marker. It selects verification, never
        # permission to trust an arbitrary pre-existing bundle or to run npm.
        marker = root / "PKG-INFO"
        if marker.exists() or marker.is_symlink():
            try:
                if not marker.is_file() or marker.is_symlink():
                    raise ValueError
                metadata = BytesParser().parsebytes(_read(root, "PKG-INFO"))
                if (
                    metadata.get_all("Name") != ["asterion"]
                    or metadata.get_all("Version") != [self.metadata.version]
                    or _read(root, _ATTESTATION) != _attestation(root)
                ):
                    raise ValueError
            except (OSError, ValueError):
                raise ValueError("extension build closure is invalid") from None
            return
        inputs = _input_digests(root)
        self._staging = tempfile.TemporaryDirectory(prefix="asterion-prime-build-")
        staging = Path(self._staging.name)
        bundle = staging / "ipython-extension.mjs"
        attestation = staging / _ATTESTATION
        try:
            # The final esbuild option overrides the package's normal outfile.
            # No invocation writes a shared dist or source-tree resource.
            subprocess.run(
                ("npm", "run", "build", "--", f"--outfile={bundle}"),
                cwd=root / _PACKAGE,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if inputs != _input_digests(root):
                raise ValueError("extension build closure is invalid")
            compiled = {name: (staging / Path(name).name).read_bytes() for name in _BUNDLES}
            attestation.write_bytes(_attestation(root, compiled, inputs))
            force_include = build_data.setdefault("force_include", {})
            if not isinstance(force_include, dict):
                raise ValueError("extension build closure is invalid")
            for name in _BUNDLES:
                force_include[str(staging / Path(name).name)] = (
                    name if self.target_name == "sdist" else name.removeprefix("src/")
                )
            if self.target_name == "sdist":
                force_include[str(attestation)] = _ATTESTATION
        except BaseException:
            self.finalize("", {}, "")
            raise

    def finalize(self, version: str, build_data: dict[str, object], artifact_path: str) -> None:
        del version, build_data, artifact_path
        staging, self._staging = self._staging, None
        if staging is not None:
            staging.cleanup()
