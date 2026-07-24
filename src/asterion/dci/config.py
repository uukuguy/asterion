"""Configuration boundary for the independent Asterion DCI product."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping, MutableMapping

from dotenv import dotenv_values, load_dotenv


ValueSource = Literal["invocation", "environment", "runtime-default"]

PI_DEFAULT_PROVIDER = "openai-codex"
PI_DEFAULT_MODEL = "gpt-5.6-luna"
PI_DEFAULT_AGENT_DIR = "~/.pi/agent"
PI_DEFAULT_TOOLS = "read,bash"
PI_DEFAULT_MAX_TURNS = 100
PI_DEFAULT_TIMEOUT_SECONDS = 3600.0
PI_MIN_NODE_VERSION = (22, 19, 0)
PI_MIN_NODE_VERSION_TEXT = ".".join(str(part) for part in PI_MIN_NODE_VERSION)


def parse_node_version(value: str) -> tuple[int, int, int] | None:
    """Parse the exact semver form emitted by ``node --version``."""

    match = re.fullmatch(r"v([0-9]+)\.([0-9]+)\.([0-9]+)\s*", value)
    if match is None:
        return None
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
    )


@dataclass(frozen=True)
class ConfigLayers:
    """Immutable process and repository ``.env`` snapshots."""

    process: Mapping[str, str]
    dotenv: Mapping[str, str]

    @classmethod
    def from_repo(
        cls, repo_root: Path, process_environment: Mapping[str, str] | None = None
    ) -> "ConfigLayers":
        process = dict(os.environ if process_environment is None else process_environment)
        loaded = dotenv_values(Path(repo_root) / ".env")
        dotenv = {key: value for key, value in loaded.items() if value is not None}
        return cls(
            process=MappingProxyType(process),
            dotenv=MappingProxyType(dotenv),
        )

    def resolve(
        self,
        name: str,
        invocation: object,
        default: object,
        *,
        allow_empty_environment: bool = False,
    ) -> tuple[object, ValueSource]:
        def is_empty(value: object) -> bool:
            return isinstance(value, str) and not value.strip()

        if invocation is not None and (
            allow_empty_environment or not is_empty(invocation)
        ):
            return invocation, "invocation"
        if name in self.process and (
            allow_empty_environment or not is_empty(self.process[name])
        ):
            return self.process[name], "environment"
        if name in self.dotenv and (
            allow_empty_environment or not is_empty(self.dotenv[name])
        ):
            return self.dotenv[name], "environment"
        return default, "runtime-default"

    def materialize(self, target: MutableMapping[str, str]) -> None:
        for name, value in self.dotenv.items():
            target.setdefault(name, value)


@dataclass(frozen=True)
class AsterionRuntimeConfig:
    """Runtime-relative configuration before an installed client is built."""

    runtime: str
    provider: str | None
    model: str | None
    tools: str
    max_turns: int
    timeout_seconds: float | None
    thinking_level: str | None
    context_profile: str | None
    authentication_mode: str
    sources: Mapping[str, ValueSource]


@dataclass(frozen=True)
class DciPiPaths:
    """Resolved external Pi checkout paths owned by an Asterion DCI run."""

    repo_dir: Path
    package_dir: Path
    agent_dir: Path


@dataclass(frozen=True)
class DciPaths:
    """Resolved paths for one independent Asterion DCI installation."""

    repo_root: Path
    pi: DciPiPaths
    output_root: Path


@dataclass(frozen=True)
class DciRuntimeOptions:
    """Resolved shared DCI Pi runtime settings."""

    runtime: str = "pi"
    provider: str | None = None
    model: str | None = None
    tools: str = "read,bash"
    timeout_seconds: float | None = 3600.0
    runtime_context_level: str | None = None
    thinking_level: str | None = None
    node_max_old_space_size_mb: int | None = None
    keep_session: bool = False
    extra_args: tuple[str, ...] = ()
    authentication_mode: str = "saved-auth"


def load_asterion_dci_env(
    repo_root: Path, *, env_file: Path | None = None
) -> Path | None:
    """Load the product .env without overriding inherited process values."""

    env_path = (
        Path(repo_root).resolve() / ".env"
        if env_file is None
        else Path(env_file).expanduser().resolve()
    )
    if not env_path.is_file():
        return None
    load_dotenv(env_path, override=False)
    return env_path


def resolve_dci_paths(
    repo_root: Path, *, environment: Mapping[str, str] | None = None
) -> DciPaths:
    """Resolve shared DCI Pi paths and Asterion-compatible aliases."""

    root = Path(repo_root).resolve()
    configured_environment = os.environ if environment is None else environment
    pi_dir = _configured_path_shared(
        "DCI_PI_DIR", "ASTERION_DCI_PI_DIR", root / "pi", root=root,
        environment=configured_environment,
    )
    package_dir = _configured_path_shared(
        "DCI_PI_PACKAGE_DIR",
        "ASTERION_DCI_PI_PACKAGE_DIR",
        pi_dir / "packages" / "coding-agent",
        root=root,
        environment=configured_environment,
    )
    agent_dir = _configured_path_shared(
        "DCI_PI_AGENT_DIR",
        "ASTERION_DCI_PI_AGENT_DIR",
        Path(PI_DEFAULT_AGENT_DIR).expanduser(),
        root=root,
        environment=configured_environment,
    )
    output_root = _configured_output_path(
        "ASTERION_DCI_OUTPUT_ROOT", root / "outputs" / "asterion-dci-runs", root=root
    )
    return DciPaths(
        repo_root=root,
        pi=DciPiPaths(
            repo_dir=pi_dir,
            package_dir=package_dir,
            agent_dir=agent_dir,
        ),
        output_root=output_root,
    )


def resolve_dci_runtime_options(
    overrides: Mapping[str, object] | None = None,
) -> DciRuntimeOptions:
    """Resolve shared DCI runtime defaults with explicit values taking priority."""

    values = {} if overrides is None else dict(overrides)
    from asterion.dci.context_profiles import resolve_context_profile

    if "runtime_context_level" in values and "context_profile" not in values:
        values["context_profile"] = values["runtime_context_level"]
    resolved = resolve_asterion_runtime(values, ConfigLayers(os.environ, {}))
    context_profile = resolve_context_profile(
        resolved.context_profile
    )
    return DciRuntimeOptions(
        runtime=resolved.runtime,
        provider=resolved.provider,
        model=resolved.model,
        tools=resolved.tools,
        timeout_seconds=resolved.timeout_seconds,
        runtime_context_level=(context_profile.name if context_profile else None),
        thinking_level=resolved.thinking_level,
        node_max_old_space_size_mb=_optional_positive_int(
            _override_or_env(
                values, "node_max_old_space_size_mb", "DCI_NODE_MAX_OLD_SPACE_SIZE_MB"
            )
        ),
        keep_session=bool(values.get("keep_session", False)),
        extra_args=tuple(values.get("extra_args", ())),
        authentication_mode=resolved.authentication_mode,
    )


def resolve_asterion_runtime(
    overrides: Mapping[str, object], layers: ConfigLayers
) -> AsterionRuntimeConfig:
    """Resolve Asterion's public Pi/Claude runtime contract independently."""

    runtime_value, runtime_source = layers.resolve(
        "DCI_RUNTIME", overrides.get("runtime"), "pi"
    )
    runtime = _public_runtime_name(_required_text(runtime_value, default="pi"))
    if runtime not in {"pi", "claude-code"}:
        raise ValueError("Asterion runtime is unsupported")

    provider_default = PI_DEFAULT_PROVIDER if runtime == "pi" else None
    model_default = PI_DEFAULT_MODEL if runtime == "pi" else None
    tools_default = PI_DEFAULT_TOOLS if runtime == "pi" else "read,grep,glob"
    specs = (
        ("provider", "DCI_PROVIDER", provider_default, "agent.provider", False),
        ("model", "DCI_MODEL", model_default, "agent.model", False),
        ("tools", "DCI_TOOLS", tools_default, "agent.tools", False),
        ("max_turns", "DCI_MAX_TURNS", PI_DEFAULT_MAX_TURNS, "agent.max_turns", False),
        (
            "timeout_seconds",
            "DCI_RPC_TIMEOUT_SECONDS",
            PI_DEFAULT_TIMEOUT_SECONDS,
            "agent.timeout_seconds",
            True,
        ),
        (
            "thinking_level",
            "DCI_PI_THINKING_LEVEL",
            None,
            "agent.thinking_level",
            True,
        ),
        (
            "context_profile",
            "DCI_RUNTIME_CONTEXT_LEVEL",
            None,
            "context.profile",
            True,
        ),
    )
    values: dict[str, object] = {}
    sources: dict[str, ValueSource] = {"runtime": runtime_source}
    for field_name, env_name, default, source_name, allow_empty in specs:
        value, source = layers.resolve(
            env_name,
            overrides.get(field_name),
            default,
            allow_empty_environment=allow_empty,
        )
        values[field_name] = value
        sources[source_name] = source

    provider = _optional_text(values["provider"])
    model = _optional_text(values["model"])
    if runtime == "pi":
        provider = provider or PI_DEFAULT_PROVIDER
        model = model or PI_DEFAULT_MODEL
        authentication_mode = "saved-auth"
    else:
        if provider is None:
            authentication_mode = "subscription"
        elif provider in {"minimax", "minimax-cn"} and model is not None:
            authentication_mode = (
                "minimax-coding-plan"
                if provider == "minimax"
                else "minimax-cn-coding-plan"
            )
        else:
            raise ValueError("Claude Code runtime/provider pair is unsupported")

    from asterion.dci.context_profiles import resolve_context_profile

    raw_context_profile = values["context_profile"]
    context_profile = (
        None
        if raw_context_profile is None
        or (isinstance(raw_context_profile, str) and not raw_context_profile.strip())
        else resolve_context_profile(str(raw_context_profile)).name
    )
    return AsterionRuntimeConfig(
        runtime=runtime,
        provider=provider,
        model=model,
        tools=_required_text(values["tools"], default=tools_default),
        max_turns=_positive_int(values["max_turns"], default=PI_DEFAULT_MAX_TURNS),
        timeout_seconds=_timeout_value(values["timeout_seconds"]),
        thinking_level=_optional_text(values["thinking_level"]),
        context_profile=context_profile,
        authentication_mode=authentication_mode,
        sources=MappingProxyType(sources),
    )


