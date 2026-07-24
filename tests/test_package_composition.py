from __future__ import annotations

import unittest
from collections.abc import Callable

from asterion.packages.composition import (
    PackageCompositionError,
    compose_packages,
)


def package(
    package_id: str,
    *,
    kind: str = "capability",
    provides_capabilities: list[str] | None = None,
    requires_capabilities: list[str] | None = None,
    requires_policies: list[str] | None = None,
    emits_events: list[str] | None = None,
    consumes_events: list[str] | None = None,
    produces_artifacts: list[str] | None = None,
    consumes_artifacts: list[str] | None = None,
) -> dict[str, object]:
    return {
        "protocol": "dci.package/v1",
        "package_id": package_id,
        "version": "1.0.0",
        "kind": kind,
        "provides_capabilities": provides_capabilities or [],
        "requires_capabilities": requires_capabilities or [],
        "requires_policies": requires_policies or [],
        "emits_events": emits_events or [],
        "consumes_events": consumes_events or [],
        "produces_artifacts": produces_artifacts or [],
        "consumes_artifacts": consumes_artifacts or [],
    }


def manifests_with_two_capability_providers() -> tuple[dict[str, object], ...]:
    return (
        package("capability.one", provides_capabilities=["shared.cap"]),
        package("capability.two", provides_capabilities=["shared.cap"]),
    )


def manifests_with_two_event_providers() -> tuple[dict[str, object], ...]:
    return (
        package("event.one", emits_events=["shared.event"]),
        package("event.two", emits_events=["shared.event"]),
    )


def manifests_with_two_artifact_providers() -> tuple[dict[str, object], ...]:
    return (
        package("artifact.one", produces_artifacts=["text/plain"]),
        package("artifact.two", produces_artifacts=["text/plain"]),
    )


def manifests_with_capability_provider() -> tuple[dict[str, object], ...]:
    return (package("capability.provider", provides_capabilities=["shared.cap"]),)


def manifests_with_policy_provider() -> tuple[dict[str, object], ...]:
    return (package("policy.shared", kind="policy"),)


def manifests_with_event_provider() -> tuple[dict[str, object], ...]:
    return (package("event.provider", emits_events=["shared.event"]),)


def manifests_with_artifact_provider() -> tuple[dict[str, object], ...]:
    return (package("artifact.provider", produces_artifacts=["text/plain"]),)


ManifestBuilder = Callable[[], tuple[dict[str, object], ...]]


class PackageCompositionTests(unittest.TestCase):
    def test_rejects_every_provider_ambiguity(self) -> None:
        cases: tuple[tuple[str, ManifestBuilder, dict[str, frozenset[str]]], ...] = (
            ("duplicate-capability-package", manifests_with_two_capability_providers, {}),
            ("duplicate-event-package", manifests_with_two_event_providers, {}),
            ("duplicate-artifact-package", manifests_with_two_artifact_providers, {}),
            (
                "host-package-capability",
                manifests_with_capability_provider,
                {"host_capabilities": frozenset({"shared.cap"})},
            ),
            (
                "host-package-policy",
                manifests_with_policy_provider,
                {"host_policies": frozenset({"policy.shared"})},
            ),
            (
                "host-package-event",
                manifests_with_event_provider,
                {"host_events": frozenset({"shared.event"})},
            ),
            (
                "host-package-artifact",
                manifests_with_artifact_provider,
                {"host_artifacts": frozenset({"text/plain"})},
            ),
        )

        for name, build_manifests, kwargs in cases:
            with self.subTest(name=name), self.assertRaises(PackageCompositionError):
                compose_packages(build_manifests(), **kwargs)

    def test_composes_a_single_package_provider(self) -> None:
        composition = compose_packages(
            (
                package("consumer", requires_capabilities=["shared.cap"]),
                package("provider", provides_capabilities=["shared.cap"]),
            )
        )

        self.assertEqual(composition.package_ids, ("provider", "consumer"))
        self.assertEqual(composition.provided_capabilities, ("shared.cap",))

    def test_composes_a_single_host_provider(self) -> None:
        composition = compose_packages(
            (package("consumer", requires_capabilities=["shared.cap"]),),
            host_capabilities=frozenset({"shared.cap"}),
        )

        self.assertEqual(composition.package_ids, ("consumer",))

    def test_output_is_independent_of_manifest_input_order(self) -> None:
        manifests = (
            package("consumer", requires_capabilities=["shared.cap"]),
            package("provider", provides_capabilities=["shared.cap"]),
            package("unrelated"),
        )

        self.assertEqual(compose_packages(manifests), compose_packages(reversed(manifests)))

    def test_rejects_missing_required_edges(self) -> None:
        cases = (
            package("capability.consumer", requires_capabilities=["missing.cap"]),
            package("policy.consumer", requires_policies=["policy.missing"]),
            package("event.consumer", consumes_events=["missing.event"]),
            package("artifact.consumer", consumes_artifacts=["application/missing"]),
        )

        for manifest in cases:
            with self.subTest(package_id=manifest["package_id"]):
                with self.assertRaises(PackageCompositionError):
                    compose_packages((manifest,))

    def test_rejects_dependency_cycles(self) -> None:
        manifests = (
            package(
                "one",
                provides_capabilities=["one.cap"],
                requires_capabilities=["two.cap"],
            ),
            package(
                "two",
                provides_capabilities=["two.cap"],
                requires_capabilities=["one.cap"],
            ),
        )

        with self.assertRaises(PackageCompositionError):
            compose_packages(manifests)


if __name__ == "__main__":
    unittest.main()
