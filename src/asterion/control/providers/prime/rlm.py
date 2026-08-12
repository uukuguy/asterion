"""Prime-specific pre-delivery binding for native RLM child admission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from asterion.control.authority import action_proposal_digest
from asterion.control.host import ControlEvent
from asterion.control.manager import ProviderOwnedActionTerminal
from asterion.control.execution import ActionExecutionReceipt
from asterion.control.authority import BudgetUsage
from asterion.control.providers.prime.client import (
    RlmAdmissionBinding,
    RlmLifecycleObservation,
    RlmMessageAdmissionBinding,
)
from asterion.control.rlm import RlmChildBinding, RlmChildService, RlmError, RlmMessageBinding


@dataclass(frozen=True)
class PrimeRlmHostComponents:
    """The exact Prime-native RLM services a ControlHost must receive together."""

    children: RlmChildService
    admission_preparer: "PrimeRlmAdmissionPreparer"
    action_lifecycle: "PrimeRlmActionLifecycle"


class _PrimeRlmClient(Protocol):
    async def rlm_binding(self, action_id: str) -> RlmAdmissionBinding: ...

    async def rlm_lifecycle(self) -> tuple[RlmLifecycleObservation, ...]: ...

    async def rlm_message_binding(
        self, action_id: str
    ) -> RlmMessageAdmissionBinding: ...


def build_prime_rlm_host_components(
    *,
    client: _PrimeRlmClient,
    authority: object,
    parent_session_id: str,
    private_root: Path | None = None,
) -> PrimeRlmHostComponents:
    """Construct one linked admission ledger and provider-owned lifecycle."""

    from asterion.control.authority import AuthorityEnvelope

    if not isinstance(authority, AuthorityEnvelope):
        raise RlmError("Prime RLM authority is invalid")
    children = RlmChildService(authority, private_root=private_root)
    preparer = PrimeRlmAdmissionPreparer(
        client=client, children=children, parent_session_id=parent_session_id
    )
    return PrimeRlmHostComponents(
        children=children,
        admission_preparer=preparer,
        action_lifecycle=PrimeRlmActionLifecycle(preparer),
    )


class PrimeRlmAdmissionPreparer:
    """Persist the exact Prime-native child binding before admitted delivery."""

    def __init__(
        self,
        *,
        client: _PrimeRlmClient,
        children: RlmChildService,
        parent_session_id: str,
    ) -> None:
        if (
            not callable(getattr(client, "rlm_binding", None))
            or not isinstance(children, RlmChildService)
            or not isinstance(parent_session_id, str)
        ):
            raise RlmError("Prime RLM admission preparer is invalid")
        self._client = client
        self._children = children
        self._parent_session_id = parent_session_id
        self._messages: dict[str, RlmMessageBinding] = {}

    async def prepare(self, proposal: ControlEvent) -> None:
        if not isinstance(proposal, ControlEvent) or proposal.type != "action.proposed":
            raise RlmError("Prime RLM proposal is invalid")
        payload = proposal.payload
        action_id = payload.get("action_id")
        target = payload.get("target")
        if payload.get("kind") == "child.message":
            await self._prepare_message(proposal)
            return
        if (
            payload.get("kind") != "child.spawn"
            or payload.get("authority_revision") is None
            or not isinstance(action_id, str)
            or not isinstance(target, Mapping)
            or target.get("kind") != "child"
            or not isinstance(target.get("child_id"), str)
        ):
            raise RlmError("Prime RLM proposal is invalid")
        gateway = await self._client.rlm_binding(action_id)
        self._validate_gateway_binding(proposal, gateway)
        self._children.admit(
            RlmChildBinding(
                action_id=gateway.action_id,
                child_id=gateway.child_id,
                parent_session_id=self._parent_session_id,
                authority_revision=gateway.authority_revision,
                proposal_digest=action_proposal_digest(proposal),
                depth=gateway.depth,
                model_selector_digest=gateway.model_selector_digest,
            )
        )

    async def _prepare_message(self, proposal: ControlEvent) -> None:
        payload = proposal.payload
        action_id = payload.get("action_id")
        target = payload.get("target")
        if (
            payload.get("authority_revision") is None
            or not isinstance(action_id, str)
            or not isinstance(target, Mapping)
            or target.get("kind") != "child"
            or not isinstance(target.get("child_id"), str)
        ):
            raise RlmError("Prime RLM proposal is invalid")
        gateway = await self._client.rlm_message_binding(action_id)
        if (
            gateway.action_id != action_id
            or gateway.recipient_id != target["child_id"]
            or gateway.authority_revision != payload["authority_revision"]
        ):
            raise RlmError("Prime RLM binding conflicts")
        binding = RlmMessageBinding(
            gateway.message_id,
            gateway.sender_id,
            gateway.recipient_id,
            gateway.body_digest,
            gateway.authority_revision,
        )
        self._children.admit_message(binding)
        existing = self._messages.get(action_id)
        if existing is not None and existing != binding:
            raise RlmError("Prime RLM binding conflicts")
        self._messages[action_id] = binding

    async def reconcile_lifecycle(self) -> None:
        """Apply the complete Gateway lifecycle history monotonically."""

        observations = await self._client.rlm_lifecycle()
        if not isinstance(observations, tuple):
            raise RlmError("Prime RLM lifecycle is invalid")
        for observation in observations:
            if not isinstance(observation, RlmLifecycleObservation):
                raise RlmError("Prime RLM lifecycle is invalid")
            binding = self._children.binding(observation.child_id)
            current = self._children.status(observation.child_id)
            if observation.type == "rlm.child.started":
                if current.status == "admitted":
                    assert observation.native_identity_digest is not None
                    self._children.record_started(
                        binding, native_identity=observation.native_identity_digest
                    )
                elif current.status not in {"started", "completed", "failed", "cancelled"}:
                    raise RlmError("Prime RLM lifecycle conflicts")
                continue
            if current.status == "started":
                assert observation.status is not None
                self._children.record_terminal(binding, status=observation.status)
            elif current.status != observation.status:
                raise RlmError("Prime RLM lifecycle conflicts")

    def owns(self, proposal: ControlEvent) -> bool:
        """True only after this exact action has a durable native-child binding."""

        if not isinstance(proposal, ControlEvent) or proposal.type != "action.proposed":
            return False
        payload = proposal.payload
        action_id = payload.get("action_id")
        target = payload.get("target")
        if payload.get("kind") == "child.message":
            return action_id in self._messages
        if (
            payload.get("kind") != "child.spawn"
            or not isinstance(action_id, str)
            or not isinstance(target, Mapping)
            or not isinstance(target.get("child_id"), str)
        ):
            return False
        try:
            binding = self._children.binding(target["child_id"])
        except RlmError:
            return False
        return binding.action_id == action_id

    @staticmethod
    def _validate_gateway_binding(
        proposal: ControlEvent, gateway: RlmAdmissionBinding
    ) -> None:
        payload = proposal.payload
        action_id = payload.get("action_id")
        target = payload.get("target")
        if (
            not isinstance(action_id, str)
            or not isinstance(target, Mapping)
            or not isinstance(target.get("child_id"), str)
            or gateway.action_id != action_id
            or gateway.child_id != target["child_id"]
            or gateway.authority_revision != payload["authority_revision"]
        ):
            raise RlmError("Prime RLM binding conflicts")


class PrimeRlmActionLifecycle:
    """Expose Prime-native RLM actions as provider-owned asynchronous work."""

    def __init__(self, preparer: PrimeRlmAdmissionPreparer) -> None:
        if not isinstance(preparer, PrimeRlmAdmissionPreparer):
            raise RlmError("Prime RLM lifecycle is invalid")
        self._preparer = preparer
        self._delivered: set[str] = set()

    def owns(self, proposal: ControlEvent) -> bool:
        return self._preparer.owns(proposal)

    @property
    def active_child_count(self) -> int:
        return sum(
            status.status in {"admitted", "started"}
            for status in self._preparer._children.public_registry()
        )

    async def reconcile(self) -> tuple[ProviderOwnedActionTerminal, ...]:
        await self._preparer.reconcile_lifecycle()
        terminals: list[ProviderOwnedActionTerminal] = []
        for status in self._preparer._children.public_registry():
            if status.status not in {"completed", "failed", "cancelled"}:
                continue
            binding = self._preparer._children.binding(status.child_id)
            if binding.action_id in self._delivered:
                continue
            if status.status == "completed":
                # The native terminal does not yet expose a verified private
                # result reference. Do not fabricate a successful projection.
                terminal = ProviderOwnedActionTerminal(
                    binding.action_id,
                    "uncertain",
                )
            else:
                terminal = ProviderOwnedActionTerminal(binding.action_id, status.status)
            self._delivered.add(binding.action_id)
            terminals.append(terminal)
        for action_id, binding in tuple(self._preparer._messages.items()):
            if action_id in self._delivered:
                continue
            gateway = await self._preparer._client.rlm_message_binding(action_id)
            if (
                gateway.message_id != binding.message_id
                or gateway.sender_id != binding.sender_id
                or gateway.recipient_id != binding.recipient_id
                or gateway.authority_revision != binding.authority_revision
                or gateway.body_digest != binding.body_digest
            ):
                raise RlmError("Prime RLM binding conflicts")
            if not gateway.delivered:
                continue
            self._preparer._children.record_message_delivered(binding)
            receipt = ActionExecutionReceipt(
                action_id=action_id,
                receipt_ref="rlm-message-" + sha256(action_id.encode()).hexdigest(),
                usage=BudgetUsage.zero(),
            )
            self._delivered.add(action_id)
            terminals.append(ProviderOwnedActionTerminal(action_id, "succeeded", receipt))
        return tuple(terminals)
