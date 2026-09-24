"""Operator-owned ARC-AGI-3 Competition run across the official catalog."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
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

from .game import ArcGameContract
from . import live
from .official import CompetitionEngine, CompetitionSession, OfficialError, prepare_session
from .official_result import (
    validate_closed_scorecard,
    write_official_receipt,
    write_recovery_record,
)
from .operator import build_p7_operator_resources
from .prompt import P7_SOLVE_PROMPT


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


@dataclass(frozen=True, slots=True)
class OfficialInvocation:
    operator_root: Path
    environment: Mapping[str, str]
    pi_base_command: tuple[str, ...]
    extension_path: Path
    api_key: str


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
    try:
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
            input_text=P7_SOLVE_PROMPT,
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


def main(argv: list[str] | None = None) -> int:
    """Run a read-only catalog preflight or one explicit paid submission."""
    if sys.argv[1:] if argv is None else argv:
        print('{"status":"preflight-rejected"}')
        return 2
    mode = os.environ.get("ASTERION_PRIME_P7_OFFICIAL_MODE", "")
    if mode not in {"preflight", "submit"}:
        print('{"status":"preflight-rejected"}')
        return 2
    session: CompetitionSession | None = None
    evidence_root: Path | None = None
    try:
        invocation = _preflight(os.environ)
        run_id = live.safe_run_id()
        evidence_root = _private_root(invocation.operator_root, run_id)
        with prepare_session(
            api_key=invocation.api_key,
            evidence_root=evidence_root,
            model_host_ready=True,
        ) as session:
            if mode == "preflight":
                value = {
                    "schema": "asterion.prime.p7-official-preflight/v1",
                    "status": "ready",
                    "game_count": session.preflight.game_count,
                    "total_action_cap": session.preflight.total_action_cap,
                    "games": [
                        {"game_id": game.game_id, "action_cap": game.action_cap}
                        for game in session.preflight.games
                    ],
                }
            else:
                value = asyncio.run(_submit(invocation, session, evidence_root))
        print(json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True))
        return 0
    except KeyboardInterrupt:
        _retain_recovery(session, evidence_root)
        print('{"status":"recovery-required"}')
        return 130
    except Exception:
        if mode == "submit":
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
