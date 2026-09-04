"""Installed Prime application discovery and provider-free preflight tests."""

from __future__ import annotations

from hashlib import sha256
from importlib import metadata
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from asterion.applications.discovery import (
    list_application_providers,
    load_application_provider,
    select_application_provider_id,
)
from asterion.applications.prime_agent.preflight import prime_preflight
from asterion.applications.prime_agent.provider import (
    preflight_arc_agi_3_worker_factory,
    create_provider,
)
from asterion.applications.prime_agent.operator.restricted_scenario_worker import (
    RestrictedScenarioInspection,
)
from asterion.applications.prime_agent.restricted_worker import (
    PrimeRestrictedWorkerProfile,
)
from asterion.services.restricted_worker import RestrictedWorkerLease
from asterion.applications.prime_agent.source_lock import PrimeSourceLock


def _profile(**changes: object) -> PrimeRestrictedWorkerProfile:
    values: dict[str, object] = {
        "image_digest": "sha256:" + "a" * 64,
        "network_mode": "none",
        "workspace_mode": "disposable",
        "credential_mode": "absent",
        "max_runtime_seconds": 300,
        "max_output_bytes": 65536,
    }
    values.update(changes)
    return PrimeRestrictedWorkerProfile(**values)  # type: ignore[arg-type]


def _source_lock(**changes: object) -> PrimeSourceLock:
    values: dict[str, object] = {
        "commit": "b" * 40,
        "tree_sha256": "c" * 64,
        "package_lock_sha256": "d" * 64,
    }
    values.update(changes)
    return PrimeSourceLock(**values)  # type: ignore[arg-type]


def _write_source(root: Path) -> PrimeSourceLock:
    commit = "b" * 40
    (root / ".git").mkdir()
    (root / "src").mkdir()
    (root / ".git" / "HEAD").write_text(f"{commit}\n")
    (root / "package.json").write_text(json.dumps({"version": "1.0.0"}))
    (root / "package-lock.json").write_text(
        json.dumps({"lockfileVersion": 3, "packages": {"": {"version": "1.0.0"}}})
    )
    (root / "src" / "main.ts").write_text("export const prime = 1;\n")
    tree = sha256()
    for relative_path in ("package.json", "src/main.ts"):
        tree.update(relative_path.encode("utf-8"))
        tree.update(b"\0")
        tree.update((root / relative_path).read_bytes())
        tree.update(b"\0")
    return PrimeSourceLock(
        commit=commit,
        tree_sha256=tree.hexdigest(),
        package_lock_sha256=sha256((root / "package-lock.json").read_bytes()).hexdigest(),
    )


class TestPrimeApplicationProvider(unittest.TestCase):
    def test_p7_preflight_returns_an_inert_fixed_worker_factory(self) -> None:
        class Engine:
            async def launch(self, **kwargs: object) -> RestrictedWorkerLease:
                raise AssertionError("factory launched a worker")

            async def completion_bytes(self, lease: RestrictedWorkerLease) -> bytes:
                raise AssertionError("factory read a worker")

            async def inspect(
                self, lease: RestrictedWorkerLease
            ) -> RestrictedScenarioInspection:
                raise AssertionError("factory inspected a worker")

            async def remove(self, lease: RestrictedWorkerLease) -> None:
                raise AssertionError("factory removed a worker")

        with TemporaryDirectory() as temporary_directory:
            source_root = (Path(temporary_directory) / "prime-agent").resolve()
            source_root.mkdir()
            result = preflight_arc_agi_3_worker_factory(
                profile=_profile(max_runtime_seconds=300, max_output_bytes=4096),
                expected_source_lock=_write_source(source_root),
                source_root=source_root,
            )
        self.assertEqual(result.status, "PASS")
        self.assertIsNotNone(result.factory)
        worker = result.factory(engine=Engine())  # type: ignore[union-attr]
        self.assertEqual(worker._adapter.scenario_id, "prime.arc-agi-3/v1")

    def test_p7_preflight_rejects_profiles_outside_its_fixed_limits(self) -> None:
        for profile in (
            _profile(max_runtime_seconds=299, max_output_bytes=4096),
            _profile(max_runtime_seconds=300, max_output_bytes=4095),
        ):
            with TemporaryDirectory() as temporary_directory:
                source_root = (Path(temporary_directory) / "prime-agent").resolve()
                source_root.mkdir()
                with self.subTest(profile=profile):
                    result = preflight_arc_agi_3_worker_factory(
                        profile=profile,
                        expected_source_lock=_write_source(source_root),
                        source_root=source_root,
                    )
                    self.assertEqual(result.status, "worker-invalid")
                    self.assertIsNone(result.factory)

    def test_provider_declares_one_metadata_only_application(self) -> None:
        provider = create_provider()

        self.assertEqual(provider.provider_id, "prime-agent")
        self.assertEqual(
            [(item.application_id, item.version) for item in provider.applications],
            [("prime.capability-program", "1.0.0")],
        )

    def test_installed_entry_point_discovers_and_loads_prime_provider(self) -> None:
        entries = tuple(metadata.entry_points(group="asterion.applications"))

        self.assertIn(
            "prime-agent",
            [item.provider_id for item in list_application_providers(entry_points=entries)],
        )
        self.assertEqual(load_application_provider("prime-agent").provider_id, "prime-agent")
        self.assertEqual(
            select_application_provider_id("prime.capability-program@1.0.0"),
            "prime-agent",
        )

    def test_preflight_verifies_trusted_lock_against_explicit_source_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            source_root = (Path(temporary_directory) / "prime-agent").resolve()
            source_root.mkdir()
            source_lock = _write_source(source_root)

            self.assertEqual(
                prime_preflight(_profile(), source_lock, source_root).status,
                "PASS",
            )

    def test_preflight_rejects_format_valid_forged_source_lock(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            source_root = (Path(temporary_directory) / "prime-agent").resolve()
            source_root.mkdir()
            source_lock = _write_source(source_root)
            forged_lock = PrimeSourceLock(
                commit=source_lock.commit,
                tree_sha256="f" * 64,
                package_lock_sha256=source_lock.package_lock_sha256,
            )

            self.assertEqual(
                prime_preflight(_profile(), forged_lock, source_root).status,
                "source-invalid",
            )

    def test_preflight_returns_fixed_safe_failure_codes(self) -> None:
        cases = (
            (None, _source_lock(), "worker-unavailable"),
            (_profile(network_mode="host"), _source_lock(), "worker-invalid"),
            (_profile(), PrimeSourceLock("invalid", "c" * 64, "d" * 64), "source-invalid"),
        )

        for profile, source_lock, expected in cases:
            with self.subTest(expected=expected):
                result = prime_preflight(profile, source_lock, Path("/unsafe"))  # type: ignore[arg-type]
                self.assertEqual(result.status, expected)
                self.assertNotIn("sha256:", repr(result))


if __name__ == "__main__":
    unittest.main()
