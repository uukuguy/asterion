"""Operator-owned ARC-AGI-3 Competition run across the official catalog."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from typing import Any

from asterion.applications.prime import create_prime_arc_agi_3_gameplay_provider
from asterion.applications.provider import InstalledApplication, resolve_installed_provider
from asterion.capabilities.prime_arc_agi_3_gameplay.provider import (
    CAPABILITY_REF,
    PACKAGE_REF,
    create_prime_arc_agi_3_gameplay_package,
)
from asterion.runner.composed import run_composed_application
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryContext

from .game import ArcGameContract, GAME_ID_ENV, SEED_ENV, P7GameSelection, _read_catalog, resolve_game_selection
from . import live
from .model_selection import declared_model_selection
from .official import CompetitionEngine, CompetitionSession, OfficialError, prepare_session
from .official_result import (
    validate_closed_scorecard,
    write_official_receipt,
    write_recovery_record,
)
from .operator import build_p7_operator_resources
from .official_replay import execute_saved_prefix
from .prompt import P7_SOLVE_PROMPT


_FULL_ROSTER_MODEL_ID = "gpt-6.1-sol"


@dataclass(frozen=True, slots=True)
class OfficialGameAttempt:
    """Public-safe local progress; the SDK scorecard remains authoritative."""

    game_id: str
    status: str
    run_id: str


async def run_official_games(
    session: Any,
    run_game: Callable[[Any, ArcGameContract, str], Awaitable[None]],
) -> tuple[OfficialGameAttempt, ...]:
    """Open one card, attempt every catalog game once, then close normally.

    A failed game is still an attempt. The SDK scorecard later decides its
    official score. Interruptions escape so session disposal can abort-close.
    """

    session.open()
    attempts: list[OfficialGameAttempt] = []
    for policy in session.preflight.games:
        run_id = live.safe_run_id()
        try:
            engine = session.make(policy.game_id)
        except Exception:
            attempts.append(OfficialGameAttempt(policy.game_id, "make-failed", run_id))
            continue
        try:
            game = ArcGameContract(
                policy.game_id,
                win_levels=engine.win_levels,
                action_cap=policy.action_cap,
            )
            await run_game(engine, game, run_id)
        except Exception:
            attempts.append(OfficialGameAttempt(policy.game_id, "run-failed", run_id))
        else:
            attempts.append(OfficialGameAttempt(policy.game_id, "run-completed", run_id))
    session.close()
    return tuple(attempts)


@dataclass(frozen=True, repr=False, slots=True)
class OfficialInvocation:
    operator_root: Path
    environment: Mapping[str, str]
    pi_base_command: tuple[str, ...]
    extension_path: Path
    api_key: str

    def __repr__(self) -> str:
        return "<OfficialInvocation redacted>"


@dataclass(frozen=True, repr=False, slots=True)
class SavedInvocation:
    operator_root: Path
    arc_root: Path
    api_key: str
    prefixes: tuple[object, ...]
    catalog_ids: tuple[str, ...] = ()

    def __repr__(self) -> str:
        return "<SavedInvocation redacted>"


@dataclass(frozen=True, repr=False, slots=True)
class CatalogInvocation:
    operator_root: Path
    api_key: str

    def __repr__(self) -> str:
        return "<CatalogInvocation redacted>"


def _preflight_catalog(process_environment: Mapping[str, str]) -> CatalogInvocation:
    """Resolve only the credential needed for the read-only official catalog."""
    import asterion

    try:
        root = Path(process_environment[live.OPERATOR_ROOT_ENV]).resolve(strict=True)
        package = Path(str(asterion.__file__)).resolve(strict=True)
        if package.is_relative_to(root) or "site-packages" not in package.parts:
            raise ValueError
        environment = {**live._dotenv_values(root / ".env"), **process_environment}
        api_key = environment.get("ARC_API_KEY", "").strip()
        if not api_key:
            raise ValueError
        return CatalogInvocation(root, api_key)
    except Exception:
        raise OfficialError("official preflight unavailable") from None


def _preflight(process_environment: Mapping[str, str]) -> OfficialInvocation:
    """Resolve an installed operator and both credentials before card creation."""
    import asterion

    try:
        root = Path(process_environment[live.OPERATOR_ROOT_ENV]).resolve(strict=True)
        package = Path(str(asterion.__file__)).resolve(strict=True)
        if package.is_relative_to(root) or "site-packages" not in package.parts:
            raise ValueError
        environment = live.load_operator_environment(root)
        api_key = environment.get("ARC_API_KEY", "").strip()
        if not api_key:
            raise ValueError
        return OfficialInvocation(
            root,
            environment,
            live.pi_base_command(
                node=live.resolve_node(environment),
                pi_entry=live.resolve_pi_entry(environment),
            ),
            live.extension_path(),
            api_key,
        )
    except Exception:
        raise OfficialError("official preflight unavailable") from None


def _load_current_roster_prefixes(
    arc_root: Path, runs_root: Path, catalog: tuple[dict[str, object], ...],
) -> tuple[object, ...]:
    """Verify current WorldMap sources directly; display caches grant no authority."""
    from .score import partial_game_score
    from .solutions import VerifiedPrefix, load_exact_prefix, load_resume_worldmap, source_experiment

    if runs_root.is_symlink() or not runs_root.is_dir():
        return ()
    games = {row["game_id"]: row for row in catalog}
    best: dict[str, tuple[tuple[object, ...], VerifiedPrefix]] = {}
    for run in sorted(runs_root.iterdir(), key=lambda path: path.name):
        try:
            summary_path = run / "summary.json"
            if (run.is_symlink() or not run.is_dir() or summary_path.is_symlink()
                    or not summary_path.is_file() or summary_path.stat().st_size > 1024 * 1024):
                continue
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            experiment = source_experiment(run, summary) if type(summary) is dict else None
            if (type(experiment) is not dict
                    or summary.get("schema") != "asterion.prime.p7-live-private-summary/v1"
                    or summary.get("run_id") != run.name
                    or experiment.get("model") != _FULL_ROSTER_MODEL_ID
                    or type(experiment.get("seed")) is not int or experiment["seed"] != 0
                    or experiment.get("prediction_variant") != "verified"):
                continue
            game_id = experiment.get("game_id")
            if type(game_id) is not str or game_id not in games:
                continue
            game = games[game_id]
            scope = VerifiedPrefix(game_id, 0, game["win_levels"], 0, (), run.name, "")
            if load_resume_worldmap(run, scope) is None:
                continue
            prefix = load_exact_prefix(arc_root, runs_root, run.name, game_id, 0,
                                       expected_model_id=_FULL_ROSTER_MODEL_ID)
            if prefix is None:
                continue
            counts, previous = [], 0
            for level in range(1, prefix.levels_completed + 1):
                end = next(item.sequence for item in prefix.transitions if item.levels_completed == level)
                counts.append(end - previous)
                previous = end
            selection = P7GameSelection(game_id, 0, prefix.levels_completed,
                                        tuple(game["baseline_actions"]), game["win_levels"])
            key = (-prefix.levels_completed, -Decimal(partial_game_score(tuple(counts), selection)),
                   len(prefix.transitions), prefix.source_run_id)
            if game_id not in best or key < best[game_id][0]:
                best[game_id] = (key, prefix)
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, StopIteration):
            continue
    return tuple(best[game_id][1] for game_id in sorted(best))


def _preflight_saved(process_environment: Mapping[str, str]) -> SavedInvocation:
    """Verify local actions and ARC credentials before any scorecard operation."""
    import asterion
    from .solutions import load_best_prefix

    try:
        root = Path(process_environment[live.OPERATOR_ROOT_ENV]).resolve(strict=True)
        package = Path(str(asterion.__file__)).resolve(strict=True)
        if package.is_relative_to(root) or "site-packages" not in package.parts:
            raise ValueError
        environment = {**live._dotenv_values(root / ".env"), **process_environment}
        expected_model_id = declared_model_selection(environment).model
        api_key = environment.get("ARC_API_KEY", "").strip()
        if not api_key:
            raise ValueError
        arc_root = live.resolve_arc_root(environment)
        runs_root = root / ".asterion-private" / "prime-p7-live"
        requested = process_environment.get(GAME_ID_ENV, "")
        if type(requested) is not str or not requested:
            raise ValueError
        if requested == "all":
            if expected_model_id != _FULL_ROSTER_MODEL_ID:
                raise ValueError
            catalog = _read_catalog(arc_root)
            catalog_ids = tuple(sorted(row["game_id"] for row in catalog))
            if not catalog_ids or len(set(catalog_ids)) != len(catalog_ids):
                raise ValueError
            prefixes = _load_current_roster_prefixes(arc_root, runs_root, catalog)
            return SavedInvocation(root, arc_root, api_key, prefixes, catalog_ids)
        else:
            game = resolve_game_selection(
                {GAME_ID_ENV: requested, SEED_ENV: "0"}, arc_root
            )
            prefix = load_best_prefix(
                arc_root,
                runs_root,
                game.game_id,
                0,
                expected_model_id=expected_model_id,
            )
            prefixes = () if prefix is None else (prefix,)
        if not prefixes:
            raise ValueError
        return SavedInvocation(root, arc_root, api_key, tuple(prefixes))
    except Exception:
        raise OfficialError("official saved preflight unavailable") from None


def _private_root(operator_root: Path, run_id: str) -> Path:
    base = operator_root / ".asterion-private" / "prime-p7-official"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    path = base / run_id
    path.mkdir(mode=0o700)
    return path


def _resolve_gameplay_application() -> InstalledApplication:
    provider = resolve_installed_provider(
        create_prime_arc_agi_3_gameplay_provider(),
        runtime_factories=default_runtime_factory_registry(),
        installed_packages=(create_prime_arc_agi_3_gameplay_package(),),
    )
    return provider.applications[0]


async def _run_game(
    invocation: OfficialInvocation,
    application: InstalledApplication,
    evidence_root: Path,
    engine: CompetitionEngine,
    game: ArcGameContract,
    run_id: str,
) -> None:
    """Run one exact official engine through the installed gameplay assembly."""
    resources = None
    try:
        game_root = evidence_root / run_id
        game_root.mkdir(mode=0o700)
        trace_root = game_root / "trace"
        trace_root.mkdir(mode=0o700)
        worker = live.SubprocessPythonWorker(root=game_root)
        resources = build_p7_operator_resources(
            environment=invocation.environment,
            pi_base_command=invocation.pi_base_command,
            extension_path=invocation.extension_path,
            working_directory=invocation.operator_root,
            worker=worker,
            engine=engine,
            private_trace_root=trace_root,
            game=game,
        )
        assembly = application.assemblies[0]
        runtime = assembly.runtime_binding.factory(
            RuntimeFactoryContext(
                provider_id="prime-applications",
                application_id="prime.arc-agi-3-gameplay",
                application_version="1.0.0",
                runtime_id="asterion.prime",
                assembly_path=assembly.path,
                options=resources.runtime_options,
                host_services=resources.host_services,
            )
        )
        result = await run_composed_application(
            assembly.plan,
            implementations=application.implementations,
            runtime=runtime,
            run_id=run_id,
            input_text=P7_SOLVE_PROMPT + "\n\nInitial research context:\n" + json.dumps(
                resources.host_services["prime.ipython"].current_context(),
                ensure_ascii=False, separators=(",", ":"),
            ),
            host_services=resources.host_services,
            implementation_packages={CAPABILITY_REF: PACKAGE_REF},
            signal=live.NeverCancelled(),
        )
        value = live.receipt_value(result.artifacts)
        if (
            value.get("game_id") != game.game_id
            or value.get("win_levels") != game.win_levels
            or value.get("action_cap") != game.action_cap
            or value.get("scope") != "p7-gameplay-run"
            or value.get("outcome") not in {"game-won", "failed"}
        ):
            raise OfficialError("official gameplay evidence unavailable")
    finally:
        try:
            if resources is not None:
                await resources.close()
        finally:
            engine.close()


async def _submit(
    invocation: OfficialInvocation,
    session: CompetitionSession,
    evidence_root: Path,
) -> dict[str, object]:
    application = _resolve_gameplay_application()

    async def run_game(
        engine: CompetitionEngine, game: ArcGameContract, run_id: str
    ) -> None:
        await _run_game(invocation, application, evidence_root, engine, game, run_id)

    await run_official_games(session, run_game)
    receipt = validate_closed_scorecard(session)
    write_official_receipt(receipt, evidence_root)
    return receipt.to_dict()


def _submit_saved(
    session: CompetitionSession,
    evidence_root: Path,
    prefixes: tuple[object, ...],
    *,
    catalog_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    """Replay each saved route once; a full roster also makes every zero row."""
    prefix_ids = tuple(getattr(prefix, "game_id", None) for prefix in prefixes)
    if (any(type(game_id) is not str for game_id in prefix_ids)
            or len(set(prefix_ids)) != len(prefix_ids)):
        raise OfficialError("official saved selection unavailable")
    if catalog_ids:
        if (type(catalog_ids) is not tuple or catalog_ids != tuple(sorted(set(catalog_ids)))
                or catalog_ids != session.preflight.game_ids or catalog_ids != session.selected_game_ids
                or not set(prefix_ids).issubset(catalog_ids)):
            raise OfficialError("official saved catalog unavailable")
        selected = catalog_ids
    elif not prefixes or prefix_ids != session.selected_game_ids:
        raise OfficialError("official saved selection unavailable")
    else:
        selected = prefix_ids
    by_game = dict(zip(prefix_ids, prefixes))
    session.open()
    for game_id in selected:
        engine = session.make(game_id)
        try:
            prefix = by_game.get(game_id)
            if prefix is not None:
                execute_saved_prefix(engine, prefix)
            else:
                initial = engine.observe()
                if initial.get("levels_completed") != 0 or initial.get("state") != "NOT_FINISHED":
                    raise OfficialError("official initial observation unavailable")
        finally:
            engine.close()
    session.close()
    receipt = validate_closed_scorecard(session)
    write_official_receipt(receipt, evidence_root)
    return receipt.to_dict()


def main(argv: list[str] | None = None) -> int:
    """Run a read-only catalog preflight or one explicit paid submission."""
    if sys.argv[1:] if argv is None else argv:
        print('{"status":"preflight-rejected"}')
        return 2
    mode = os.environ.get("ASTERION_PRIME_P7_OFFICIAL_MODE", "")
    if mode not in {"preflight", "submit", "saved-submit", "live-eval"}:
        print('{"status":"preflight-rejected"}')
        return 2
    session: CompetitionSession | None = None
    evidence_root: Path | None = None
    try:
        invocation = (
            _preflight_catalog(os.environ) if mode == "preflight" else
            _preflight_saved(os.environ) if mode == "saved-submit" else
            _preflight(os.environ)
        )
        run_id = live.safe_run_id()
        evidence_root = _private_root(invocation.operator_root, run_id)
        with prepare_session(
            api_key=invocation.api_key,
            evidence_root=evidence_root,
            model_host_ready=True,
            **(
                {"selected_game_ids": invocation.catalog_ids or tuple(prefix.game_id for prefix in invocation.prefixes)}
                if isinstance(invocation, SavedInvocation) else {}
            ),
        ) as session:
            if mode == "preflight":
                value = {
                    "schema": "asterion.prime.p7-official-preflight/v1",
                    "status": "ready",
                    "game_count": session.preflight.game_count,
                    "total_action_cap": session.preflight.total_action_cap,
                    "total_model_callback_cap": session.preflight.total_model_callback_cap,
                    "total_deadline_seconds": session.preflight.total_deadline_seconds,
                    "games": [
                        {
                            "game_id": game.game_id,
                            "action_cap": game.action_cap,
                            "model_callback_cap": game.model_callback_cap,
                            "deadline_seconds": game.deadline_seconds,
                        }
                        for game in session.preflight.games
                    ],
                }
            elif mode == "saved-submit":
                if not isinstance(invocation, SavedInvocation):
                    raise OfficialError("official saved selection unavailable")
                value = _submit_saved(session, evidence_root, invocation.prefixes,
                                      catalog_ids=invocation.catalog_ids)
            else:
                value = asyncio.run(_submit(invocation, session, evidence_root))
        print(json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True))
        return 0
    except KeyboardInterrupt:
        _retain_recovery(session, evidence_root)
        print('{"status":"recovery-required"}')
        return 130
    except Exception:
        if mode in {"submit", "saved-submit", "live-eval"}:
            _retain_recovery(session, evidence_root)
        before_session = session is None
        rejected = mode == "preflight" or before_session
        print(json.dumps({"status": (
            "preflight-rejected" if rejected else "recovery-required"
        )}, separators=(",", ":")))
        return 2 if rejected else 1


def _retain_recovery(
    session: CompetitionSession | None, evidence_root: Path | None
) -> None:
    if session is None or evidence_root is None:
        return
    try:
        write_recovery_record(session, evidence_root)
    except OfficialError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ("OfficialGameAttempt", "OfficialInvocation", "main", "run_official_games")
