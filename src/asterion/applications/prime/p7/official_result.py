"""Validated Competition closure evidence, with no SDK payload serialization."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re

from .official import CompetitionSession, OfficialError

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", re.ASCII)
_PUBLIC_SCORECARD_BASE_URL = "https://arcprize.org"


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
    catalog_count: int = 0
    selected_count: int = 0
    played_runs: int = 0
    skipped_count: int = 0

    @property
    def scorecard_url(self) -> str:
        return f"{_PUBLIC_SCORECARD_BASE_URL}/scorecards/{self.card_id}"

    @property
    def games_completed(self) -> int:
        return sum(game.completed for game in self.games)

    @property
    def games_attempted(self) -> int:
        return len(self.games)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "asterion.prime.p7-official-receipt/v1", "mode": "official",
            "status": "closed-confirmed", "card_id": self.card_id,
            "scorecard_url": self.scorecard_url, "overall_score": self.overall_score,
            "catalog_count": self.catalog_count,
            "selected_count": self.selected_count,
            "played_runs": self.played_runs,
            "skipped_count": self.skipped_count,
            "games_attempted": self.games_attempted,
            "games_completed": self.games_completed,
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
    The official SDK may add a zero-action NOT_FINISHED run when closing an
    unselected catalog game; it is a skipped placeholder, not a played game.
    """
    try:
        if (session.normal_close_confirmed is not True or session.aborted
                or session.recovery_required or session.unattempted_game_ids):
            raise ValueError
        card_id = _identifier(session.card_id)
        card = session.closure_result
        if card.card_id != card_id or card.competition_mode is not True:
            raise ValueError
        catalog = session.preflight.game_ids
        selected = tuple(getattr(session, "selected_game_ids", catalog))
        if (not catalog or tuple(sorted(set(catalog))) != tuple(catalog)
                or not selected or tuple(sorted(set(selected))) != tuple(selected)
                or not set(selected).issubset(catalog)
                or set(session.guids) != set(selected)):
            raise ValueError
        rows = card.environments
        if type(rows) not in (list, tuple):
            raise ValueError
        results = {}
        bindings = {}
        for row in rows:
            game_id = _identifier(row.id)
            if game_id not in catalog or game_id in results:
                raise ValueError
            runs = row.runs
            if type(runs) not in (list, tuple):
                raise ValueError
            # The SDK's EnvironmentScoreList computed properties call max()
            # and therefore raise for this documented zero-run skipped shape.
            # Inspect only the raw runs field and never read row.score or other
            # computed fields for an unselected environment.
            if not runs:
                if game_id in selected:
                    raise ValueError
                results[game_id] = None
                continue
            if game_id not in selected:
                if len(runs) != 1:
                    raise ValueError
                run = runs[0]
                state = getattr(run.state, "name", run.state)
                if (getattr(run, "id", None) not in (None, game_id)
                        or type(run.guid) is not str or not run.guid
                        or state != "NOT_FINISHED"
                        or type(run.completed) is not bool or run.completed
                        or _number(run.score) != 0.0
                        or _count(run.levels_completed) != 0
                        or _count(run.actions) != 0
                        or _count(run.resets) != 0):
                    raise ValueError
                results[game_id] = None
                continue
            if len(runs) != 1:
                raise ValueError
            run = runs[0]
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
        if set(results) & (set(catalog) - set(selected)) - {game_id for game_id, value in results.items()
                                                            if value is None}:
            raise ValueError
        if set(selected) != {game_id for game_id, value in results.items() if value is not None}:
            raise ValueError
        games = tuple(results[game_id] for game_id in selected)
        score = _number(card.score)
        skipped = len(catalog) - len(selected)
        # Digest a strict allowlist, including private run identity, not SDK
        # model_dump(): the SDK model contains API keys and arbitrary opaque data.
        digest = sha256(_json({"card_id": card_id, "competition_mode": True,
                              "score": score, "games": [asdict(g) for g in games],
                              "catalog_count": len(catalog), "selected_count": len(selected),
                              "played_runs": len(games), "skipped_count": skipped,
                              "guids": bindings}).encode()).hexdigest()
        return OfficialReceipt(card_id, score, games, digest, len(catalog), len(selected),
                               len(games), skipped)
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
        "selected_game_ids": list(getattr(session, "selected_game_ids",
                                           session.preflight.game_ids)),
        "unattempted_game_ids": list(session.unattempted_game_ids),
        "guids": dict(session.guids), "aborted": session.aborted,
        "normal_close_confirmed": session.normal_close_confirmed,
    }
    return _write_private(evidence_root, "official-recovery.json", value)
