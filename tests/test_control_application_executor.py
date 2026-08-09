from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
    InstalledAssembly,
)
from asterion.assembly.protocol import resolve_assembly
from asterion.capabilities.catalog import CapabilityCatalog, CapabilityRef, CatalogEntry
from asterion.capabilities.execution import (
    CapabilityImplementationBinding,
    CapabilityExecutionResult,
    CapabilityInvocation,
)
from asterion.capability_packages import CapabilityPackageRef, InstalledCapabilityPackage
from asterion.control.application_executor import ApplicationActionExecutor
from asterion.control.authority import BudgetUsage
from asterion.control.execution import ActionExecutionFailure
from asterion.control.host import ControlEvent
from asterion.control.private_store import (
    MAX_PRIVATE_TEXT_BYTES,
    PrivateResultPublication,
)
from asterion.control.system import ApplicationPortfolioEntry, AgentSystemPlan
from asterion.control.factory import ControlPlaneFactory, ControlPlaneFactoryBinding
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryBinding, RuntimeFactoryRegistry
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest


TRACE_CAPABILITY = CapabilityRef("trace.capability", "1.0.0")
SENTINEL = "SENTINEL_SECRET"


class HostileInnerRuntimeOptions(Mapping[str, str]):
    def __getitem__(self, key: str) -> str:
        del key
        raise RuntimeError(f"{SENTINEL} leaked")

    def __iter__(self) -> Iterator[str]:
        return iter(("token",))

    def __len__(self) -> int:
        return 1


class MutableSignal:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled


class RecordingResolver:
    def __init__(self, values: Mapping[str, str], audit: list[str]) -> None:
        self.values = dict(values)
        self.audit = audit
        self.requests: list[tuple[str, int]] = []

    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        self.audit.append("content.resolve")
        self.requests.append((reference, max_bytes))
        try:
            value = self.values[reference]
        except KeyError:
            raise KeyError(f"{SENTINEL} missing") from None
        if len(value.encode("utf-8")) > max_bytes:
            raise ValueError(f"{SENTINEL} oversized")
        return value


class RecordingResultStore:
    def __init__(self, audit: list[str]) -> None:
        self.audit = audit
        self.publication: Mapping[str, object] | None = None
        self.raw_result: object | None = None
        self.fail = False
        self.override: object | None = None

    def publish_application_result(
        self,
        *,
        action_id: str,
        provider_id: str,
        application_id: str,
        version: str,
        runtime_id: str,
        idempotency_key: str,
        run_id: str,
        result: object,
    ) -> PrivateResultPublication:
        self.audit.append("result.publish")
        if self.fail:
            raise RuntimeError(f"{SENTINEL} publication")
        self.publication = {
            "action_id": action_id,
            "provider_id": provider_id,
            "application_id": application_id,
            "version": version,
            "runtime_id": runtime_id,
            "idempotency_key": idempotency_key,
            "run_id": run_id,
        }
        self.raw_result = result
        if self.override is not None:
            return cast(PrivateResultPublication, self.override)
        return PrivateResultPublication(
            action_id=action_id,
            receipt_ref=f"receipt-{action_id}",
            artifact_ids=("artifact-1",),
            media_types=("application/json",),
        )


class RecordingRuntime:
    manifest = RuntimeManifest(runtime_id="fake.runtime", capabilities=())

    def __init__(self, audit: list[str]) -> None:
        self.audit = audit
        self.requests: list[RunRequest] = []

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del signal
        self.audit.append("runtime.run")
        self.requests.append(request)
        if False:
            yield RunEvent("", 0, "", {})


