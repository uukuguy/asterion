"""Execute exact application action proposals through resolved assemblies."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Protocol

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
    InstalledAssembly,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages import CapabilityPackageRef
from asterion.control.authority import BudgetRequest, BudgetUsage
from asterion.control.execution import (
    ActionExecutionFailure,
    ActionExecutionReceipt,
)
from asterion.control.host import ControlEvent
from asterion.control.private_store import (
    MAX_PRIVATE_TEXT_BYTES,
    PrivateContentResolver,
    PrivateResultPublication,
    PrivateResultStore,
    validate_private_result_publication,
)
from asterion.control.system import AgentSystemPlan, ApplicationPortfolioEntry
from asterion.pathlight.recorder import (
    NOOP_PATHLIGHT_RECORDER,
    PathlightRecorder,
)
from asterion.protocol_ordering import is_sorted_unique_scalar_strings
from asterion.runner.application import ApplicationRunResult
from asterion.runner.composed import run_composed_application
from asterion.runtime.factory import (
    RuntimeFactoryBinding,
    RuntimeFactoryContext,
    RuntimeFactoryError,
    RuntimeFactoryRegistry,
)
from asterion.runtime.host import CancellationSignal

ApplicationIdentity = tuple[str, str, str, str]


class ChildActionService(Protocol):
    """Execute exact child lifecycle actions without discovery."""

    async def spawn(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt: ...

    async def message(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt: ...

    async def cancel(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt: ...


class SystemActionService(Protocol):
    """Execute exact control-system actions through the selected provider."""

    async def execute(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt: ...


class ApplicationActionExecutor:
    """ActionExecutor for one preflight-resolved application portfolio.

    Runtime bindings are snapshotted at construction. This preserves the
    already-selected factory boundary: execution can invoke an exact factory,
    but it cannot reselect or discover a different runtime binding.
    """

    def __init__(
        self,
        *,
        plan: AgentSystemPlan,
        providers: Iterable[InstalledApplicationProvider],
        runtime_factories: RuntimeFactoryRegistry,
        runtime_options: Mapping[ApplicationIdentity, Mapping[str, str]],
        content: PrivateContentResolver,
        results: PrivateResultStore,
        host_services: Mapping[str, object],
        pathlight: PathlightRecorder | None = None,
        child_service: ChildActionService | None = None,
        system_service: SystemActionService | None = None,
    ) -> None:
        if (
            not isinstance(plan, AgentSystemPlan)
            or not isinstance(runtime_factories, RuntimeFactoryRegistry)
            or not callable(getattr(content, "resolve_text", None))
            or not callable(getattr(results, "publish_application_result", None))
            or not isinstance(host_services, Mapping)
            or not _valid_child_action_service(child_service)
            or not _valid_system_action_service(system_service)
        ):
            raise ValueError("application action executor is invalid")
        self._plan = plan
        self._providers = _index_providers(providers)
        self._runtime_bindings = _snapshot_runtime_bindings(
            plan, runtime_factories
        )
        self._runtime_options = _freeze_runtime_options(plan, runtime_options)
        self._content = content
        self._results = results
        self._host_services = MappingProxyType(dict(host_services))
        self._pathlight = pathlight
        self._child_service = child_service
        self._system_service = system_service

    async def execute(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt:
        if self._is_system_action(proposal):
            if self._system_service is None:
                raise _failed(proposal, "system-service-unavailable")
            try:
                receipt = await self._system_service.execute(proposal, signal)
            except ActionExecutionFailure:
                raise
            except Exception:
                raise ActionExecutionFailure(
                    "uncertain", "system-progress-unknown", None
                ) from None
            if type(receipt) is not ActionExecutionReceipt:
                raise ActionExecutionFailure(
                    "uncertain", "system-progress-unknown", None
                )
            return receipt
        child_action = self._child_action(proposal)
        if child_action is not None:
            if self._child_service is None:
                raise _failed(proposal, "child-service-unavailable")
            try:
                method = getattr(self._child_service, child_action)
                receipt = await method(proposal, signal)
            except ActionExecutionFailure:
                raise
            except Exception:
                raise ActionExecutionFailure(
                    "uncertain", "child-progress-unknown", None
                ) from None
            if type(receipt) is not ActionExecutionReceipt:
                raise ActionExecutionFailure("uncertain", "child-progress-unknown", None)
            return receipt
        _raise_if_cancelled(proposal, signal)
        target, identity, entry = self._resolve_entry(proposal)
        if entry is None:
            raise _failed(proposal, "target-mismatch")
        if not _provider_contains_entry(self._providers, entry):
            raise _failed(proposal, "target-mismatch")
        budget = _budget(proposal)
        missing_service = _missing_host_service(entry.assembly, self._host_services)
        if missing_service:
            raise _failed(proposal, "host-service-unavailable")

        runtime_binding = self._runtime_bindings[identity]
        _raise_if_cancelled(proposal, signal)

        input_text = _resolve_input(self._content, proposal)
        _raise_if_cancelled(proposal, signal)

        run_id = _run_id(proposal)
        try:
            runtime = runtime_binding.factory(
                RuntimeFactoryContext(
                    provider_id=entry.provider_id,
                    application_id=entry.application_id,
                    application_version=entry.version,
                    runtime_id=entry.runtime_id,
                    assembly_path=entry.assembly.path,
                    options=self._runtime_options[identity],
                    host_services=self._host_services,
                    pathlight=self._pathlight or NOOP_PATHLIGHT_RECORDER,
                )
            )
        except Exception:
            raise ActionExecutionFailure(
                "uncertain", "runtime-progress-unknown", None
            ) from None

        try:
            if runtime.manifest.runtime_id != entry.runtime_id:
                raise ValueError
        except Exception:
            raise ActionExecutionFailure(
                "uncertain", "runtime-progress-unknown", None
            ) from None

        try:
            result = await run_composed_application(
                entry.assembly.plan,
                implementations=entry.application.implementations,
                implementation_packages=_implementation_packages(entry.application),
                runtime=runtime,
                run_id=run_id,
                input_text=input_text,
                host_services=self._host_services,
                signal=signal,
                pathlight=self._pathlight,
            )
        except asyncio.CancelledError:
            raise ActionExecutionFailure(
                "uncertain", "application-progress-unknown", None
            ) from None
        except Exception:
            raise ActionExecutionFailure(
                "uncertain", "application-progress-unknown", None
            ) from None

        usage = _usage_from_events(result, budget)
        artifact_ids, media_types = _artifact_projection(result)
        publication = _publish(
            self._results,
            proposal=proposal,
            target=target,
            run_id=run_id,
            result=result,
        )
        if (
            publication.action_id != proposal.payload["action_id"]
            or publication.artifact_ids != artifact_ids
            or publication.media_types != media_types
        ):
            raise ActionExecutionFailure(
                "uncertain", "result-publication-invalid", None
            )
        return ActionExecutionReceipt(
            action_id=str(proposal.payload["action_id"]),
            receipt_ref=publication.receipt_ref,
            usage=usage,
            artifact_ids=publication.artifact_ids,
            media_types=publication.media_types,
        )

    def _resolve_entry(
        self, proposal: ControlEvent
    ) -> tuple[Mapping[str, object], ApplicationIdentity, ApplicationPortfolioEntry | None]:
        try:
            if not isinstance(proposal, ControlEvent):
                raise TypeError
            if proposal.type != "action.proposed":
                raise KeyError
            payload = proposal.payload
            if payload["kind"] != "application.invoke":
                raise KeyError
            target = payload["target"]
            if not isinstance(target, Mapping) or target.get("kind") != "application":
                raise KeyError
            identity = (
                str(target["provider_id"]),
                str(target["application_id"]),
                str(target["version"]),
                str(target["runtime_id"]),
            )
        except (KeyError, TypeError, ValueError):
            raise _failed(proposal, "invalid-proposal") from None
        return target, identity, self._plan.portfolio_entry(*identity)

    @staticmethod
    def _is_system_action(proposal: object) -> bool:
        return (
            isinstance(proposal, ControlEvent)
            and proposal.type == "action.proposed"
            and proposal.payload.get("kind")
            in {"checkpoint.create", "goal.complete", "goal.fail"}
        )

    @staticmethod
    def _child_action(proposal: object) -> str | None:
        if not isinstance(proposal, ControlEvent) or proposal.type != "action.proposed":
            return None
        kind = proposal.payload.get("kind")
        if not isinstance(kind, str) or not kind.startswith("child."):
            return None
        target = proposal.payload.get("target")
        if (
            not isinstance(target, Mapping)
            or set(target) != {"kind", "child_id"}
            or target.get("kind") != "child"
            or not isinstance(target.get("child_id"), str)
        ):
            raise _failed(proposal, "child-target-mismatch")
        methods = {
            "child.spawn": "spawn",
            "child.message": "message",
            "child.cancel": "cancel",
        }
        try:
            return methods[kind]
        except KeyError:
            raise _failed(proposal, "child-target-mismatch") from None


def _index_providers(
    providers: Iterable[InstalledApplicationProvider],
) -> Mapping[str, InstalledApplicationProvider]:
    try:
        values = tuple(providers)
    except TypeError:
        raise ValueError("application action providers are invalid") from None
    indexed: dict[str, InstalledApplicationProvider] = {}
    for provider in values:
        if (
            not isinstance(provider, InstalledApplicationProvider)
            or provider.protocol != APPLICATION_PROVIDER_PROTOCOL
            or provider.provider_id in indexed
        ):
            raise ValueError("application action providers are invalid")
        indexed[provider.provider_id] = provider
    return MappingProxyType(indexed)


def _valid_child_action_service(value: object) -> bool:
    if value is None:
        return True
    try:
        return all(
            callable(getattr(value, method, None))
            for method in ("spawn", "message", "cancel")
        )
    except Exception:
        return False


def _valid_system_action_service(value: object) -> bool:
    if value is None:
        return True
    try:
        return callable(getattr(value, "execute", None))
    except Exception:
        return False


def _provider_contains_entry(
    providers: Mapping[str, InstalledApplicationProvider],
    entry: ApplicationPortfolioEntry,
) -> bool:
    provider = providers.get(entry.provider_id)
    if provider is None:
        return False
    for application in provider.applications:
        if application is entry.application:
            return any(
                assembly is entry.assembly
                for assembly in application.assemblies
            )
    return False


def _snapshot_runtime_bindings(
    plan: AgentSystemPlan,
    runtime_factories: RuntimeFactoryRegistry,
) -> Mapping[ApplicationIdentity, RuntimeFactoryBinding]:
    values: dict[ApplicationIdentity, RuntimeFactoryBinding] = {}
    for identity, entry in plan.portfolio_by_identity.items():
        try:
            binding = runtime_factories.select(entry.runtime_id)
        except RuntimeFactoryError:
            raise ValueError("application runtime factories are invalid") from None
        if (
            binding.runtime_id != entry.runtime_id
            or any(
                capability not in binding.capabilities
                for capability in entry.assembly.plan.runtime_capabilities
            )
        ):
            raise ValueError("application runtime factories are invalid")
        values[identity] = binding
    return MappingProxyType(values)


def _freeze_runtime_options(
    plan: AgentSystemPlan,
    runtime_options: Mapping[ApplicationIdentity, Mapping[str, str]],
) -> Mapping[ApplicationIdentity, Mapping[str, str]]:
    if not isinstance(runtime_options, Mapping):
        raise ValueError("application runtime options are invalid")
    expected = set(plan.portfolio_by_identity)
    try:
        actual = set(runtime_options)
    except Exception:
        raise ValueError("application runtime options are invalid") from None
    if actual != expected:
        raise ValueError("application runtime options are invalid")

    values: dict[ApplicationIdentity, Mapping[str, str]] = {}
    for identity in expected:
        if not _is_application_identity(identity):
            raise ValueError("application runtime options are invalid")
        try:
            raw_options = runtime_options[identity]
            if not isinstance(raw_options, Mapping):
                raise ValueError
            frozen_options: dict[str, str] = {}
            for key, value in raw_options.items():
                if type(key) is not str or type(value) is not str:
                    raise ValueError
                frozen_options[key] = value
        except Exception:
            raise ValueError("application runtime options are invalid") from None
        values[identity] = MappingProxyType(frozen_options)
    return MappingProxyType(values)


def _is_application_identity(value: object) -> bool:
    return (
        type(value) is tuple
        and len(value) == 4
        and all(type(item) is str for item in value)
    )


def _budget(proposal: ControlEvent) -> BudgetRequest:
    try:
        raw_budget = proposal.payload["budget"]
        if not isinstance(raw_budget, Mapping):
            raise TypeError
        return BudgetRequest.from_mapping(raw_budget)
    except Exception:
        raise _failed(proposal, "invalid-proposal") from None


def _missing_host_service(
    assembly: InstalledAssembly, host_services: Mapping[str, object]
) -> bool:
    return any(service not in host_services for service in assembly.plan.host_capabilities)


def _resolve_input(content: PrivateContentResolver, proposal: ControlEvent) -> str:
    try:
        reference = proposal.payload["input_ref"]
        if not isinstance(reference, str):
            raise TypeError
        input_text = content.resolve_text(reference, max_bytes=MAX_PRIVATE_TEXT_BYTES)
        if not isinstance(input_text, str):
            raise TypeError
        if len(input_text.encode("utf-8")) > MAX_PRIVATE_TEXT_BYTES:
            raise ValueError
        return input_text
    except Exception:
        raise _failed(proposal, "private-input-unavailable") from None


def _implementation_packages(
    application: InstalledApplication,
) -> Mapping[CapabilityRef, CapabilityPackageRef]:
    values = {
        binding.capability_ref: package.package_ref
        for package in application.installed_packages
        for binding in package.implementations
    }
    return MappingProxyType(values)


def _usage_from_events(
    result: ApplicationRunResult, reservation: BudgetRequest
) -> BudgetUsage:
    application_tokens = 0
    try:
        for event in result.events:
            if event["type"] != "usage.reported":
                continue
            if set(event) != {"type", "payload"}:
                raise TypeError
            payload = event["payload"]
            if (
                not isinstance(payload, Mapping)
                or set(payload) != {"input_tokens", "output_tokens"}
            ):
                raise TypeError
            input_tokens = _nonnegative_int(payload["input_tokens"])
            output_tokens = _nonnegative_int(payload["output_tokens"])
            application_tokens += input_tokens + output_tokens
    except Exception:
        raise ActionExecutionFailure(
            "uncertain", "usage-report-invalid", None
        ) from None
    usage = BudgetUsage(
        controller_tokens=0,
        application_tokens=application_tokens,
        child_tokens=0,
        aggregate_tokens=application_tokens,
        cost_micros=0,
    )
    if (
        usage.application_tokens > reservation.application_tokens
        or usage.aggregate_tokens > reservation.aggregate_tokens
        or usage.cost_micros > reservation.cost_micros
    ):
        raise ActionExecutionFailure(
            "uncertain", "usage-reservation-exceeded", None
        )
    return usage


def _artifact_projection(
    result: ApplicationRunResult,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        artifact_ids = []
        media_types = []
        for artifact in result.artifacts:
            artifact_id = artifact["artifact_id"]
            media_type = artifact["media_type"]
            if not isinstance(artifact_id, str) or not isinstance(media_type, str):
                raise TypeError
            artifact_ids.append(artifact_id)
            media_types.append(media_type)
        artifact_id_projection = tuple(sorted(artifact_ids))
        media_type_projection = tuple(sorted(set(media_types)))
    except Exception:
        raise ActionExecutionFailure(
            "uncertain", "artifact-publication-invalid", None
        ) from None
    if not is_sorted_unique_scalar_strings(list(artifact_id_projection)):
        raise ActionExecutionFailure(
            "uncertain", "artifact-publication-invalid", None
        )
    return artifact_id_projection, media_type_projection


def _publish(
    results: PrivateResultStore,
    *,
    proposal: ControlEvent,
    target: Mapping[str, object],
    run_id: str,
    result: ApplicationRunResult,
) -> PrivateResultPublication:
    try:
        return validate_private_result_publication(
            results.publish_application_result(
                action_id=str(proposal.payload["action_id"]),
                provider_id=str(target["provider_id"]),
                application_id=str(target["application_id"]),
                version=str(target["version"]),
                runtime_id=str(target["runtime_id"]),
                idempotency_key=str(proposal.payload["idempotency_key"]),
                run_id=run_id,
                result=result,
            )
        )
    except Exception:
        raise ActionExecutionFailure(
            "uncertain", "result-publication-failed", None
        ) from None


def _failed(proposal: object, reason_code: str) -> ActionExecutionFailure:
    return ActionExecutionFailure(
        "failed",
        reason_code,
        _failure_receipt_ref(proposal, reason_code),
    )


def _failure_receipt_ref(proposal: object, reason_code: str) -> str:
    action_id = "unknown"
    try:
        if not isinstance(proposal, ControlEvent):
            raise TypeError
        candidate = proposal.payload["action_id"]
        if isinstance(candidate, str):
            action_id = candidate
    except Exception:
        pass
    digest = hashlib.sha256(f"{action_id}:{reason_code}".encode("utf-8")).hexdigest()
    return f"failure-{digest[:32]}"


def _run_id(proposal: ControlEvent) -> str:
    payload = proposal.payload
    encoded = json.dumps(
        {
            "action_id": payload["action_id"],
            "idempotency_key": payload["idempotency_key"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"control-action-{hashlib.sha256(encoded).hexdigest()[:32]}"


def _raise_if_cancelled(proposal: object, signal: CancellationSignal | None) -> None:
    if signal is None:
        return
    try:
        cancelled = signal.cancelled
    except Exception:
        raise _failed(proposal, "cancellation-state-unavailable") from None
    if not isinstance(cancelled, bool):
        raise _failed(proposal, "cancellation-state-unavailable")
    if cancelled:
        raise ActionExecutionFailure("cancelled", "cancelled", None)


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError
    return value
