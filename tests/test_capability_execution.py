from __future__ import annotations

import json
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from types import MappingProxyType

from asterion.assembly.protocol import resolve_assembly
from asterion.capabilities.catalog import (
    CatalogEntry,
    CapabilityCatalog,
    CapabilityRef,
    discover_capabilities,
)
from asterion.capabilities.execution import (
    InProcessArtifactPayload,
    CapabilityExecutionError,
    CapabilityExecutionResult,
    CapabilityInvocation,
    project_public_value,
    validate_implementation_bindings,
    validate_capability_result,
)
from asterion.runner.application import ApplicationRunError
from asterion.runner.composed import run_composed_application
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"
MANIFEST_ROOT = SOURCE / "capabilities/dci_research/manifests"
ASSEMBLY = (
    SOURCE
    / "applications/dci_agent_lite/assemblies/dci-local-research.json"
)


class FixtureRuntime:
    manifest = RuntimeManifest(
        runtime_id="pi.reference",
        capabilities=("filesystem.read", "shell"),
    )

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del request, signal
        if False:
            yield RunEvent("", 0, "", {})


class RecordingImplementation:
    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        del invocation
        return CapabilityExecutionResult(events=(), artifacts=())


class NonCallableImplementation:
    execute = "SECRET-NON-CALLABLE-IMPLEMENTATION"


class ResultImplementation:
    def __init__(self, result: CapabilityExecutionResult) -> None:
        self.result = result
        self.invocations: list[CapabilityInvocation] = []

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        self.invocations.append(invocation)
        return self.result


class MutatingImplementation(ResultImplementation):
    def __init__(
        self,
        result: CapabilityExecutionResult,
        *,
        event: dict[str, object],
        artifact: dict[str, object],
    ) -> None:
        super().__init__(result)
        self.event = event
        self.artifact = artifact

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        self.invocations.append(invocation)
        self.event["type"] = "host.changed"
        event_payload = self.event["payload"]
        assert isinstance(event_payload, dict)
        event_payload["nested"] = {"status": "changed"}
        self.artifact["media_type"] = "application/vnd.host-changed+json"
        artifact_value = self.artifact["value"]
        assert isinstance(artifact_value, dict)
        artifact_value["nested"] = {"status": "changed"}
        return self.result


def resolve_plan():
    return resolve_assembly(
        json.loads(ASSEMBLY.read_text()),
        catalog=discover_capabilities((MANIFEST_ROOT,)),
        runtime_manifest=FixtureRuntime.manifest.to_mapping(),
    )


def evidence_plan():
    producer = {
        "protocol": "asterion.capability/v1",
        "capability_id": "evidence.producer",
        "version": "1.0.0",
        "kind": "capability",
        "provides_capabilities": [],
        "requires_capabilities": [],
        "requires_policies": [],
        "emits_events": ["producer.completed"],
        "consumes_events": [],
        "produces_artifacts": ["application/vnd.producer+json"],
        "consumes_artifacts": [],
    }
    consumer = {
        "protocol": "asterion.capability/v1",
        "capability_id": "evidence.consumer",
        "version": "1.0.0",
        "kind": "evaluation",
        "provides_capabilities": [],
        "requires_capabilities": [],
        "requires_policies": [],
        "emits_events": [],
        "consumes_events": ["host.ready", "producer.completed"],
        "produces_artifacts": ["application/vnd.consumer+json"],
        "consumes_artifacts": [
            "application/vnd.host-input+json",
            "application/vnd.producer+json",
        ],
    }
    catalog = CapabilityCatalog(
        entries=tuple(
            CatalogEntry(
                ref=CapabilityRef(str(manifest["capability_id"]), "1.0.0"),
                source=PROJECT / f'{manifest["capability_id"]}.json',
                manifest=manifest,
            )
            for manifest in (consumer, producer)
        )
    )
    assembly = {
        "protocol": "dci.assembly/v1",
        "application_id": "evidence.application",
        "version": "1.0.0",
        "runtime_id": "pi.reference",
        "packages": [
            {"package_id": "evidence.consumer", "version": "1.0.0"},
            {"package_id": "evidence.producer", "version": "1.0.0"},
        ],
        "host_capabilities": [],
        "host_policies": [],
        "host_events": ["host.ready"],
        "host_artifacts": ["application/vnd.host-input+json"],
    }
    return resolve_assembly(
        assembly,
        catalog=catalog,
        runtime_manifest=FixtureRuntime.manifest.to_mapping(),
    )


