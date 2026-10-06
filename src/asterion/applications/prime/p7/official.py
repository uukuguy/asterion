"""Application-owned, one-shot official Competition SDK lifecycle.

No SDK import or remote operation occurs at module import. The operator supplies
readiness and credentials; public errors deliberately contain fixed text only.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any

from .broker import ArcAction, _canonical_action, _snapshot_observation

OFFICIAL_BASE_URL = "https://three.arcprize.org"
_GAME_ID = re.compile(r"[A-Za-z0-9]+-[A-Za-z0-9]+", re.ASCII)


class OfficialError(RuntimeError):
    """Fixed public-safe official operation failure."""

    def __init__(self, message, *, reason='unknown'):
        super().__init__(message)
        self.reason = reason if reason in {
            'unknown', 'initial-state', 'identity-mismatch', 'observation-invalid', 'action-invalid',
            'sdk-action-failed', 'levels-regressed', 'scorecard-open-failed',
            'scorecard-close-failed', 'game-make-failed'} else 'unknown'


@dataclass(frozen=True, slots=True)
class OfficialGamePolicy:
    game_id: str
    action_cap: int
    baseline_actions: tuple[int, ...] | None
    model_callback_cap: int = 128
    deadline_seconds: int = 3600


@dataclass(frozen=True, slots=True)
class OfficialPreflight:
    games: tuple[OfficialGamePolicy, ...]

    @property
    def game_ids(self) -> tuple[str, ...]:
        return tuple(game.game_id for game in self.games)

    @property
    def total_action_cap(self) -> int:
        return sum(game.action_cap for game in self.games)

    @property
    def total_model_callback_cap(self) -> int:
        return sum(game.model_callback_cap for game in self.games)

    @property
    def total_deadline_seconds(self) -> int:
        return sum(game.deadline_seconds for game in self.games)

    @property
    def game_count(self) -> int:
        return len(self.games)


def _mode(value: object) -> str:
    return str(getattr(value, "value", value)).upper()


def _check_overrides() -> None:
    if os.environ.get("ARC_BASE_URL", OFFICIAL_BASE_URL) != OFFICIAL_BASE_URL:
        raise ValueError
    if os.environ.get("OPERATION_MODE", "competition").strip().lower() != "competition":
        raise ValueError


def _check_sdk(sdk: Any) -> None:
    _check_overrides()
    if _mode(sdk.operation_mode) != "COMPETITION" or sdk.arc_base_url != OFFICIAL_BASE_URL:
        raise ValueError


def official_sdk_factory(**kwargs: Any) -> Any:
    """Lazy production factory; fake factories receive the same SDK arguments."""
    from arc_agi import Arcade, OperationMode
    from arcengine import GameAction

    _check_overrides()  # SDK import may load dotenv; check again before any network.
    kwargs["operation_mode"] = OperationMode.COMPETITION
    sdk = Arcade(**kwargs)
    # The mapping is adapter-owned, never caller-provided executable content.
    sdk._asterion_actions = {name: getattr(GameAction, name) for name in
                            ("RESET", *(f"ACTION{i}" for i in range(1, 8)))}
    return sdk


def _catalog(sdk: Any) -> OfficialPreflight:
    rows = sdk.get_environments()
    if type(rows) not in (list, tuple) or not rows:
        raise ValueError
    games = []
    for row in rows:
        game_id = getattr(row, "game_id", None)
        if type(game_id) is not str or not _GAME_ID.fullmatch(game_id):
            raise ValueError
        baseline = getattr(row, "baseline_actions", None)
        if (type(baseline) in (list, tuple) and baseline
                and all(type(n) is int and n > 0 for n in baseline)):
            baseline = tuple(baseline)
        else:
            baseline = None
        cap = 1000 if baseline is None else min(5000, max(1000, 2 * sum(baseline)))
        games.append(OfficialGamePolicy(game_id, cap, baseline))
    if len({game.game_id for game in games}) != len(games):
        raise ValueError
    return OfficialPreflight(tuple(sorted(games, key=lambda game: game.game_id)))


def prepare_session(*, api_key: str, evidence_root: Path, model_host_ready: bool,
                    sdk_factory: Callable[..., Any] | None = None,
                    selected_game_ids: tuple[str, ...] | list[str] | None = None
                    ) -> CompetitionSession:
    """Discover and seal the official catalog, without opening a scorecard.

    The private scratch directory probes evidence writability and provides an
    empty metadata root, preventing the SDK's local catalog scan from masking
    an unsuccessful remote discovery. Call dispose() when finished.
    """
    scratch = None
    sdk = None
    try:
        _check_overrides()
        if type(api_key) is not str or not api_key.strip() or model_host_ready is not True:
            raise ValueError
        root = Path(evidence_root)
        if not root.is_dir():
            raise ValueError
        scratch = TemporaryDirectory(prefix=".p7-official-", dir=root)
        metadata = Path(scratch.name) / "environments"
        metadata.mkdir(mode=0o700)
        logger = logging.Logger("asterion.prime.p7.official", level=logging.CRITICAL)
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        sdk = (sdk_factory or official_sdk_factory)(
            arc_api_key=api_key, arc_base_url=OFFICIAL_BASE_URL,
            operation_mode="COMPETITION", environments_dir=str(metadata),
            recordings_dir=str(Path(scratch.name) / "recordings"), logger=logger,
        )
        _check_sdk(sdk)
        readiness = _catalog(sdk)
        return CompetitionSession(sdk, readiness, scratch,
                                  selected_game_ids=selected_game_ids)
    except Exception:
        _dispose_sdk(sdk)
        if scratch is not None:
            scratch.cleanup()
        raise OfficialError("official preflight unavailable") from None


def preflight(**kwargs: Any) -> OfficialPreflight:
    """Read-only convenience that also releases private SDK resources."""
    with prepare_session(**kwargs) as session:
        return session.preflight


def _dispose_sdk(sdk: Any) -> None:
    # SDK HTTP sessions own no gameplay lifecycle; closing their transport must
    # never trigger another reset, card, or server scorecard read.
    transport = getattr(sdk, "_session", None)
    if callable(getattr(transport, "close", None)):
        try:
            transport.close()
        except Exception:
            pass


class CompetitionSession:
    """One catalog, one create attempt, one make per exact game, one close attempt."""

    def __init__(self, sdk: Any, readiness: OfficialPreflight, scratch: TemporaryDirectory,
                 *, selected_game_ids: tuple[str, ...] | list[str] | None = None) -> None:
        self._sdk = sdk
        self._preflight = readiness
        self._scratch = scratch
        catalog_ids = readiness.game_ids
        if selected_game_ids is None:
            selected = catalog_ids
        else:
            if (type(selected_game_ids) not in (tuple, list)
                    or not selected_game_ids
                    or any(type(game_id) is not str for game_id in selected_game_ids)
                    or len(set(selected_game_ids)) != len(selected_game_ids)
                    or not set(selected_game_ids).issubset(catalog_ids)):
                raise ValueError
            selected = tuple(sorted(selected_game_ids))
        self._selected_game_ids = tuple(selected)
        self.card_id: str | None = None
        self.closure_result: Any = None
        self.abort_result: Any = None
        self._aborted = False
        self.recovery_required = False
        self._open_attempted = False
        self._close_attempted = False
        self._disposed = False
        self._made: set[str] = set()
        self._environments: list[Any] = []
        self._guids: dict[str, str] = {}

    def __repr__(self) -> str:
        return "<CompetitionSession redacted>"

    @property
    def preflight(self) -> OfficialPreflight:
        return self._preflight

    @property
    def selected_game_ids(self) -> tuple[str, ...]:
        return self._selected_game_ids

    @property
    def catalog_unselected_game_ids(self) -> tuple[str, ...]:
        return tuple(game_id for game_id in self.preflight.game_ids
                     if game_id not in self._selected_game_ids)

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def unattempted_game_ids(self) -> tuple[str, ...]:
        """Exact missing IDs, retained after abort for private recovery evidence."""
        return tuple(game_id for game_id in self._selected_game_ids if game_id not in self._made)

    @property
    def normal_close_confirmed(self) -> bool:
        """Lifecycle fact only; scorecard rows and scores still require validation."""
        return self.closure_result is not None and not self._aborted

    @property
    def abort_close_confirmed(self) -> bool:
        """Abort response matched this card; this never grants a normal receipt."""
        return self.abort_result is not None and self._aborted

    @property
    def guids(self) -> Mapping[str, str]:
        from types import MappingProxyType
        return MappingProxyType(dict(self._guids))

    def _require_open(self) -> None:
        if self._disposed or self.card_id is None or self._close_attempted:
            raise ValueError
        _check_sdk(self._sdk)

    def open(self) -> str:
        try:
            if self._disposed or self._open_attempted:
                raise ValueError
            _check_sdk(self._sdk)
            self._open_attempted = True
            card_id = self._sdk.create_scorecard()
            if type(card_id) is not str or not card_id.strip():
                raise ValueError
            self.card_id = card_id
            return card_id
        except Exception:
            if self._open_attempted and self.card_id is None:
                self.recovery_required = True
            raise OfficialError("official scorecard unavailable", reason="scorecard-open-failed") from None

    def make(self, game_id: str) -> CompetitionEngine:
        try:
            self._require_open()
            if game_id not in self._selected_game_ids or game_id in self._made:
                raise ValueError
            self._made.add(game_id)
            environment = self._sdk.make(game_id, scorecard_id=self.card_id,
                                         include_frame_data=True, save_recording=False)
            if environment is None:
                raise ValueError
            self._environments.append(environment)
            engine = CompetitionEngine(self, environment, game_id)
            self._guids[game_id] = engine.guid
            return engine
        except Exception:
            if game_id in self._made:
                # The remote make may have created a run even when its return
                # value was lost or failed identity validation.  It cannot be
                # retried safely and must remain recovery-only.
                self.recovery_required = True
            raise OfficialError("official game unavailable", reason="game-make-failed") from None

    def close(self) -> Any:
        """Close an ordinary attempt only after every selected game was attempted."""
        if self.unattempted_game_ids:
            raise OfficialError("official games unattempted")
        return self._close(abort=False)

    def abort_close(self) -> Any:
        """Close interrupted work; its result cannot become a normal receipt."""
        return self._close(abort=True)

    def _close(self, *, abort: bool) -> Any:
        if self._disposed or self.card_id is None or self._close_attempted:
            raise OfficialError("official scorecard unavailable")
        self._close_attempted = True
        self._aborted = abort
        try:
            _check_sdk(self._sdk)
            result = self._sdk.close_scorecard(self.card_id)
            if result is None or getattr(result, "card_id", None) != self.card_id:
                raise ValueError
            if abort:
                self.abort_result = result
            else:
                self.closure_result = result
            return result
        except Exception:
            self.recovery_required = True
            raise OfficialError("official scorecard recovery required", reason="scorecard-close-failed") from None

    def dispose(self) -> None:
        if self._disposed:
            return
        if self.card_id is not None and not self._close_attempted:
            try:
                # Cleanup cannot prove the operator finished its game loop.
                self.abort_close()
            except OfficialError:
                pass
        self._disposed = True
        for environment in self._environments:
            _dispose_sdk(environment)
        _dispose_sdk(self._sdk)
        self._scratch.cleanup()

    def __enter__(self) -> CompetitionSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.dispose()


class CompetitionEngine:
    """Broker-compatible live observations; never creates or replays an engine."""

    def __init__(self, session: CompetitionSession, environment: Any, game_id: str) -> None:
        self._session = session
        self._environment = environment
        self.game_id = game_id
        # Compatibility identity for the broker's local replay contract. The
        # Competition server does not accept or attest a caller-chosen seed.
        self.seed = 0
        self._current = environment.observation_space
        self.guid = getattr(self._current, "guid", None)
        self.win_levels = getattr(self._current, "win_levels", None)
        if (type(self.guid) is not str or not self.guid.strip()
                or type(self.win_levels) is not int or self.win_levels < 1):
            raise ValueError
        policy = next(game for game in session.preflight.games if game.game_id == game_id)
        if policy.baseline_actions is not None and len(policy.baseline_actions) != self.win_levels:
            raise ValueError
        self._validate_identity(self._current)
        self._snapshot(self._current)

    def __repr__(self) -> str:
        return "<CompetitionEngine redacted>"

    def _validate_identity(self, observation: Any) -> None:
        env = self._environment
        self._session._require_open()
        if (env.environment_info.game_id != self.game_id
                or env.scorecard_id != self._session.card_id
                or env.base_url != OFFICIAL_BASE_URL
                or env._guid != self.guid
                or getattr(observation, "guid", None) != self.guid
                or getattr(observation, "game_id", None) != self.game_id):
            raise ValueError

    def _snapshot(self, observation: Any) -> dict[str, object]:
        def frame(value: Any) -> Any:
            if hasattr(value, "tolist"):
                value = value.tolist()
            return [frame(item) for item in value] if isinstance(value, (list, tuple)) else value
        state = observation.state
        snapshot = {
            "available_actions": sorted(getattr(item, "value", item) for item in observation.available_actions),
            "frame": frame(observation.frame), "levels_completed": observation.levels_completed,
            "state": getattr(state, "value", state), "win_levels": observation.win_levels,
        }
        _snapshot_observation(snapshot, win_levels=self.win_levels)
        return snapshot

    def observe(self) -> dict[str, object]:
        reason = 'identity-mismatch'
        try:
            self._validate_identity(self._current)
            reason = 'observation-invalid'
            return self._snapshot(self._current)
        except Exception:
            raise OfficialError('official observation unavailable', reason=reason) from None

    def step(self, action: str, data: Mapping[str, int] | None = None) -> dict[str, object]:
        reason = 'identity-mismatch'
        try:
            self._validate_identity(self._current)
            reason = 'action-invalid'
            action_value = _canonical_action(ArcAction(action, tuple(sorted((data or {}).items()))))
            actions = getattr(self._session._sdk, '_asterion_actions', {})
            reason = 'sdk-action-failed'
            result = self._environment.step(actions.get(action, action), dict(action_value.data))
            reason = 'identity-mismatch'
            self._validate_identity(result)
            reason = 'observation-invalid'
            snapshot = self._snapshot(result)
            reason = 'levels-regressed'
            if snapshot['levels_completed'] < self._current.levels_completed:
                raise ValueError
            self._current = result
            return snapshot
        except Exception:
            raise OfficialError('official action unavailable', reason=reason) from None

    def close(self) -> None:
        """The session owns the remote environment and scorecard lifetime."""
