"""Run native.dci-research through the standard Native entry."""

import asyncio
import json
import os
import shutil
import stat
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from asterion.agents.native.application import (
    NativeApplicationSpec,
    NativeOperatorContext,
    prepare_native_application,
)
from asterion.runner.application import ApplicationRunResult
from asterion.runtime.factory import RuntimeFactoryRegistry


QUESTION = (
    "Answer the following question using only wiki_dump.jsonl in the current "
    "directory. Do not use web search. Use rg instead of grep for fast "
    "searching. Question: In which street did the Great Fire of London originate?"
)


async def run_native_dci_research(
    *,
    runtime_factories: RuntimeFactoryRegistry,
    runtime_options: Mapping[str, str],
    corpus_root: str,
    question: str,
    run_id: str,
) -> ApplicationRunResult:
    """Prepare and run one DCI retrieval. The caller owns the registry."""

    application = prepare_native_application(
        NativeApplicationSpec(
            application_id="native.dci-research",
            application_version="1.0.0",
        ),
        NativeOperatorContext(
            runtime_factories=runtime_factories,
            runtime_options=runtime_options,
            host_service_options={
                "corpus.local-root": {"root": corpus_root},
            },
            managed_host_services={},
        ),
    )
    return await application.run(question, run_id=run_id)


class ReadinessFailure(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LiveConfiguration:
    provider: str
    model: str
    node: str
    cli: str
    corpus: str
    agent_dir: str
    evidence_root: str
    environment: dict[str, str]


def repository_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "asterion").is_dir():
            return parent
    raise ReadinessFailure("evidence parent is unavailable")


def path_is_exact(value: str, *, require_directory: bool) -> bool:
    if type(value) is not str:
        return False
    path = Path(value)
    if (
        not path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts[1:])
        or str(path.resolve(strict=False)) != value
    ):
        return False
    current = Path(path.anchor)
    try:
        details = current.stat(follow_symlinks=False)
    except OSError:
        return False
    for component in path.parts[1:]:
        current /= component
        try:
            details = current.stat(follow_symlinks=False)
        except FileNotFoundError:
            return current == path and not require_directory
        except OSError:
            return False
        if stat.S_ISLNK(details.st_mode):
            return False
    if require_directory and not stat.S_ISDIR(details.st_mode):
        return False
    return True


def _real_directory(path: Path) -> bool:
    try:
        details = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode)


def _regular_file(path: Path) -> bool:
    try:
        details = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(details.st_mode) and not stat.S_ISLNK(details.st_mode)


def _required(env: Mapping[str, str], name: str, reason: str) -> str:
    value = env.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ReadinessFailure(reason)
    return value


def _pi_checkout(root: Path, env: Mapping[str, str]) -> Path:
    configured = env.get("DCI_PI_DIR")
    candidates = []
    if isinstance(configured, str) and configured.strip():
        candidates.append(Path(configured).expanduser())
    candidates.append(root / "pi")
    for checkout in candidates:
        cli = checkout / "packages/coding-agent/dist/cli.js"
        if _real_directory(checkout) and _regular_file(cli):
            return checkout
    raise ReadinessFailure("pi checkout is unavailable")


def _node_path(which) -> str:
    found = which("node")
    if not isinstance(found, str) or not found:
        raise ReadinessFailure("node executable is unavailable")
    node = Path(found).resolve()
    text = str(node)
    if not path_is_exact(text, require_directory=False):
        raise ReadinessFailure("node executable is unavailable")
    try:
        details = node.stat(follow_symlinks=False)
    except OSError:
        raise ReadinessFailure("node executable is unavailable") from None
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or stat.S_IMODE(details.st_mode) & 0o111 == 0
        or not os.access(node, os.X_OK)
    ):
        raise ReadinessFailure("node executable is unavailable")
    return text