def producer_result():
    return CapabilityExecutionResult(
        events=({
            "type": "producer.completed",
            "payload": {"nested": {"status": "complete"}},
        },),
        artifacts=({
            "artifact_id": "producer-artifact",
            "media_type": "application/vnd.producer+json",
            "value": {"nested": {"status": "complete"}},
        },),
    )


def host_events():
    return ({
        "type": "host.ready",
        "payload": {"nested": {"status": "ready"}},
    },)


def host_artifacts():
    return ({
        "artifact_id": "host-input",
        "media_type": "application/vnd.host-input+json",
        "value": {"nested": {"status": "ready"}},
    },)


class DciResearchManifestDeclarationTests(unittest.TestCase):
    def test_research_does_not_consume_runtime_internal_host_evidence(self) -> None:
        manifest = json.loads((MANIFEST_ROOT / "dci-research.json").read_text())

        self.assertEqual(manifest["consumes_events"], [])
        self.assertEqual(manifest["consumes_artifacts"], [])


class InProcessArtifactPayloadTests(unittest.TestCase):
    def test_private_value_is_deeply_immutable_and_repr_redacted(self) -> None:
        private = {
            "nested": {
                "values": ["SENTINEL_QUESTION", {"gold": "SENTINEL_GOLD"}]
            }
        }
        payload = InProcessArtifactPayload(
            private_value=private,
            public_projection={
                "status": "completed",
                "question_sha256": "a" * 64,
            },
        )
        private["nested"]["values"][1]["gold"] = "changed"

        self.assertEqual(
            payload.private_value["nested"]["values"][1]["gold"],
            "SENTINEL_GOLD",
        )
        with self.assertRaises(TypeError):
            payload.private_value["nested"]["values"][0] = "changed"
        with self.assertRaises(AttributeError):
            payload._private_value = {}  # type: ignore[reportAttributeAccessIssue]
        self.assertNotIn("SENTINEL", repr(payload))
        self.assertNotIn("SENTINEL", str(payload))

    def test_public_projection_recurses_through_mappings_and_sequences(self) -> None:
        payload = InProcessArtifactPayload(
            private_value={
                "question": "SENTINEL_QUESTION",
                "nested": ({"prediction": "SENTINEL_PREDICTION"},),
            },
            public_projection={
                "status": "completed",
                "hashes": ("a" * 64, "b" * 64),
                "artifact_ids": ("answer",),
            },
        )

        projected = project_public_value(
            {
                "artifacts": (
                    {
                        "artifact_id": "research",
                        "value": {"stage_data": payload},
                    },
                )
            }
        )

        self.assertEqual(
            projected["artifacts"][0]["value"]["stage_data"]["status"],
            "completed",
        )
        self.assertEqual(
            projected["artifacts"][0]["value"]["stage_data"]["artifact_ids"],
            ["answer"],
        )
        rendered = json.dumps(projected, sort_keys=True)
        self.assertNotIn("SENTINEL", rendered)
        with self.assertRaises(TypeError):
            payload.public_projection["status"] = "changed"

    def test_public_projection_rejects_opaque_values_fail_closed(self) -> None:
        with self.assertRaises(CapabilityExecutionError) as raised:
            project_public_value({"value": object()})

        self.assertEqual(
            str(raised.exception), "artifact public projection is invalid"
        )

        with self.assertRaises(CapabilityExecutionError) as private:
            InProcessArtifactPayload(
                private_value={"mutable": object()},
                public_projection={},
            )
        self.assertEqual(
            str(private.exception), "private artifact payload is invalid"
        )


