"""Authenticated, bounded authority for one dynamic ARC level attempt."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import re
import secrets
from typing import Callable

from .p7_solving_score import official_p7_partial_score
from .p7_solving_workload import (
    P7_SOLVING_ACTION_CAP,
    P7_SOLVING_ARC_AGI_WHEEL_SHA256,
    P7_SOLVING_BATCH_CAP,
    P7_SOLVING_BASELINE_ACTIONS,
    P7_SOLVING_RESOURCE_SHA256,
)


class P7SolvingBrokerError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 solving broker is unavailable")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _digest(value: object) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


_SCORE = re.compile(r"(?:0|[1-9][0-9]?|100)\.[0-9]{6}\Z")


def _valid_grid(value: object) -> bool:
    if type(value) is not list or not value:
        return False
    for layer in value:
        if type(layer) is not list or not layer:
            return False
        widths = {len(row) for row in layer if type(row) is list}
        if (
            len(widths) != 1
            or len(widths) == 0
            or any(
                type(row) is not list
                or not row
                or any(type(pixel) is not int or not 0 <= pixel <= 255 for pixel in row)
                for row in layer
            )
        ):
            return False
    return True


def normalize_p7_observation(value: object) -> dict[str, object]:
    fields = {"available_actions", "frame", "levels_completed", "state", "win_levels"}
    if type(value) is not dict or set(value) != fields:
        raise P7SolvingBrokerError()
    available = value["available_actions"]
    if (
        type(value["state"]) is not str
        or not value["state"]
        or type(value["levels_completed"]) is not int
        or value["levels_completed"] < 0
        or type(value["win_levels"]) is not int
        or value["win_levels"] < 1
        or value["levels_completed"] > value["win_levels"]
        or type(available) is not list
        or available != sorted(set(available))
        or any(type(item) is not int or not 1 <= item <= 7 for item in available)
        or not _valid_grid(value["frame"])
    ):
        raise P7SolvingBrokerError()
    return deepcopy(value)


def normalize_p7_action(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != {"name", "data"}:
        raise P7SolvingBrokerError()
    name, data = value["name"], value["data"]
    if (
        type(name) is not str
        or name not in {"RESET", *(f"ACTION{i}" for i in range(1, 8))}
        or type(data) is not dict
    ):
        raise P7SolvingBrokerError()
    if name == "ACTION6":
        if set(data) != {"x", "y"} or any(
            type(data[key]) is not int or not 0 <= data[key] <= 63 for key in ("x", "y")
        ):
            raise P7SolvingBrokerError()
    elif data != {}:
        raise P7SolvingBrokerError()
    return deepcopy(value)


@dataclass(frozen=True, repr=False)
class P7SolvingSeal:
    transcript_sha256: str
    score_sha256: str
    score: str
    terminal_reason: str
    action_count: int
    levels_completed: int

    def __repr__(self) -> str:
        return "P7SolvingSeal(redacted)"


class P7SolvingBroker:
    """Journal each primitive and close on the first level transition."""

    def __init__(
        self,
        *,
        engine: object,
        token: str | None = None,
        resource_sha256: str = P7_SOLVING_RESOURCE_SHA256,
        arc_agi_wheel_sha256: str = P7_SOLVING_ARC_AGI_WHEEL_SHA256,
    ) -> None:
        if (
            not callable(getattr(engine, "observe", None))
            or not callable(getattr(engine, "act", None))
            or resource_sha256 != P7_SOLVING_RESOURCE_SHA256
            or arc_agi_wheel_sha256 != P7_SOLVING_ARC_AGI_WHEEL_SHA256
            or token is not None
            and (type(token) is not str or not token)
        ):
            raise P7SolvingBrokerError()
        try:
            initial = normalize_p7_observation(engine.observe())
        except BaseException:
            raise P7SolvingBrokerError() from None
        if initial["levels_completed"] != 0 or initial["win_levels"] != 7:
            raise P7SolvingBrokerError()
        self._engine = engine
        self._token = token or secrets.token_hex(32)
        self._resource_sha256 = resource_sha256
        self._wheel_sha256 = arc_agi_wheel_sha256
        self._sequence = 0
        self._initial_levels = initial["levels_completed"]
        self._last = initial
        self._journal: list[dict[str, object]] = [{"observation": initial}]
        self._terminal = "ACTIVE"
        self._terminal_reason = "active"

    @property
    def token(self) -> str:
        return self._token

    @property
    def action_count(self) -> int:
        return len(self._journal) - 1

    def _view(self) -> dict[str, object]:
        result = deepcopy(self._last)
        result.update(
            {
                "actions_remaining": P7_SOLVING_ACTION_CAP - self.action_count,
                "actions_taken": self.action_count,
                "terminal": self._terminal,
                "terminal_reason": self._terminal_reason,
            }
        )
        return result

    def request(self, request: object) -> dict[str, object]:
        if (
            type(request) is not dict
            or set(request) != {"data", "method", "sequence", "token"}
            or request["token"] != self._token
            or type(request["sequence"]) is not int
            or request["sequence"] != self._sequence + 1
            or request["method"] not in {"act", "observe", "status"}
        ):
            raise P7SolvingBrokerError()
        method, data = request["method"], request["data"]
        if method in {"observe", "status"}:
            if data != {}:
                raise P7SolvingBrokerError()
            self._sequence += 1
            return self._view()
        if (
            self._terminal != "ACTIVE"
            or type(data) is not dict
            or set(data) != {"actions"}
            or type(data["actions"]) is not list
            or not 1 <= len(data["actions"]) <= P7_SOLVING_BATCH_CAP
        ):
            raise P7SolvingBrokerError()
        try:
            actions = [normalize_p7_action(item) for item in data["actions"]]
        except BaseException:
            raise P7SolvingBrokerError() from None
        try:
            for action in actions:
                if self.action_count >= P7_SOLVING_ACTION_CAP:
                    raise ValueError
                action_number = (
                    None if action["name"] == "RESET" else int(str(action["name"])[6:])
                )
                if (
                    action_number is not None
                    and action_number not in self._last["available_actions"]
                ):
                    raise ValueError
                before = self._last["levels_completed"]
                win_levels = self._last["win_levels"]
                row = {"action": action}
                self._journal.append(row)
                after = normalize_p7_observation(self._engine.act(deepcopy(action)))
                row["observation"] = after
                if after["win_levels"] != win_levels:
                    raise ValueError
                self._last = after
                completed = after["levels_completed"] - before
                if (
                    completed not in (0, 1)
                    or after["levels_completed"] < self._initial_levels
                ):
                    self._terminal, self._terminal_reason = "ERROR", "engine-invalid"
                    raise ValueError
                if completed == 1:
                    self._terminal, self._terminal_reason = (
                        "LEVEL_SOLVED",
                        "level-completed",
                    )
                    break
                if self.action_count == P7_SOLVING_ACTION_CAP:
                    self._terminal, self._terminal_reason = "ACTION_CAP", "action-cap"
                    break
            self._sequence += 1
            return self._view()
        except BaseException:
            self._terminal, self._terminal_reason = "ERROR", "engine-invalid"
            raise P7SolvingBrokerError() from None

    def _score(self) -> str:
        if self._terminal != "LEVEL_SOLVED":
            return "0.000000"
        try:
            score = official_p7_partial_score(
                self.action_count,
                arc_agi_wheel_sha256=self._wheel_sha256,
                baseline_actions=P7_SOLVING_BASELINE_ACTIONS,
            )
            if type(score) is not str or _SCORE.fullmatch(score) is None:
                raise ValueError
            return score
        except BaseException:
            raise P7SolvingBrokerError() from None

    def seal(self) -> P7SolvingSeal:
        if self._terminal == "ACTIVE":
            raise P7SolvingBrokerError()
        score = self._score()
        return P7SolvingSeal(
            transcript_sha256=_digest(self._journal),
            score_sha256=_digest({"score": score}),
            score=score,
            terminal_reason=self._terminal_reason,
            action_count=self.action_count,
            levels_completed=self._last["levels_completed"] - self._initial_levels,
        )

    def presentation(self) -> dict[str, object]:
        seal = self.seal()
        return {
            "action_count": seal.action_count,
            "applied_actions": [deepcopy(row["action"]) for row in self._journal[1:]],
            "completion_grid": deepcopy(self._last["frame"]),
            "initial_grid": deepcopy(self._journal[0]["observation"]["frame"]),
            "levels_completed": seal.levels_completed,
            "score": seal.score,
            "terminal_reason": seal.terminal_reason,
        }

    def replay(
        self,
        factory: Callable[[], object],
        *,
        resource_sha256: str = P7_SOLVING_RESOURCE_SHA256,
        arc_agi_wheel_sha256: str = P7_SOLVING_ARC_AGI_WHEEL_SHA256,
    ) -> dict[str, object]:
        seal = self.seal()
        if (
            resource_sha256 != self._resource_sha256
            or arc_agi_wheel_sha256 != self._wheel_sha256
        ):
            raise P7SolvingBrokerError()
        engine = None
        try:
            engine = factory()
            current = normalize_p7_observation(engine.observe())
            if current != self._journal[0]["observation"]:
                raise ValueError
            initial_levels = current["levels_completed"]
            transitioned_at = None
            for index, row in enumerate(self._journal[1:], 1):
                before = current["levels_completed"]
                current = normalize_p7_observation(engine.act(deepcopy(row["action"])))
                if current != row["observation"]:
                    raise ValueError
                if current["levels_completed"] == before + 1:
                    transitioned_at = index
                elif current["levels_completed"] != before:
                    raise ValueError
            if (
                current != self._last
                or len(self._journal) - 1 != seal.action_count
                or current["levels_completed"] - initial_levels != seal.levels_completed
                or (transitioned_at == seal.action_count)
                != (seal.terminal_reason == "level-completed")
                or self._score() != seal.score
            ):
                raise ValueError
        except BaseException:
            raise P7SolvingBrokerError() from None
        finally:
            try:
                close = getattr(engine, "close", None)
                if callable(close):
                    close()
            except BaseException:
                pass
        return {
            "action_count": seal.action_count,
            "levels_completed": seal.levels_completed,
            "replay_sha256": seal.transcript_sha256,
            "score": seal.score,
            "score_sha256": seal.score_sha256,
            "terminal_reason": seal.terminal_reason,
        }


__all__ = (
    "P7SolvingBroker",
    "P7SolvingBrokerError",
    "P7SolvingSeal",
    "normalize_p7_action",
    "normalize_p7_observation",
)