class UsageImplementation:
    def __init__(
        self,
        audit: list[str],
        *,
        input_tokens: int = 100,
        output_tokens: int = 55,
        artifact_id: str = "artifact-1",
        extra_artifact_id: str | None = None,
        usage_extra_field: bool = False,
        cancel_during: bool = False,
        fail: bool = False,
    ) -> None:
        self.audit = audit
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.artifact_id = artifact_id
        self.extra_artifact_id = extra_artifact_id
        self.usage_extra_field = usage_extra_field
        self.cancel_during = cancel_during
        self.fail = fail
        self.calls: list[CapabilityInvocation] = []

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        self.audit.append("implementation.execute")
        self.calls.append(invocation)
        if self.cancel_during:
            signal = cast(MutableSignal, invocation.signal)
            signal.cancelled = True
            raise RuntimeError(f"{SENTINEL} cancelled")
        if self.fail:
            raise RuntimeError(f"{SENTINEL} provider")
        usage_payload = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }
        if self.usage_extra_field:
            usage_payload["private"] = SENTINEL  # type: ignore[assignment]
        artifacts = [
            {
                "artifact_id": self.artifact_id,
                "media_type": "application/json",
                "value": {"secret": SENTINEL},
            },
        ]
        if self.extra_artifact_id is not None:
            artifacts.append(
                {
                    "artifact_id": self.extra_artifact_id,
                    "media_type": "application/json",
                    "value": {"secret": SENTINEL},
                }
            )
        return CapabilityExecutionResult(
            events=(
                {
                    "type": "usage.reported",
                    "payload": usage_payload,
                },
            ),
            artifacts=tuple(artifacts),
        )


class TaskCancelledImplementation:
    def __init__(self, audit: list[str]) -> None:
        self.audit = audit

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        del invocation
        self.audit.append("implementation.execute")
        raise asyncio.CancelledError


def _proposal(**payload_changes: object) -> ControlEvent:
    payload: dict[str, object] = {
        "action_id": "action-1",
        "authority_revision": 1,
        "idempotency_key": "idempotency-1",
        "kind": "application.invoke",
        "target": {
            "kind": "application",
            "provider_id": "example.provider",
            "application_id": "alpha",
            "version": "1.0.0",
            "runtime_id": "fake.runtime",
        },
        "input_ref": "content-ref-1",
        "expected_artifacts": (),
        "budget": {
            "controller_tokens": 0,
            "application_tokens": 200,
            "child_tokens": 0,
            "aggregate_tokens": 200,
            "cost_micros": 0,
            "deadline_ms": 1000,
        },
        "causal_parent_ids": (),
    }
    payload.update(payload_changes)
    return ControlEvent(
        event_id="event-1",
        session_id="session-1",
        generation=1,
        sequence=1,
        emitted_at="2026-08-10T03:00:00Z",
        type="action.proposed",
        payload=payload,
    )


