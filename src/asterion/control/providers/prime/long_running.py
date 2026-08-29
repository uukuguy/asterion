"""Private Prime translation for host-issued long-running effects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from asterion.control.long_running import LongRunningIntent, LongRunningReceipt
from asterion.control.protocol import OPAQUE_ID


class PrimeLongRunningError(RuntimeError):
    """Raised when the selected Prime long-running boundary fails closed."""


@dataclass(frozen=True)
class PrimeLongRunningIpcReceipt:
    """Body-free durable result returned by the private Gateway IPC."""

    command_id: str
    command_digest: str
    status: Literal["succeeded", "failed", "uncertain"]

    def __post_init__(self) -> None:
        if (
            not _valid_id(self.command_id)
            or not _valid_digest(self.command_digest)
            or self.status not in {"succeeded", "failed", "uncertain"}
        ):
            raise PrimeLongRunningError("Prime long-running receipt is invalid")


@dataclass(frozen=True)
class PrimeLongRunningCommand:
    """One exact pinned daemon command bound to a host effect identity."""

    intent: LongRunningIntent
    command_type: Literal[
        "heartbeats_list",
        "heartbeat_get",
        "heartbeat_set",
        "heartbeat_update",
        "heartbeat_manage",
    ]
    active_session_id: str | None = None
    schedule: str | None = None
    prompt: str | None = field(default=None, repr=False)
    delivery_mode: Literal["steer", "followUp"] | None = None
    job_id: str | None = None
    action: Literal["pause", "resume", "cancel"] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.intent, LongRunningIntent):
            raise PrimeLongRunningError("Prime long-running command is invalid")
        try:
            validate_prime_long_running_mapping(self.to_mapping())
        except PrimeLongRunningError:
            raise
        except (TypeError, ValueError):
            raise PrimeLongRunningError(
                "Prime long-running command is invalid"
            ) from None

    @property
    def command_id(self) -> str:
        return self.intent.effect_id

    @classmethod
    def heartbeats_list(
        cls, intent: LongRunningIntent
    ) -> PrimeLongRunningCommand:
        return cls(intent, "heartbeats_list")

    @classmethod
    def heartbeat_get(
        cls, intent: LongRunningIntent, active_session_id: str
    ) -> PrimeLongRunningCommand:
        return cls(intent, "heartbeat_get", active_session_id=active_session_id)

    @classmethod
    def heartbeat_set(
        cls,
        intent: LongRunningIntent,
        *,
        active_session_id: str,
        schedule: str,
        prompt: str,
        delivery_mode: Literal["steer", "followUp"] | None = None,
    ) -> PrimeLongRunningCommand:
        return cls(
            intent,
            "heartbeat_set",
            active_session_id=active_session_id,
            schedule=schedule,
            prompt=prompt,
            delivery_mode=delivery_mode,
        )

    @classmethod
    def heartbeat_update(
        cls,
        intent: LongRunningIntent,
        active_session_id: str,
        action: Literal["pause", "resume", "cancel"],
    ) -> PrimeLongRunningCommand:
        return cls(
            intent,
            "heartbeat_update",
            active_session_id=active_session_id,
            action=action,
        )

    @classmethod
    def heartbeat_manage(
        cls,
        intent: LongRunningIntent,
        active_session_id: str,
        job_id: str,
        action: Literal["pause", "resume", "cancel"],
    ) -> PrimeLongRunningCommand:
        return cls(
            intent,
            "heartbeat_manage",
            active_session_id=active_session_id,
            job_id=job_id,
            action=action,
        )

    def to_mapping(self) -> Mapping[str, object]:
        if self.command_type == "heartbeats_list":
            return {"type": self.command_type}
        if self.command_type == "heartbeat_get":
            return {
                "type": self.command_type,
                "activeSessionId": self.active_session_id,
            }
        if self.command_type == "heartbeat_set":
            return {
                "type": self.command_type,
                "activeSessionId": self.active_session_id,
                "schedule": self.schedule,
                "prompt": self.prompt,
                **(
                    {}
                    if self.delivery_mode is None
                    else {"deliveryMode": self.delivery_mode}
                ),
            }
        if self.command_type == "heartbeat_update":
            return {
                "type": self.command_type,
                "activeSessionId": self.active_session_id,
                "action": self.action,
            }
        return {
            "type": self.command_type,
            "activeSessionId": self.active_session_id,
            "jobId": self.job_id,
            "action": self.action,
        }


class PrimeLongRunningClient(Protocol):
    async def execute_long_running(
        self, command_id: str, command: Mapping[str, object]
    ) -> PrimeLongRunningIpcReceipt:
        """Send one already-authorized exact command without retrying it."""
        ...


class PrimeLongRunningService:
    """Translate a host effect through the selected Prime provider once."""

    def __init__(self, client: PrimeLongRunningClient) -> None:
        if not hasattr(client, "execute_long_running"):
            raise PrimeLongRunningError("Prime long-running service is invalid")
        self._client = client

    async def apply(self, command: PrimeLongRunningCommand) -> LongRunningReceipt:
        if not isinstance(command, PrimeLongRunningCommand):
            raise PrimeLongRunningError("Prime long-running command is invalid")
        try:
            receipt = await self._client.execute_long_running(
                command.command_id,
                command.to_mapping(),
            )
        except (KeyError, TypeError, ValueError, RuntimeError):
            raise PrimeLongRunningError("Prime long-running operation failed") from None
        if (
            not isinstance(receipt, PrimeLongRunningIpcReceipt)
            or receipt.command_id != command.command_id
        ):
            raise PrimeLongRunningError("Prime long-running receipt is invalid")
        intent = command.intent
        return LongRunningReceipt(
            intent.effect_id,
            intent.source_id,
            intent.source_kind,
            intent.due_at_ms,
            receipt.status,
        )


def validate_prime_long_running_mapping(
    value: Mapping[str, object],
) -> Mapping[str, object]:
    """Rebuild one exact pinned heartbeat command without retaining aliases."""

    if not isinstance(value, Mapping) or not isinstance(value.get("type"), str):
        raise PrimeLongRunningError("Prime long-running command is invalid")
    command_type = value["type"]
    expected: set[str]
    if command_type == "heartbeats_list":
        expected = {"type"}
    elif command_type == "heartbeat_get":
        expected = {"type", "activeSessionId"}
    elif command_type == "heartbeat_set":
        expected = {"type", "activeSessionId", "schedule", "prompt"}
        if "deliveryMode" in value:
            expected.add("deliveryMode")
    elif command_type == "heartbeat_update":
        expected = {"type", "activeSessionId", "action"}
    elif command_type == "heartbeat_manage":
        expected = {"type", "activeSessionId", "jobId", "action"}
    else:
        raise PrimeLongRunningError("Prime long-running command is invalid")
    if set(value) != expected:
        raise PrimeLongRunningError("Prime long-running command is invalid")
    if command_type != "heartbeats_list" and not _valid_id(value["activeSessionId"]):
        raise PrimeLongRunningError("Prime long-running command is invalid")
    if command_type == "heartbeat_set" and (
        not _valid_text(value["schedule"])
        or not _valid_text(value["prompt"])
        or value.get("deliveryMode") not in {None, "steer", "followUp"}
    ):
        raise PrimeLongRunningError("Prime long-running command is invalid")
    if command_type in {"heartbeat_update", "heartbeat_manage"} and value.get(
        "action"
    ) not in {"pause", "resume", "cancel"}:
        raise PrimeLongRunningError("Prime long-running command is invalid")
    if command_type == "heartbeat_manage" and not _valid_id(value["jobId"]):
        raise PrimeLongRunningError("Prime long-running command is invalid")
    return dict(value)


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and OPAQUE_ID.fullmatch(value) is not None


def _valid_text(value: object) -> bool:
    return isinstance(value, str) and bool(value) and len(value.encode("utf-8")) <= 1024 * 1024


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
