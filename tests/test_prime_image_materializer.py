"""Tests for the explicit, non-executing Prime image input materializer."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from asterion.applications.prime_agent.operator.image_input_lock import ImagePlatformDescriptor
from tools import materialize_prime_ipython_inputs as materializer


_INITIAL_PLATFORM = ImagePlatformDescriptor("linux", "amd64", None)


class TestPrimeImageMaterializer(unittest.TestCase):
    def test_returns_only_an_explicit_release_command_plan(self) -> None:
        with TemporaryDirectory() as temporary:
            output = (Path(temporary) / "operator-artifacts").resolve()
            plan = materializer.plan_materialization(output, _INITIAL_PLATFORM)

        self.assertEqual(plan.output_root, output)
        self.assertEqual(plan.platform, _INITIAL_PLATFORM)
        self.assertEqual(plan.recipe_sha256, materializer.recipe_sha256())
        self.assertTrue(plan.commands)
        self.assertTrue(all(isinstance(command, tuple) for command in plan.commands))
        self.assertTrue(all("docker" not in command and "pip" not in command and "npm" not in command and "uv" not in command for command in plan.commands))
        self.assertIn("separately authorized", plan.notice)

    def test_rejects_non_external_existing_or_unsafe_output_roots(self) -> None:
        with TemporaryDirectory() as temporary:
            external = Path(temporary).resolve()
            existing = external / "existing"
            existing.mkdir()
            for target in (
                Path("relative"),
                existing,
                materializer.repository_root() / "external",
                materializer.repository_root().parent / "source-target",
            ):
                with self.subTest(target=target), self.assertRaises(materializer.PrimeImageMaterializerError):
                    materializer.plan_materialization(target, _INITIAL_PLATFORM)

    def test_planning_does_not_execute_or_materialize_anything(self) -> None:
        with TemporaryDirectory() as temporary:
            output = (Path(temporary) / "fresh").resolve()
            forbidden = RuntimeError("effectful access")
            with (
                mock.patch("subprocess.run", side_effect=forbidden),
                mock.patch("socket.create_connection", side_effect=forbidden),
                mock.patch.object(Path, "mkdir", side_effect=forbidden),
                mock.patch.object(Path, "write_bytes", side_effect=forbidden),
            ):
                materializer.plan_materialization(output, _INITIAL_PLATFORM)
            self.assertFalse(output.exists())