def _assembly(
    root: Path,
    implementation: UsageImplementation,
    *,
    runtime_id: str = "fake.runtime",
    runtime_manifest: Mapping[str, object] | None = None,
):
    runtime_manifest = runtime_manifest or {
        "protocol": "asterion.agent-runtime/v1",
        "runtime_id": runtime_id,
        "capabilities": [],
    }
    manifest = {
        "protocol": "asterion.capability/v1",
        "capability_id": TRACE_CAPABILITY.capability_id,
        "version": TRACE_CAPABILITY.version,
        "kind": "capability",
        "provides_capabilities": [],
        "requires_capabilities": [],
        "requires_policies": [],
        "emits_events": ["usage.reported"],
        "consumes_events": [],
        "produces_artifacts": ["application/json"],
        "consumes_artifacts": [],
    }
    catalog = CapabilityCatalog(
        entries=(
            CatalogEntry(
                ref=TRACE_CAPABILITY,
                source=root / "trace-capability.json",
                manifest=manifest,
            ),
        )
    )
    plan = resolve_assembly(
        {
            "protocol": "asterion.application-assembly/v1",
            "application_id": "alpha",
            "version": "1.0.0",
            "runtime_id": runtime_id,
            "capability_packages": [{"package_id": "trace", "version": "1.0.0"}],
            "capabilities": [
                {
                    "capability_id": TRACE_CAPABILITY.capability_id,
                    "version": TRACE_CAPABILITY.version,
                }
            ],
            "host_capabilities": ["secret.service"],
            "host_policies": [],
            "host_events": [],
            "host_artifacts": [],
        },
        catalog=catalog,
        runtime_manifest=runtime_manifest,
    )
    assembly_path = root / "alpha.json"
    assembly_path.write_text("{}")
    package = InstalledCapabilityPackage(
        package_ref=CapabilityPackageRef("trace", "1.0.0"),
        payload_sha256="0" * 64,
        source_id="trace-source",
        source_kind="local-directory",
        catalog_roots=(),
        benchmark_suite_paths=(),
        implementations=(
            CapabilityImplementationBinding(TRACE_CAPABILITY, implementation),
        ),
        benchmark_bindings=(),
    )
    installed_assembly = InstalledAssembly(
        runtime_id=runtime_id,
        path=assembly_path,
        plan=plan,
    )
    application = InstalledApplication(
        application_id="alpha",
        version="1.0.0",
        assembly_paths=(assembly_path,),
        capability_packages=(package.package_ref,),
        runtime_ids=(runtime_id,),
        installed_packages=(package,),
        assemblies=(installed_assembly,),
    )
    provider = InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="example.provider",
        resource_root=root,
        applications=(application,),
    )
    return provider, application, installed_assembly


def _control_binding() -> ControlPlaneFactoryBinding:
    return ControlPlaneFactoryBinding(
        control_plane_id="fake.control",
        version="1.0.0",
        commands=(
            "action.resolve",
            "checkpoint.request",
            "input.submit",
            "session.attach",
            "session.cancel",
            "session.create",
            "session.pause",
            "session.resume",
        ),
        events=(
            "action.proposed",
            "budget.reported",
            "checkpoint.created",
            "fault.raised",
            "goal.updated",
            "session.budget-limited",
            "session.cancelled",
            "session.completed",
            "session.created",
            "session.failed",
            "session.paused",
            "session.recovery-required",
            "session.running",
        ),
        capabilities=("action-proposals",),
        continuation_media_type="application/vnd.asterion.control-capsule",
        checkpoint_version="1.0.0",
        compatibility_ids=("asterion.agent-control/v1",),
        factory=cast(ControlPlaneFactory, lambda context: object()),
    )


def _executor(
    root: Path,
    *,
    audit: list[str] | None = None,
    implementation: UsageImplementation | None = None,
    content: RecordingResolver | None = None,
    result_store: RecordingResultStore | None = None,
    host_services: Mapping[str, object] | None = None,
    runtime_factories: RuntimeFactoryRegistry | None = None,
    runtime_options: Mapping[tuple[str, str, str, str], Mapping[str, str]] | None = None,
    provider_override: InstalledApplicationProvider | None = None,
    runtime_id: str = "fake.runtime",
    runtime_manifest: Mapping[str, object] | None = None,
):
    audit = [] if audit is None else audit
    implementation = implementation or UsageImplementation(audit)
    provider, application, assembly = _assembly(
        root,
        implementation,
        runtime_id=runtime_id,
        runtime_manifest=runtime_manifest,
    )
    plan = AgentSystemPlan(
        system_id="research.system",
        version="1.0.0",
        control_binding=_control_binding(),
        portfolio=(
            ApplicationPortfolioEntry(
                provider_id=provider.provider_id,
                application=application,
                assembly=assembly,
            ),
        ),
        policies=(),
        host_capabilities=("secret.service",),
        control_capabilities=("action-proposals",),
    )

    def runtime_factory(context: object) -> RecordingRuntime:
        audit.append("runtime.factory")
        rendered = repr(context)
        assert "SENTINEL" not in rendered
        return RecordingRuntime(audit)

    factories = runtime_factories or RuntimeFactoryRegistry(
        (
            RuntimeFactoryBinding(
                runtime_id="fake.runtime",
                capabilities=(),
                factory=runtime_factory,
            ),
        )
    )
    resolver = content or RecordingResolver({"content-ref-1": f"private {SENTINEL}"}, audit)
    results = result_store or RecordingResultStore(audit)
    executor = ApplicationActionExecutor(
        plan=plan,
        providers=(provider_override or provider,),
        runtime_factories=factories,
        runtime_options=runtime_options
        if runtime_options is not None
        else {
            (
                provider.provider_id,
                application.application_id,
                application.version,
                assembly.runtime_id,
            ): {}
        },
        content=resolver,
        results=results,
        host_services=host_services
        if host_services is not None
        else {"secret.service": {"value": SENTINEL}},
        pathlight=None,
    )
    return executor, resolver, results, implementation


