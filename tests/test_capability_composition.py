from __future__ import annotations

import unittest
from collections.abc import Callable

from asterion.capabilities.composition import (
    CapabilityCompositionError,
    compose_capabilities,
)


def capability(
    capability_id: str,
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
        "protocol": "asterion.capability/v1",
        "capability_id": capability_id,
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
        capability("capability.one", provides_capabilities=["shared.cap"]),
        capability("capability.two", provides_capabilities=["shared.cap"]),
    )


def manifests_with_two_event_providers() -> tuple[dict[str, object], ...]:
    return (
        capability("event.one", emits_events=["shared.event"]),
        capability("event.two", emits_events=["shared.event"]),
    )


def manifests_with_two_artifact_providers() -> tuple[dict[str, object], ...]:
    return (
        capability("artifact.one", produces_artifacts=["text/plain"]),
        capability("artifact.two", produces_artifacts=["text/plain"]),
    )


def manifests_with_capability_provider() -> tuple[dict[str, object], ...]:
    return (capability("capability.provider", provides_capabilities=["shared.cap"]),)


def manifests_with_policy_provider() -> tuple[dict[str, object], ...]:
    return (capability("policy.shared", kind="policy"),)


def manifests_with_event_provider() -> tuple[dict[str, object], ...]:
    return (capability("event.provider", emits_events=["shared.event"]),)


def manifests_with_artifact_provider() -> tuple[dict[str, object], ...]:
    return (capability("artifact.provider", produces_artifacts=["text/plain"]),)


ManifestBuilder = Callable[[], tuple[dict[str, object], ...]]


class CapabilityCompositionTests(unittest.TestCase):
    def test_rejects_every_provider_ambiguity(self) -> None:
        cases: tuple[tuple[str, ManifestBuilder, dict[str, frozenset[str]]], ...] = (
            ("duplicate-capability-capability", manifests_with_two_capability_providers, {}),
            ("duplicate-event-capability", manifests_with_two_event_providers, {}),
            ("duplicate-artifact-capability", manifests_with_two_artifact_providers, {}),
            (
                "host-capability-capability",
                manifests_with_capability_provider,
                {"host_capabilities": frozenset({"shared.cap"})},
            ),
            (
                "host-capability-policy",
                manifests_with_policy_provider,
                {"host_policies": frozenset({"policy.shared"})},
            ),
            (
                "host-capability-event",
                manifests_with_event_provider,
                {"host_events": frozenset({"shared.event"})},
            ),
            (
                "host-capability-artifact",
                manifests_with_artifact_provider,
                {"host_artifacts": frozenset({"text/plain"})},
            ),
        )

        for name, build_manifests, kwargs in cases:
            with self.subTest(name=name), self.assertRaises(CapabilityCompositionError):
                compose_capabilities(build_manifests(), **kwargs)

    def test_composes_a_single_capability_provider(self) -> None:
        composition = compose_capabilities(
            (
                capability("consumer", requires_capabilities=["shared.cap"]),
                capability("provider", provides_capabilities=["shared.cap"]),
            )
        )

        self.assertEqual(composition.capability_ids, ("provider", "consumer"))
        self.assertEqual(composition.provided_capabilities, ("shared.cap",))

    def test_composes_a_single_host_provider(self) -> None:
        composition = compose_capabilities(
            (capability("consumer", requires_capabilities=["shared.cap"]),),
            host_capabilities=frozenset({"shared.cap"}),
        )

        self.assertEqual(composition.capability_ids, ("consumer",))

    def test_output_is_independent_of_manifest_input_order(self) -> None:
        manifests = (
            capability("consumer", requires_capabilities=["shared.cap"]),
            capability("provider", provides_capabilities=["shared.cap"]),
            capability("unrelated"),
        )

        self.assertEqual(compose_capabilities(manifests), compose_capabilities(reversed(manifests)))

    def test_rejects_missing_required_edges(self) -> None:
        cases = (
            capability("capability.consumer", requires_capabilities=["missing.cap"]),
            capability("policy.consumer", requires_policies=["policy.missing"]),
            capability("event.consumer", consumes_events=["missing.event"]),
            capability("artifact.consumer", consumes_artifacts=["application/missing"]),
        )

        for manifest in cases:
            with self.subTest(capability_id=manifest["capability_id"]):
                with self.assertRaises(CapabilityCompositionError):
                    compose_capabilities((manifest,))

    def test_rejects_dependency_cycles(self) -> None:
        manifests = (
            capability(
                "one",
                provides_capabilities=["one.cap"],
                requires_capabilities=["two.cap"],
            ),
            capability(
                "two",
                provides_capabilities=["two.cap"],
                requires_capabilities=["one.cap"],
            ),
        )

        with self.assertRaises(CapabilityCompositionError):
            compose_capabilities(manifests)


if __name__ == "__main__":
    unittest.main()
