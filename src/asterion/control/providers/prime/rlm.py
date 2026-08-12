"""Prime-specific pre-delivery binding for native RLM child admission."""

from __future__ import annotations

from collections.abc import Mapping

from asterion.control.authority import action_proposal_digest
from asterion.control.host import ControlEvent
from asterion.control.providers.prime.client import (
    PrimeControlPlaneClient,
    RlmAdmissionBinding,
    RlmLifecycleObservation,
)
from asterion.control.rlm import RlmChildBinding, RlmChildService, RlmError


class PrimeRlmAdmissionPreparer:
    """Persist the exact Prime-native child binding before admitted delivery."""

    def __init__(
        self,
        *,
        client: PrimeControlPlaneClient,
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

    async def prepare(self, proposal: ControlEvent) -> None:
        if not isinstance(proposal, ControlEvent) or proposal.type != "action.proposed":
            raise RlmError("Prime RLM proposal is invalid")
        payload = proposal.payload
        action_id = payload.get("action_id")
        target = payload.get("target")
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
                child_id=gateway.child_id,
                parent_session_id=self._parent_session_id,
                authority_revision=gateway.authority_revision,
                proposal_digest=action_proposal_digest(proposal),
                depth=gateway.depth,
                model_selector_digest=gateway.model_selector_digest,
            )
        )

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