class TestApplicationActionExecutor(unittest.IsolatedAsyncioTestCase):
    async def test_exact_portfolio_action_runs_once_and_returns_safe_receipt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []
            executor, resolver, results, implementation = _executor(
                Path(directory), audit=audit
            )

            receipt = await executor.execute(_proposal(), MutableSignal())

            self.assertEqual(receipt.action_id, "action-1")
            self.assertEqual(receipt.receipt_ref, "receipt-action-1")
            self.assertEqual(receipt.usage, BudgetUsage(0, 155, 0, 155, 0))
            self.assertEqual(receipt.artifact_ids, ("artifact-1",))
            self.assertEqual(receipt.media_types, ("application/json",))
            self.assertEqual(resolver.requests, [("content-ref-1", MAX_PRIVATE_TEXT_BYTES)])
            self.assertEqual(len(implementation.calls), 1)
            self.assertEqual(
                audit,
                [
                    "content.resolve",
                    "runtime.factory",
                    "implementation.execute",
                    "result.publish",
                ],
            )
            self.assertNotIn(SENTINEL, repr(receipt))
            rendered_publication = repr(results.publication)
            self.assertNotIn(SENTINEL, rendered_publication)
            self.assertIn(SENTINEL, repr(results.raw_result))
            publication = results.publication
            assert publication is not None
            self.assertIn("control-action-", str(publication["run_id"]))

    async def test_private_runtime_options_are_forwarded_by_exact_identity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []
            contexts: list[object] = []

            def runtime_factory(context: object) -> RecordingRuntime:
                audit.append("runtime.factory")
                contexts.append(context)
                self.assertNotIn(SENTINEL, repr(context))
                return RecordingRuntime(audit)

            factories = RuntimeFactoryRegistry(
                (
                    RuntimeFactoryBinding(
                        runtime_id="fake.runtime",
                        capabilities=(),
                        factory=runtime_factory,
                    ),
                )
            )
            executor, _, _, _ = _executor(
                Path(directory),
                audit=audit,
                runtime_factories=factories,
                runtime_options={
                    (
                        "example.provider",
                        "alpha",
                        "1.0.0",
                        "fake.runtime",
                    ): {
                        "private-token": SENTINEL,
                        "mode": "operator-owned",
                    }
                },
            )

            receipt = await executor.execute(_proposal(), MutableSignal())

            self.assertEqual(receipt.receipt_ref, "receipt-action-1")
            self.assertEqual(len(contexts), 1)
            context = contexts[0]
            options = cast(Mapping[str, str], getattr(context, "options"))
            self.assertEqual(
                options["private-token"],
                SENTINEL,
            )
            self.assertEqual(options["mode"], "operator-owned")
            self.assertNotIn(SENTINEL, repr(receipt))

    def test_runtime_options_are_required_exact_private_plan_configuration(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unknown_identity = ("example.provider", "alpha", "1.0.0", "other.runtime")
            cases: tuple[object, ...] = (
                {},
                {
                    ("example.provider", "alpha", "1.0.0", "fake.runtime"): {},
                    unknown_identity: {},
                },
                {
                    ("example.provider", "alpha", "1.0.0", "fake.runtime"): {
                        "token": cast(str, object())
                    },
                },
                {
                    ("example.provider", "alpha", "1.0.0", "fake.runtime"): {
                        cast(str, object()): "value"
                    },
                },
                {
                    ("example.provider", "alpha", "1.0.0"): {},
                },
                {
                    (
                        "example.provider",
                        "alpha",
                        "1.0.0",
                        "fake.runtime",
                    ): HostileInnerRuntimeOptions(),
                },
            )
            for runtime_options in cases:
                with self.subTest(runtime_options=repr(runtime_options)):
                    with self.assertRaises(ValueError) as raised:
                        _executor(
                            root,
                            audit=[],
                            runtime_options=cast(
                                Mapping[tuple[str, str, str, str], Mapping[str, str]],
                                runtime_options,
                            ),
                        )
                    self.assertNotIn(SENTINEL, str(raised.exception))

    async def test_default_pi_factory_receives_private_options_without_provider_contact(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            cwd = root / "cwd"
            cwd.mkdir()
            audit: list[str] = []
            pi_manifest = default_runtime_factory_registry().select(
                "pi.reference"
            ).manifest.to_mapping()
            executor, _, _, _ = _executor(
                root,
                audit=audit,
                runtime_factories=default_runtime_factory_registry(),
                runtime_options={
                    (
                        "example.provider",
                        "alpha",
                        "1.0.0",
                        "pi.reference",
                    ): {
                        "command": json.dumps(
                            [str(Path(sys.executable).resolve()), "-u", "-c", "pass"],
                            separators=(",", ":"),
                        ),
                        "cwd": str(cwd),
                        "environment": json.dumps(
                            {"SENTINEL_ENV": SENTINEL},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "evidence_root": str(root / "pi-evidence"),
                        "max_turns": "1",
                        "tools": "read,grep",
                    }
                },
                runtime_id="pi.reference",
                runtime_manifest=pi_manifest,
            )

            receipt = await executor.execute(
                _proposal(
                    target={
                        "kind": "application",
                        "provider_id": "example.provider",
                        "application_id": "alpha",
                        "version": "1.0.0",
                        "runtime_id": "pi.reference",
                    }
                ),
                MutableSignal(),
            )

            self.assertEqual(receipt.receipt_ref, "receipt-action-1")
            self.assertEqual(
                audit, ["content.resolve", "implementation.execute", "result.publish"]
            )
            self.assertNotIn(SENTINEL, repr(receipt))

    async def test_expected_artifacts_are_validated_only_by_control_protocol_shape(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executor, _, _, _ = _executor(Path(directory), audit=[])

            receipt = await executor.execute(
                _proposal(expected_artifacts=("report.alpha",)),
                MutableSignal(),
            )

            self.assertEqual(receipt.artifact_ids, ("artifact-1",))

    async def test_rejects_all_exact_identity_mismatches_before_runtime_contact(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cases = (
                ("provider_id", "other.provider"),
                ("application_id", "zeta"),
                ("version", "2.0.0"),
                ("runtime_id", "other.runtime"),
            )
            for field, value in cases:
                with self.subTest(field=field):
                    audit: list[str] = []
                    executor, _, _, _ = _executor(Path(directory), audit=audit)
                    target = dict(cast(Mapping[str, object], _proposal().payload["target"]))
                    target[field] = value
                    with self.assertRaises(ActionExecutionFailure) as raised:
                        await executor.execute(_proposal(target=target), MutableSignal())
                    self.assertEqual(raised.exception.status, "failed")
                    self.assertEqual(raised.exception.reason_code, "target-mismatch")
                    self.assertEqual(audit, [])
                    self.assertNotIn(SENTINEL, repr(raised.exception))

    async def test_rejects_non_event_and_hostile_cancellation_state_safely(
        self,
    ) -> None:
        class HostileSignal:
            @property
            def cancelled(self) -> bool:
                raise RuntimeError(SENTINEL)

        with tempfile.TemporaryDirectory() as directory:
            executor, _, _, _ = _executor(Path(directory), audit=[])
            with self.assertRaises(ActionExecutionFailure) as malformed:
                await executor.execute(cast(ControlEvent, object()), MutableSignal())
            self.assertEqual(malformed.exception.status, "failed")
            self.assertEqual(malformed.exception.reason_code, "invalid-proposal")

            with self.assertRaises(ActionExecutionFailure) as hostile:
                await executor.execute(_proposal(), cast(MutableSignal, HostileSignal()))
            self.assertEqual(hostile.exception.status, "failed")
            self.assertEqual(
                hostile.exception.reason_code, "cancellation-state-unavailable"
            )
            self.assertNotIn(SENTINEL, repr(hostile.exception))

    async def test_rejects_missing_and_oversized_content_before_runtime_contact(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for values in ({}, {"content-ref-1": "x" * (MAX_PRIVATE_TEXT_BYTES + 1)}):
                with self.subTest(missing=not values):
                    audit: list[str] = []
                    executor, _, _, _ = _executor(
                        Path(directory),
                        audit=audit,
                        content=RecordingResolver(values, audit),
                    )
                    with self.assertRaises(ActionExecutionFailure) as raised:
                        await executor.execute(_proposal(), MutableSignal())
                    self.assertEqual(raised.exception.status, "failed")
                    self.assertEqual(raised.exception.reason_code, "private-input-unavailable")
                    self.assertEqual(audit, ["content.resolve"])
                    self.assertNotIn(SENTINEL, str(raised.exception))

    async def test_rejects_missing_runtime_binding_at_construction(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cases = (
                (
                    "missing-binding",
                    RuntimeFactoryRegistry(()),
                    None,
                ),
                (
                    "missing-capability",
                    RuntimeFactoryRegistry(
                        (
                            RuntimeFactoryBinding(
                                runtime_id="fake.runtime",
                                capabilities=(),
                                factory=lambda context: RecordingRuntime([]),
                            ),
                        )
                    ),
                    {
                        "protocol": "asterion.agent-runtime/v1",
                        "runtime_id": "fake.runtime",
                        "capabilities": ["filesystem.read"],
                    },
                ),
            )
            for name, factories, runtime_manifest in cases:
                with self.subTest(name=name):
                    with self.assertRaises(ValueError):
                        _executor(
                            Path(directory),
                            audit=[],
                            runtime_factories=factories,
                            runtime_manifest=runtime_manifest,
                        )

    async def test_rejects_missing_host_service_before_runtime_contact(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []
            executor, _, _, _ = _executor(
                Path(directory),
                audit=audit,
                host_services={},
            )
            with self.assertRaises(ActionExecutionFailure) as raised:
                await executor.execute(_proposal(), MutableSignal())
            self.assertEqual(raised.exception.status, "failed")
            self.assertEqual(raised.exception.reason_code, "host-service-unavailable")
            self.assertEqual(audit, [])

    async def test_cancellation_before_and_during_execution_have_closed_semantics(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []
            executor, _, _, _ = _executor(Path(directory), audit=audit)
            with self.assertRaises(ActionExecutionFailure) as before:
                await executor.execute(_proposal(), MutableSignal(cancelled=True))
            self.assertEqual(before.exception.status, "cancelled")
            self.assertEqual(audit, [])

        with tempfile.TemporaryDirectory() as directory:
            audit = []
            implementation = UsageImplementation(audit, cancel_during=True)
            executor, _, _, _ = _executor(
                Path(directory), audit=audit, implementation=implementation
            )
            with self.assertRaises(ActionExecutionFailure) as during:
                await executor.execute(_proposal(), MutableSignal())
            self.assertEqual(during.exception.status, "uncertain")
            self.assertEqual(during.exception.receipt_ref, None)
            self.assertIn("implementation.execute", audit)

        with tempfile.TemporaryDirectory() as directory:
            audit = []
            executor, _, _, _ = _executor(
                Path(directory),
                audit=audit,
                implementation=cast(UsageImplementation, TaskCancelledImplementation(audit)),
            )
            with self.assertRaises(ActionExecutionFailure) as task_cancelled:
                await executor.execute(_proposal(), MutableSignal())
            self.assertEqual(task_cancelled.exception.status, "uncertain")
            self.assertIsNone(task_cancelled.exception.receipt_ref)

    async def test_runtime_factory_call_failure_has_unknown_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []

            def fail_factory(context: object) -> RecordingRuntime:
                del context
                audit.append("runtime.factory")
                raise RuntimeError(f"{SENTINEL} runtime")

            factories = RuntimeFactoryRegistry(
                (
                    RuntimeFactoryBinding(
                        runtime_id="fake.runtime",
                        capabilities=(),
                        factory=fail_factory,
                    ),
                )
            )
            executor, _, _, _ = _executor(
                Path(directory), audit=audit, runtime_factories=factories
            )
            with self.assertRaises(ActionExecutionFailure) as raised:
                await executor.execute(_proposal(), MutableSignal())
            self.assertEqual(raised.exception.status, "uncertain")
            self.assertEqual(raised.exception.reason_code, "runtime-progress-unknown")
            self.assertIsNone(raised.exception.receipt_ref)
            self.assertEqual(audit, ["content.resolve", "runtime.factory"])
            self.assertNotIn(SENTINEL, repr(raised.exception))

    async def test_unknown_provider_progress_is_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []
            implementation = UsageImplementation(audit, fail=True)
            executor, _, _, _ = _executor(
                Path(directory), audit=audit, implementation=implementation
            )

            with self.assertRaises(ActionExecutionFailure) as raised:
                await executor.execute(_proposal(), MutableSignal())

            self.assertEqual(raised.exception.status, "uncertain")
            self.assertEqual(raised.exception.reason_code, "application-progress-unknown")
            self.assertIsNone(raised.exception.receipt_ref)
            self.assertIn("implementation.execute", audit)
            self.assertNotIn(SENTINEL, str(raised.exception))

    async def test_duplicate_artifact_usage_overrun_and_publication_failure_are_uncertain(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for name, implementation, proposal, configure_store in (
                (
                    "duplicate",
                    UsageImplementation([], artifact_id="bad-artifact"),
                    _proposal(),
                    None,
                ),
                (
                    "overrun",
                    UsageImplementation([], input_tokens=201, output_tokens=0),
                    _proposal(),
                    None,
                ),
                (
                    "usage-extra",
                    UsageImplementation([], usage_extra_field=True),
                    _proposal(),
                    None,
                ),
                (
                    "publication",
                    UsageImplementation([]),
                    _proposal(),
                    "fail",
                ),
            ):
                with self.subTest(name=name):
                    audit: list[str] = []
                    implementation.audit = audit
                    store = RecordingResultStore(audit)
                    if configure_store == "fail":
                        store.fail = True
                    if name == "duplicate":
                        store.override = {
                            "action_id": "action-1",
                            "receipt_ref": "receipt-action-1",
                            "artifact_ids": ("artifact-1", "artifact-1"),
                            "media_types": ("application/json",),
                        }
                    executor, _, _, _ = _executor(
                        Path(directory),
                        audit=audit,
                        implementation=implementation,
                        result_store=store,
                    )
                    with self.assertRaises(ActionExecutionFailure) as raised:
                        await executor.execute(proposal, MutableSignal())
                    self.assertEqual(raised.exception.status, "uncertain")
                    self.assertIsNone(raised.exception.receipt_ref)
                    self.assertNotIn(SENTINEL, repr(raised.exception))

    async def test_distinct_artifacts_may_share_one_media_type_projection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []
            implementation = UsageImplementation(
                audit, artifact_id="artifact-1", extra_artifact_id="artifact-2"
            )
            store = RecordingResultStore(audit)
            store.override = PrivateResultPublication(
                action_id="action-1",
                receipt_ref="receipt-action-1",
                artifact_ids=("artifact-1", "artifact-2"),
                media_types=("application/json",),
            )
            executor, _, _, _ = _executor(
                Path(directory),
                audit=audit,
                implementation=implementation,
                result_store=store,
            )

            receipt = await executor.execute(_proposal(), MutableSignal())

            self.assertEqual(receipt.artifact_ids, ("artifact-1", "artifact-2"))
            self.assertEqual(receipt.media_types, ("application/json",))

    async def test_result_store_public_projection_must_match_action_and_artifacts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cases = (
                PrivateResultPublication(
                    action_id="other-action",
                    receipt_ref="receipt-action-1",
                    artifact_ids=("artifact-1",),
                    media_types=("application/json",),
                ),
                PrivateResultPublication(
                    action_id="action-1",
                    receipt_ref="receipt-action-1",
                    artifact_ids=("artifact-2",),
                    media_types=("application/json",),
                ),
                {
                    "action_id": "action-1",
                    "receipt_ref": "receipt-action-1",
                    "artifact_ids": ("artifact-1",),
                    "media_types": ("application/json",),
                    "private": SENTINEL,
                },
            )
            for publication in cases:
                with self.subTest(publication=publication):
                    audit: list[str] = []
                    store = RecordingResultStore(audit)
                    store.override = publication
                    executor, _, _, _ = _executor(
                        Path(directory), audit=audit, result_store=store
                    )
                    with self.assertRaises(ActionExecutionFailure) as raised:
                        await executor.execute(_proposal(), MutableSignal())
                    self.assertEqual(raised.exception.status, "uncertain")

    async def test_provider_argument_must_contain_exact_application_snapshot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []
            implementation = UsageImplementation(audit)
            provider, application, assembly = _assembly(Path(directory), implementation)
            copied_provider = replace(
                provider,
                applications=(
                    replace(
                        application,
                        assemblies=(replace(assembly),),
                    ),
                ),
            )
            executor, _, _, _ = _executor(
                Path(directory),
                audit=audit,
                implementation=implementation,
                provider_override=copied_provider,
            )

            with self.assertRaises(ActionExecutionFailure) as raised:
                await executor.execute(_proposal(), MutableSignal())

            self.assertEqual(raised.exception.status, "failed")
            self.assertEqual(raised.exception.reason_code, "target-mismatch")
            self.assertEqual(audit, [])

    async def test_public_receipts_and_failures_redact_sentinel_and_are_immutable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []
            executor, _, _, _ = _executor(Path(directory), audit=audit)
            receipt = await executor.execute(_proposal(), MutableSignal())

            with self.assertRaises(AttributeError):
                receipt.action_id = "changed"  # type: ignore[misc]
            self.assertNotIn(SENTINEL, repr(receipt))

            target = dict(cast(Mapping[str, object], _proposal().payload["target"]))
            target["application_id"] = "zeta"
            with self.assertRaises(ActionExecutionFailure) as raised:
                await executor.execute(_proposal(target=target), MutableSignal())
            self.assertNotIn(SENTINEL, repr(raised.exception))
            self.assertNotIn(SENTINEL, str(raised.exception))

    async def test_provider_free_operation_does_not_contact_provider_or_expose_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit: list[str] = []
            executor, _, _, _ = _executor(Path(directory), audit=audit)
            receipt = await executor.execute(_proposal(), MutableSignal())

            self.assertEqual(receipt.receipt_ref, "receipt-action-1")
            self.assertNotIn(directory, repr(receipt))
            self.assertEqual(audit.count("implementation.execute"), 1)


if __name__ == "__main__":
    unittest.main()