def resolve_live_configuration(root: Path, env: Mapping[str, str], *, which=shutil.which) -> LiveConfiguration:
    """Return one live configuration or raise a public readiness failure."""

    provider = _required(env, "DCI_PROVIDER", "missing DCI_PROVIDER")
    model = _required(env, "DCI_MODEL", "missing DCI_MODEL")
    checkout = _pi_checkout(root, env)
    cli = checkout / "packages/coding-agent/dist/cli.js"
    if not cli.is_absolute():
        cli = Path.cwd() / cli
    node = _node_path(which)
    raw_agent = env.get("DCI_PI_AGENT_DIR")
    agent = Path(raw_agent).expanduser() if isinstance(raw_agent, str) and raw_agent else Path("~/.pi/agent").expanduser()
    if not agent.is_absolute() or not _real_directory(agent):
        raise ReadinessFailure("agent directory is unavailable")
    configured_corpus = env.get("ASTERION_DCI_CORPUS_ROOT")
    if isinstance(configured_corpus, str) and Path(configured_corpus).is_absolute():
        corpus = Path(configured_corpus) / "wiki_corpus"
    else:
        corpus = root / "corpus" / "wiki_corpus"
    corpus_text = str(corpus)
    if (
        not path_is_exact(corpus_text, require_directory=True)
        or not (corpus / "wiki_dump.jsonl").is_file()
    ):
        raise ReadinessFailure("corpus is unavailable")
    outputs = root / "outputs"
    if not outputs.exists():
        outputs.mkdir(mode=0o755)
    elif not _real_directory(outputs):
        raise ReadinessFailure("evidence parent is unavailable")
    evidence = outputs / "native-dci-example"
    if evidence.exists() and not _real_directory(evidence):
        raise ReadinessFailure("evidence parent is unavailable")
    evidence_text = str(evidence)
    if not path_is_exact(evidence_text, require_directory=False):
        raise ReadinessFailure("evidence parent is unavailable")
    environment = {str(key): str(value) for key, value in env.items()}
    environment["PI_CODING_AGENT_DIR"] = str(agent)
    return LiveConfiguration(
        provider=provider,
        model=model,
        node=node,
        cli=str(cli),
        corpus=corpus_text,
        agent_dir=str(agent),
        evidence_root=evidence_text,
        environment=environment,
    )


def live_runtime_options(config: LiveConfiguration) -> dict[str, str]:
    return {
        "command": json.dumps(
            [config.node, config.cli, "--mode", "rpc"],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "cwd": config.corpus,
        "environment": json.dumps(
            config.environment,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "evidence_root": config.evidence_root,
        "max_turns": "6",
        "tools": "read,grep",
        "provider": config.provider,
        "model": config.model,
    }


def public_status_line(run_id: str, status: str) -> str:
    return json.dumps(
        {
            "application_id": "native.dci-research",
            "run_id": run_id,
            "status": status,
        },
        sort_keys=True,
    )


async def execute_live(config: LiveConfiguration, *, prepare=None, run_id: str) -> int:
    try:
        if prepare is not None:
            prepare(config)
            raise RuntimeError("live prepare injection returned")
        from asterion.runtime.defaults import default_runtime_factory_registry

        await run_native_dci_research(
            runtime_factories=default_runtime_factory_registry(),
            runtime_options=live_runtime_options(config),
            corpus_root=config.corpus,
            question=QUESTION,
            run_id=run_id,
        )
    except Exception:
        print(public_status_line(run_id, "failed"))
        print("native-dci-example: run failed", file=sys.stderr)
        return 1
    print(public_status_line(run_id, "completed"))
    return 0


async def run_live(*, root: Path, env: Mapping[str, str], prepare=None, which=shutil.which) -> int:
    try:
        config = resolve_live_configuration(root, env, which=which)
    except ReadinessFailure as error:
        print(error.reason, file=sys.stderr)
        return 2
    return await execute_live(
        config,
        prepare=prepare,
        run_id="native-dci-" + uuid.uuid4().hex,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["--live"]:
        print("native-dci-example: use --live", file=sys.stderr)
        return 2
    root = repository_root()
    env_file = root / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=False)
    return asyncio.run(run_live(root=root, env=os.environ))


if __name__ == "__main__":
    raise SystemExit(main())
