"""Validated Competition closure evidence, with no SDK payload serialization."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re

from .official import CompetitionSession, OFFICIAL_BASE_URL, OfficialError

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", re.ASCII)


@dataclass(frozen=True, slots=True)
class OfficialGameResult:
    game_id: str
    score: float
    state: str
    completed: bool
    levels_completed: int
    actions: int


@dataclass(frozen=True, slots=True)
class OfficialReceipt:
    card_id: str
    overall_score: float
    games: tuple[OfficialGameResult, ...]
    closure_digest: str

    @property
    def scorecard_url(self) -> str:
        return f"{OFFICIAL_BASE_URL}/scorecards/{self.card_id}"

    @property
    def games_completed(self) -> int:
        return sum(game.completed for game in self.games)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "asterion.prime.p7-official-receipt/v1", "mode": "official",
            "status": "closed-confirmed", "card_id": self.card_id,
            "scorecard_url": self.scorecard_url, "overall_score": self.overall_score,
            "games_attempted": len(self.games), "games_completed": self.games_completed,
            "games": [asdict(game) for game in self.games],
            "closure_digest": self.closure_digest,
        }


def _number(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError
    return float(value)


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _identifier(value: object) -> str:
    if type(value) is not str or _SAFE_ID.fullmatch(value) is None:
        raise ValueError
    return value


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_closed_scorecard(session: CompetitionSession) -> OfficialReceipt:
    """Validate the result retained by a successful, normal one-shot close.

    SDK EnvironmentScoreList holds one run per make. A normal baseline-backed
    EnvironmentScore may omit its optional id; the list id and run guid bind it.
    NOT_PLAYED and NOT_FINISHED are honest unsolved states on a closed card.
    """
    try:
        if (session.normal_close_confirmed is not True or session.aborted
                or session.recovery_required or session.unattempted_game_ids):
            raise ValueError
        card_id = _identifier(session.card_id)
        card = session.closure_result
        if card.card_id != card_id or card.competition_mode is not True:
            raise ValueError
        expected = session.preflight.game_ids
        if (not expected or tuple(sorted(set(expected))) != tuple(expected)
                or set(session.guids) != set(expected)):
            raise ValueError
        rows = card.environments
        if type(rows) not in (list, tuple) or len(rows) != len(expected):
            raise ValueError
        results = {}
        bindings = {}
        for row in rows:
            game_id = _identifier(row.id)
            if game_id not in expected or game_id in results:
                raise ValueError
            if type(row.runs) not in (list, tuple) or len(row.runs) != 1:
                raise ValueError
            run = row.runs[0]
            if (getattr(run, "id", None) not in (None, game_id)
                    or type(run.guid) is not str or not run.guid
                    or run.guid != session.guids[game_id]):
                raise ValueError
            state = getattr(run.state, "name", run.state)
            if state not in ("WIN", "GAME_OVER", "NOT_PLAYED", "NOT_FINISHED"):
                raise ValueError
            if type(run.completed) is not bool or run.completed != (state == "WIN"):
                raise ValueError
            levels = _count(run.levels_completed)
            if (state == "WIN" and levels == 0) or (state == "NOT_PLAYED" and levels != 0):
                raise ValueError
            results[game_id] = OfficialGameResult(
                game_id, _number(run.score), state, run.completed, levels, _count(run.actions))
            bindings[game_id] = run.guid
        games = tuple(results[game_id] for game_id in expected)
        score = _number(card.score)
        # Digest a strict allowlist, including private run identity, not SDK
        # model_dump(): the SDK model contains API keys and arbitrary opaque data.
        digest = sha256(_json({"card_id": card_id, "competition_mode": True,
                              "score": score, "games": [asdict(g) for g in games],
                              "guids": bindings}).encode()).hexdigest()
        return OfficialReceipt(card_id, score, games, digest)
    except Exception:
        raise OfficialError("official result unverified") from None


def _write_private(root: Path, name: str, value: object) -> Path:
    try:
        path = Path(root) / name
        data = _json(value) + "\n"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return path
    except Exception:
        raise OfficialError("official evidence unavailable") from None


def write_official_receipt(receipt: OfficialReceipt, evidence_root: Path) -> Path:
    """Persist the validated allowlist into a new private evidence directory."""
    return _write_private(evidence_root, "official-receipt.json", receipt.to_dict())


def write_recovery_record(session: CompetitionSession, evidence_root: Path) -> Path:
    """Retain lifecycle identities for operator recovery, without a result URL.

    Does not persist the SDK result, API key, errors, prompts, frames or actions.
    A card with malformed closure fields remains unverified here.
    """
    value = {
        "schema": "asterion.prime.p7-official-recovery/v1",
        "status": "recovery-required", "card_id": session.card_id,
        "game_ids": list(session.preflight.game_ids),
        "unattempted_game_ids": list(session.unattempted_game_ids),
        "guids": dict(session.guids), "aborted": session.aborted,
        "normal_close_confirmed": session.normal_close_confirmed,
    }
    return _write_private(evidence_root, "official-recovery.json", value)