class CapabilityImplementationBindingTests(unittest.TestCase):
    def test_non_callable_implementation_is_rejected_without_content(self) -> None:
        valid = RecordingImplementation()
        for implementation in (object(), NonCallableImplementation()):
            bindings = tuple(
                (
                    CapabilityRef(capability_id, "1.0.0"),
                    implementation if capability_id == "dci.research" else valid,
                )
                for capability_id in (
                    "dci.evaluation",
                    "dci.research",
                    "protocol.observability",
                )
            )

            with (
                self.subTest(implementation=type(implementation).__name__),
                self.assertRaises(CapabilityExecutionError) as raised,
            ):
                validate_implementation_bindings(resolve_plan(), bindings)

            self.assertNotIn(
                "SECRET-NON-CALLABLE-IMPLEMENTATION", str(raised.exception)
            )

    def test_exact_bindings_require_every_executable_capability(self) -> None:
        implementation = RecordingImplementation()

        with self.assertRaises(CapabilityExecutionError):
            validate_implementation_bindings(
                resolve_plan(),
                ((CapabilityRef("dci.research", "1.0.0"), implementation),),
            )

    def test_duplicate_exact_bindings_fail_before_mapping_conversion(self) -> None:
        implementation = RecordingImplementation()
        binding = (CapabilityRef("dci.research", "1.0.0"), implementation)

        with self.assertRaises(CapabilityExecutionError):
            validate_implementation_bindings(resolve_plan(), (binding, binding))

    def test_complete_exact_bindings_are_immutable_and_policy_is_declarative(self) -> None:
        implementation = RecordingImplementation()
        bindings = tuple(
            (CapabilityRef(capability_id, "1.0.0"), implementation)
            for capability_id in ("dci.evaluation", "dci.research", "protocol.observability")
        )

        resolved = validate_implementation_bindings(resolve_plan(), bindings)

        self.assertIsInstance(resolved, MappingProxyType)
        self.assertNotIn(CapabilityRef("policy.local-corpus", "1.0.0"), resolved)
        with self.assertRaises(TypeError):
            resolved[CapabilityRef("other", "1.0.0")] = implementation  # type: ignore[reportIndexIssue]

    def test_unknown_exact_binding_is_rejected(self) -> None:
        implementation = RecordingImplementation()
        bindings = tuple(
            (CapabilityRef(capability_id, "1.0.0"), implementation)
            for capability_id in (
                "dci.evaluation",
                "dci.research",
                "protocol.observability",
                "unknown.capability",
            )
        )

        with self.assertRaises(CapabilityExecutionError):
            validate_implementation_bindings(resolve_plan(), bindings)


class CapabilityExecutionValueTests(unittest.TestCase):
    def test_invocation_and_result_are_deeply_immutable(self) -> None:
        manifest = resolve_plan().capability_manifests[1]
        invocation = CapabilityInvocation(
            capability_ref=CapabilityRef("dci.research", "1.0.0"),
            manifest=manifest,
            run_id="capability-run-1",
            input_text="Read the corpus",
            upstream_events=({
                "type": "research.completed",
                "payload": {"nested": {"ok": True}},
            },),
            upstream_artifacts=({"media_type": "text/plain", "value": {"x": 1}},),
            host_events=({
                "type": "run.started",
                "payload": {"nested": {"ok": True}},
            },),
            host_artifacts=({
                "artifact_id": "host-input",
                "media_type": "text/plain",
                "value": {"nested": {"ok": True}},
            },),
            runtime=FixtureRuntime(),
            host_services={"service.example": object()},
        )
        result = CapabilityExecutionResult(
            events=({"type": "research.completed", "payload": {"ok": True}},),
            artifacts=({
                "artifact_id": "research-result",
                "media_type": "application/vnd.dci.research+json",
                "value": {"answer_artifact_uri": "final.txt"},
            },),
        )

        self.assertIsInstance(invocation.host_services, MappingProxyType)
        with self.assertRaises(TypeError):
            invocation.upstream_events[0]["payload"]["nested"]["ok"] = False  # type: ignore[reportIndexIssue]
        with self.assertRaises(TypeError):
            invocation.upstream_artifacts[0]["media_type"] = "changed"  # type: ignore[reportIndexIssue]
        with self.assertRaises(TypeError):
            invocation.host_events[0]["payload"]["nested"]["ok"] = False  # type: ignore[reportIndexIssue]
        with self.assertRaises(TypeError):
            invocation.host_artifacts[0]["value"]["nested"]["ok"] = False  # type: ignore[reportIndexIssue]
        with self.assertRaises(TypeError):
            result.events[0]["type"] = "changed"  # type: ignore[reportIndexIssue]
        with self.assertRaises(TypeError):
            result.artifacts[0]["value"]["answer_artifact_uri"] = "changed"  # type: ignore[reportIndexIssue]