def _public_runtime_name(value: str) -> str:
    return {
        "pi.reference": "pi",
        "claude-code.reference": "claude-code",
    }.get(value, value)


def _required_text(value: object, *, default: str) -> str:
    normalized = str(value).strip()
    return normalized or default


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _positive_int(value: object, *, default: int) -> int:
    if isinstance(value, str) and not value.strip():
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("DCI_MAX_TURNS must be an integer") from error
    if parsed <= 0:
        raise ValueError("DCI_MAX_TURNS must be greater than zero")
    return parsed


def _override_or_env(
    values: Mapping[str, object],
    key: str,
    environment_name: str,
    default: object = None,
) -> object:
    if key in values:
        return values[key]
    return os.environ.get(environment_name, default)


def _resolve_runtime(value: object) -> str:
    normalized = str(value).strip().lower()
    if normalized in {"", "pi", "pi.reference", "pi-ref", "pi_reference"}:
        return "pi"
    if normalized in {"claude-code", "claude-code.reference", "claude_code", "claudecode"}:
        return "claude-code"
    raise ValueError("DCI runtime is unsupported")


def _timeout_value(value: object) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        timeout_seconds = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("DCI RPC timeout must be a non-negative number") from error
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError("DCI RPC timeout must be a non-negative number")
    return timeout_seconds


def _optional_positive_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("DCI Node heap size must be a positive integer")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError("DCI Node heap size must be a positive integer") from error
    if parsed <= 0 or str(parsed) != str(value).strip():
        raise ValueError("DCI Node heap size must be a positive integer")
    return parsed


def _configured_path(name: str, default: Path, *, root: Path) -> Path:
    value = os.environ.get(name, "").strip()
    path = Path(value).expanduser() if value else default
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _configured_output_path(name: str, default: Path, *, root: Path) -> Path:
    """Resolve destination syntax without following security-relevant symlinks."""

    value = os.environ.get(name, "").strip()
    path = Path(value).expanduser() if value else default
    if not path.is_absolute():
        path = root / path
    return Path(os.path.normpath(path))


def _configured_path_shared(
    shared_name: str,
    alias_name: str,
    default: Path,
    *,
    root: Path,
    environment: Mapping[str, str] = os.environ,
) -> Path:
    value = (
        environment.get(shared_name, "").strip()
        or environment.get(alias_name, "").strip()
    )
    path = Path(value).expanduser() if value else default
    if not path.is_absolute():
        path = root / path
    return Path(os.path.normpath(path))
