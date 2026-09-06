"""Private, one-game P7 broker and deterministic replay verifier."""

from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
import secrets
from typing import Callable


class P7DevelopmentBrokerError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 development broker is unavailable")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _digest(value: object) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


def _observation(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != {
        "state",
        "levels_completed",
        "win_levels",
        "available_actions",
        "frame",
    }:
        raise P7DevelopmentBrokerError()
    state, completed, won, actions, frame = (
        value[k]
        for k in (
            "state",
            "levels_completed",
            "win_levels",
            "available_actions",
            "frame",
        )
    )
    if (
        type(state) is not str
        or type(completed) is not int
        or type(won) is not int
        or type(actions) is not list
        or any(type(x) is not int or not 1 <= x <= 7 for x in actions)
        or actions != sorted(set(actions))
    ):
        raise P7DevelopmentBrokerError()

    def grid(item: object) -> list[object]:
        if type(item) is not list:
            raise ValueError
        return [grid(x) if type(x) is list else x for x in item]

    try:
        normalized = grid(frame)

        def ints(item: object) -> bool:
            return (
                type(item) is int or type(item) is list and all(ints(x) for x in item)
            )

        if not ints(normalized):
            raise ValueError
    except ValueError:
        raise P7DevelopmentBrokerError() from None
    return {
        "state": state,
        "levels_completed": completed,
        "win_levels": won,
        "available_actions": actions,
        "frame": normalized,
    }


@dataclass(frozen=True, repr=False)
class P7BrokerSeal:
    transcript_sha256: str
    terminal_reason: str
    action_count: int

    def __repr__(self) -> str:
        return "P7BrokerSeal(redacted)"


class P7DevelopmentBroker:
    def __init__(self, *, engine: object, token: str | None = None) -> None:
        if not all(
            callable(getattr(engine, x, None)) for x in ("observe", "act", "status")
        ):
            raise P7DevelopmentBrokerError()
        self._engine, self._token, self._sequence, self._sealed = (
            engine,
            token or secrets.token_hex(32),
            0,
            False,
        )
        self._journal: list[dict[str, object]] = []
        self._status: bool | None = None

    @property
    def token(self) -> str:
        return self._token

    def request(self, request: object) -> dict[str, object]:
        if (
            type(request) is not dict
            or set(request) != {"token", "sequence", "method", "data"}
            or request["token"] != self._token
            or type(request["sequence"]) is not int
            or request["sequence"] != self._sequence + 1
            or request["method"] not in {"observe", "act", "status"}
            or self._sealed
        ):
            raise P7DevelopmentBrokerError()
        method, data = request["method"], request["data"]
        try:
            if method == "observe":
                if data != {} or self._sequence:
                    raise ValueError
                observation = _observation(self._engine.observe())
                self._journal.append({"observation": observation})
                result = {"observation": observation}
            elif method == "act":
                if (
                    type(data) is not dict
                    or set(data) != {"action_id", "data"}
                    or type(data["action_id"]) is not int
                    or data["action_id"] not in range(1, 8)
                    or data["data"] != {}
                    or self._status is not None
                    or len(self._journal) >= 5
                ):
                    raise ValueError
                available = self._journal[-1]["observation"]["available_actions"]
                if data["action_id"] not in available:
                    raise ValueError
                observation = _observation(self._engine.act(data["action_id"]))
                self._journal.append(
                    {"action_id": data["action_id"], "observation": observation}
                )
                result = {"observation": observation}
            else:
                if data != {} or self._status is not None or len(self._journal) < 2:
                    raise ValueError
                terminal = self._engine.status()
                if type(terminal) is not bool:
                    raise ValueError
                actions = len(self._journal) - 1
                if not terminal and actions != 4:
                    raise ValueError
                self._status = terminal
                self._sealed = True
                result = {"terminal": terminal, "terminal_reason": "engine-terminal" if terminal else "action-limit"}
            self._sequence += 1
            return result
        except P7DevelopmentBrokerError:
            raise
        except BaseException:
            raise P7DevelopmentBrokerError() from None

    def seal(self) -> P7BrokerSeal:
        if not self._sealed:
            raise P7DevelopmentBrokerError()
        if self._status is None:
            raise P7DevelopmentBrokerError()
        actions = sum("action_id" in row for row in self._journal)
        return P7BrokerSeal(
            _digest(self._journal),
            "engine-terminal" if self._status else "action-limit",
            actions,
        )

    def replay(self, factory: Callable[[], object]) -> dict[str, object]:
        sealed = self.seal()
        engine = None
        try:
            engine = factory()
            first = _observation(engine.observe())
            if not self._journal or first != self._journal[0]["observation"]:
                raise ValueError
            for row in self._journal[1:]:
                if _observation(engine.act(row["action_id"])) != row["observation"]:
                    raise ValueError
            terminal = engine.status()
            if type(terminal) is not bool or not (terminal or sealed.action_count == 4):
                raise ValueError
        except BaseException:
            raise P7DevelopmentBrokerError() from None
        finally:
            try:
                close = getattr(engine, "close", None)
                if callable(close):
                    close()
            except BaseException:
                pass
        return {
            "replay_sha256": _digest(self._journal),
            "terminal_reason": sealed.terminal_reason,
            "action_count": sealed.action_count,
        }


def p7_model_client_module_bytes() -> bytes:
    return b"# P7 model surface: observe(), act(action_id), status(); transport is host-owned.\n"


__all__ = (
    "P7BrokerSeal",
    "P7DevelopmentBroker",
    "P7DevelopmentBrokerError",
    "p7_model_client_module_bytes",
)