class CapabilityResultValidationTests(unittest.TestCase):
    def manifest(self):
        return next(
            manifest
            for manifest in resolve_plan().capability_manifests
            if manifest["capability_id"] == "dci.research"
        )

    def test_declared_events_and_artifacts_are_accepted(self) -> None:
        validate_capability_result(
            self.manifest(),
            CapabilityExecutionResult(
                events=({"type": "research.completed", "payload": {}},),
                artifacts=({
                    "artifact_id": "research-result",
                    "media_type": "application/vnd.dci.research+json",
                    "value": {},
                },),
            ),
        )

    def test_declared_outputs_are_allowed_types_not_required_outputs(self) -> None:
        validate_capability_result(
            self.manifest(),
            CapabilityExecutionResult(events=(), artifacts=()),
        )

    def test_undeclared_or_malformed_outputs_are_rejected_without_content(self) -> None:
        sentinel = "SECRET-PACKAGE-OUTPUT"
        invalid = (
            CapabilityExecutionResult(events=({"type": sentinel, "payload": {}},), artifacts=()),
            CapabilityExecutionResult(
                events=(),
                artifacts=({
                    "artifact_id": "result",
                    "media_type": sentinel,
                    "value": {},
                },),
            ),
            CapabilityExecutionResult(
                events=(),
                artifacts=(
                    {"artifact_id": "same", "media_type": "application/vnd.dci.research+json", "value": {}},
                    {"artifact_id": "same", "media_type": "application/vnd.dci.research+json", "value": {}},
                ),
            ),
            CapabilityExecutionResult(
                events=({"type": "research.completed", "payload": sentinel},),
                artifacts=(),
            ),
            CapabilityExecutionResult(
                events=(),
                artifacts=({
                    "artifact_id": "",
                    "media_type": "application/vnd.dci.research+json",
                    "value": {},
                },),
            ),
            CapabilityExecutionResult(
                events=(),
                artifacts=({
                    "artifact_id": "result",
                    "media_type": "application/vnd.dci.research+json",
                    "value": sentinel,
                },),
            ),
        )
        for result in invalid:
            with self.subTest(result=result):
                with self.assertRaises(CapabilityExecutionError) as raised:
                    validate_capability_result(self.manifest(), result)
                self.assertNotIn(sentinel, str(raised.exception))


class ComposedEvidenceTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_filters_and_deeply_freezes_upstream_and_host_evidence(
        self,
    ) -> None:
        producer = ResultImplementation(producer_result())
        consumer = ResultImplementation(
            CapabilityExecutionResult(events=(), artifacts=())
        )

        await run_composed_application(
            evidence_plan(),
            implementations=(
                (CapabilityRef("evidence.producer", "1.0.0"), producer),
                (CapabilityRef("evidence.consumer", "1.0.0"), consumer),
            ),
            runtime=FixtureRuntime(),
            run_id="evidence-run",
            input_text="Transport evidence",
            host_services={},
            host_events=host_events(),
            host_artifacts=host_artifacts(),
        )

        invocation = consumer.invocations[0]
        self.assertEqual(
            tuple(event["type"] for event in invocation.upstream_events),
            ("producer.completed",),
        )
        self.assertEqual(
            tuple(item["artifact_id"] for item in invocation.upstream_artifacts),
            ("producer-artifact",),
        )
        self.assertEqual(
            tuple(event["type"] for event in invocation.host_events),
            ("host.ready",),
        )
        self.assertEqual(
            tuple(item["artifact_id"] for item in invocation.host_artifacts),
            ("host-input",),
        )
        with self.assertRaises(TypeError):
            invocation.upstream_events[0]["payload"]["nested"]["status"] = "changed"  # type: ignore[reportIndexIssue]
        with self.assertRaises(TypeError):
            invocation.upstream_artifacts[0]["value"]["nested"]["status"] = "changed"  # type: ignore[reportIndexIssue]
        with self.assertRaises(TypeError):
            invocation.host_events[0]["payload"]["nested"]["status"] = "changed"  # type: ignore[reportIndexIssue]
        with self.assertRaises(TypeError):
            invocation.host_artifacts[0]["value"]["nested"]["status"] = "changed"  # type: ignore[reportIndexIssue]

    async def test_runner_snapshots_all_host_evidence_once_before_capability_work(
        self,
    ) -> None:
        caller_event = {
            "type": "host.ready",
            "payload": {"nested": {"status": "ready"}},
        }
        caller_artifact = {
            "artifact_id": "host-input",
            "media_type": "application/vnd.host-input+json",
            "value": {"nested": {"status": "ready"}},
        }
        producer = MutatingImplementation(
            producer_result(),
            event=caller_event,
            artifact=caller_artifact,
        )
        consumer = ResultImplementation(
            CapabilityExecutionResult(events=(), artifacts=())
        )

        await run_composed_application(
            evidence_plan(),
            implementations=(
                (CapabilityRef("evidence.producer", "1.0.0"), producer),
                (CapabilityRef("evidence.consumer", "1.0.0"), consumer),
            ),
            runtime=FixtureRuntime(),
            run_id="evidence-run",
            input_text="Transport evidence",
            host_services={},
            host_events=(caller_event,),
            host_artifacts=(caller_artifact,),
        )

        invocation = consumer.invocations[0]
        self.assertEqual(
            invocation.host_events[0],
            {
                "type": "host.ready",
                "payload": {"nested": {"status": "ready"}},
            },
        )
        self.assertEqual(
            invocation.host_artifacts[0],
            {
                "artifact_id": "host-input",
                "media_type": "application/vnd.host-input+json",
                "value": {"nested": {"status": "ready"}},
            },
        )

    async def test_host_evidence_must_exactly_match_assembly_declarations(
        self,
    ) -> None:
        cases = (
            ((), host_artifacts()),
            (
                (
                    *host_events(),
                    {"type": "host.extra", "payload": {}},
                ),
                host_artifacts(),
            ),
            (host_events(), ()),
            (
                host_events(),
                (
                    *host_artifacts(),
                    {
                        "artifact_id": "host-extra",
                        "media_type": "application/vnd.host-extra+json",
                        "value": {},
                    },
                ),
            ),
        )
        for actual_events, actual_artifacts in cases:
            with self.subTest(
                events=actual_events,
                artifacts=actual_artifacts,
            ):
                producer = ResultImplementation(producer_result())
                consumer = ResultImplementation(
                    CapabilityExecutionResult(events=(), artifacts=())
                )
                with self.assertRaises(ApplicationRunError):
                    await run_composed_application(
                        evidence_plan(),
                        implementations=(
                            (
                                CapabilityRef("evidence.producer", "1.0.0"),
                                producer,
                            ),
                            (
                                CapabilityRef("evidence.consumer", "1.0.0"),
                                consumer,
                            ),
                        ),
                        runtime=FixtureRuntime(),
                        run_id="evidence-run",
                        input_text="Transport evidence",
                        host_services={},
                        host_events=actual_events,
                        host_artifacts=actual_artifacts,
                    )
                self.assertEqual(producer.invocations, [])
                self.assertEqual(consumer.invocations, [])

    async def test_malformed_host_evidence_fails_closed_without_capability_work(
        self,
    ) -> None:
        sentinel = "SECRET-HOST-EVIDENCE"
        cases = (
            (
                "event-extra-field",
                ({
                    "type": "host.ready",
                    "payload": {},
                    "extra": sentinel,
                },),
                host_artifacts(),
            ),
            (
                "event-payload-not-mapping",
                ({"type": "host.ready", "payload": sentinel},),
                host_artifacts(),
            ),
            (
                "artifact-extra-field",
                host_events(),
                ({
                    "artifact_id": "host-input",
                    "media_type": "application/vnd.host-input+json",
                    "value": {},
                    "extra": sentinel,
                },),
            ),
            (
                "artifact-value-not-mapping",
                host_events(),
                ({
                    "artifact_id": "host-input",
                    "media_type": "application/vnd.host-input+json",
                    "value": sentinel,
                },),
            ),
            (
                "duplicate-artifact-id",
                host_events(),
                (
                    *host_artifacts(),
                    {
                        "artifact_id": "host-input",
                        "media_type": "application/vnd.host-input+json",
                        "value": {"sentinel": sentinel},
                    },
                ),
            ),
        )
        for name, actual_events, actual_artifacts in cases:
            with self.subTest(name=name):
                producer = ResultImplementation(producer_result())
                consumer = ResultImplementation(
                    CapabilityExecutionResult(events=(), artifacts=())
                )
                with self.assertRaises(ApplicationRunError) as raised:
                    await run_composed_application(
                        evidence_plan(),
                        implementations=(
                            (
                                CapabilityRef("evidence.producer", "1.0.0"),
                                producer,
                            ),
                            (
                                CapabilityRef("evidence.consumer", "1.0.0"),
                                consumer,
                            ),
                        ),
                        runtime=FixtureRuntime(),
                        run_id="evidence-run",
                        input_text="Transport evidence",
                        host_services={},
                        host_events=actual_events,
                        host_artifacts=actual_artifacts,
                    )
                self.assertNotIn(sentinel, str(raised.exception))
                self.assertEqual(producer.invocations, [])
                self.assertEqual(consumer.invocations, [])

    async def test_artifact_ids_are_unique_across_all_capability_results(self) -> None:
        producer = ResultImplementation(producer_result())
        consumer = ResultImplementation(
            CapabilityExecutionResult(
                events=(),
                artifacts=({
                    "artifact_id": "producer-artifact",
                    "media_type": "application/vnd.consumer+json",
                    "value": {},
                },),
            )
        )

        with self.assertRaises(ApplicationRunError):
            await run_composed_application(
                evidence_plan(),
                implementations=(
                    (CapabilityRef("evidence.producer", "1.0.0"), producer),
                    (CapabilityRef("evidence.consumer", "1.0.0"), consumer),
                ),
                runtime=FixtureRuntime(),
                run_id="evidence-run",
                input_text="Transport evidence",
                host_services={},
                host_events=host_events(),
                host_artifacts=host_artifacts(),
            )


if __name__ == "__main__":
    unittest.main()
