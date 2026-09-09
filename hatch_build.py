"""Generate the self-contained native P7 Pi extension for package builds."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Build the TypeScript extension before Hatch collects wheel artifacts."""

    _destination: Path | None = None

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        del version, build_data
        root = Path(self.root)
        package = root / "packages/typescript/asterion-prime-extension"
        subprocess.run(
            ("npm", "run", "build"),
            cwd=package,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        source = package / "dist/ipython-extension.mjs"
        destination = root / "src/asterion/applications/prime/resources/ipython-extension.mjs"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        self._destination = destination

    def finalize(self, version: str, build_data: dict[str, object], artifact_path: str) -> None:
        del version, build_data, artifact_path
        if self._destination is not None:
            self._destination.unlink(missing_ok=True)
