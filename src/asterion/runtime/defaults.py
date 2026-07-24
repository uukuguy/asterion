"""Explicit first-party runtime factories for the Asterion CLI."""

from __future__ import annotations

import math
import os
import shutil
from collections.abc import Mapping
from pathlib import Path

from asterion.runtime.factory import (
    RuntimeFactoryBinding,
    RuntimeFactoryContext,
    RuntimeFactoryError,
    RuntimeFactoryRegistry,
)
from asterion.runtimes.claude_code import ClaudeCodeRuntimeClient
from asterion.runtimes.pi import PiRuntimeClient


PI_CAPABILITIES = ("filesystem.read", "shell")
CLAUDE_CAPABILITIES = ("claude.tool.glob", "claude.tool.grep", "filesystem.read")
_CLAUDE_PROVIDER_CONFIG = {
    "minimax": ("https://api.minimax.io/anthropic", "MINIMAX_API_KEY"),
    "minimax-cn": ("https://api.minimaxi.com/anthropic", "MINIMAX_CN_API_KEY"),
}
_CLAUDE_MODEL_ENVIRONMENT_NAMES = (
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
)
_CLAUDE_OPERATIONAL_ENVIRONMENT_NAMES = (
    "PATH",
    "HOME",
    "TMPDIR",
    "TMP",
    "TEMP",
    "LANG",
    "LC_ALL",
    "TERM",
    "SHELL",
    "USER",
    "LOGNAME",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NODE_EXTRA_CA_CERTS",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)


def default_runtime_factory_registry() -> RuntimeFactoryRegistry:
    """Return the host-owned runtime bindings shipped with Asterion."""

    return RuntimeFactoryRegistry(
        (
            RuntimeFactoryBinding(
                runtime_id="pi.reference",
                capabilities=PI_CAPABILITIES,
                factory=_create_pi_runtime,
            ),
            RuntimeFactoryBinding(
                runtime_id="claude-code.reference",
                capabilities=CLAUDE_CAPABILITIES,
                factory=_create_claude_code_runtime,
            ),
        )
    )


def _create_pi_runtime(context: RuntimeFactoryContext) -> PiRuntimeClient:
    if context.runtime_id != "pi.reference":
        raise RuntimeFactoryError("runtime factory context is invalid")
    working_root = Path.cwd()
    pi_dir = _configured_path("DCI_PI_DIR", working_root / "pi", root=working_root)
    package_dir = _configured_path(
        "DCI_PI_PACKAGE_DIR", pi_dir / "packages/coding-agent", root=working_root
    )
    agent_dir = _configured_path("DCI_PI_AGENT_DIR", pi_dir / ".pi/agent", root=working_root)
    runtime_cwd = _configured_path("ASTERION_RUNTIME_CWD", working_root, root=working_root)
    cli = package_dir / "dist/cli.js"
    node = shutil.which("node")
    if node is None or not cli.is_file() or not agent_dir.is_dir() or not runtime_cwd.is_dir():
        raise RuntimeFactoryError("Pi reference runtime is unavailable")

    command = [node, str(cli), "--mode", "rpc"]
    for option, option_name in (
        ("--provider", "provider"),
        ("--model", "model"),
        ("--tools", "tools"),
    ):
        raw_value = context.options.get(option_name)
        value = "" if raw_value is None else str(raw_value).strip()
        if value:
            command.extend((option, value))
    environment = os.environ.copy()
    environment["PI_CODING_AGENT_DIR"] = str(agent_dir)
    return PiRuntimeClient(
        command=command,
        cwd=runtime_cwd,
        capabilities=PI_CAPABILITIES,
        env=environment,
    )


def _create_claude_code_runtime(
    context: RuntimeFactoryContext,
) -> ClaudeCodeRuntimeClient:
    if context.runtime_id != "claude-code.reference":
        raise RuntimeFactoryError("runtime factory context is invalid")
    executable = _configured_executable("ASTERION_CLAUDE_EXECUTABLE", "claude")
    runtime_cwd = _configured_path("ASTERION_RUNTIME_CWD", Path.cwd(), root=Path.cwd())
    evidence_root = _configured_path(
        "ASTERION_CLAUDE_OUTPUT_ROOT",
        Path.cwd() / "outputs/asterion-claude-runs",
        root=Path.cwd(),
    )
    if executable is None or not runtime_cwd.is_dir():
        raise RuntimeFactoryError("Claude Code runtime is unavailable")
    provider = _option_text(context, "provider")
    model = _option_text(context, "model")
    environment, authentication_mode = _claude_provider_environment(
        os.environ, provider=provider, model=model
    )
    configured_mode = _option_text(context, "authentication_mode")
    if configured_mode != authentication_mode:
        raise RuntimeFactoryError("Claude Code authentication configuration is invalid")
    default_timeout_seconds = _configured_timeout_option(
        context.options.get("timeout_seconds")
    )
    raw_max_turns = os.environ.get("DCI_MAX_TURNS", "4").strip()
    try:
        max_turns = int(raw_max_turns)
    except ValueError:
        raise RuntimeFactoryError("Claude Code max turns configuration is invalid") from None
    if max_turns <= 0 or str(max_turns) != raw_max_turns:
        raise RuntimeFactoryError("Claude Code max turns configuration is invalid")
    tools = _claude_tools(_option_text(context, "tools"))
    reasoning = _option_text(context, "thinking_level")
    if reasoning not in {None, "low", "medium", "high"}:
        raise RuntimeFactoryError("Claude Code reasoning configuration is invalid")
    context_profile = _option_text(context, "context_profile")
    if context_profile not in {None, "level3"}:
        raise RuntimeFactoryError("Claude Code context configuration is invalid")
    return ClaudeCodeRuntimeClient(
        executable=executable,
        cwd=runtime_cwd,
        environment=environment,
        default_timeout_seconds=default_timeout_seconds,
        max_turns=max_turns,
        tools=tools,
        evidence_root=evidence_root,
        agent_provider=provider,
        agent_model=model,
        reasoning=reasoning,
        context_profile=context_profile,
    )
def _coerce_timeout_seconds(value: object) -> float | None:
    if value is None:
        return None
    try:
        timeout_seconds = float(value)
    except (TypeError, ValueError) as error:
        raise RuntimeFactoryError("Claude Code timeout configuration is invalid") from error
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise RuntimeFactoryError("Claude Code timeout configuration is invalid")
    return timeout_seconds or None


def _claude_provider_environment(
    environment: Mapping[str, str],
    provider: str | None,
    model: str | None,
) -> tuple[dict[str, str], str]:
    provider = provider.strip() if provider is not None else None
    model = model.strip() if model is not None else None
    provider = provider or None
    model = model or None
    native_environment = {
        name: environment[name]
        for name in _CLAUDE_OPERATIONAL_ENVIRONMENT_NAMES
        if environment.get(name)
    }
    if provider is None:
        if any(
            environment.get(name, "").strip()
            for name in (
                "MINIMAX_API_KEY",
                "MINIMAX_CN_API_KEY",
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_AUTH_TOKEN",
                "ANTHROPIC_BASE_URL",
            )
        ):
            raise RuntimeFactoryError("Claude Code authentication configuration is ambiguous")
        return native_environment, "subscription"
    if provider is None or model is None:
        raise RuntimeFactoryError("Claude Code provider configuration is unavailable")
    if environment.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip():
        raise RuntimeFactoryError("Claude Code authentication configuration is ambiguous")
    provider_config = _CLAUDE_PROVIDER_CONFIG.get(provider)
    if provider_config is None:
        raise RuntimeFactoryError("Claude Code provider configuration is unsupported")

    base_url, key_name = provider_config
    api_key = environment.get(key_name, "").strip()
    if not api_key:
        raise RuntimeFactoryError("Claude Code provider configuration is unavailable")

    native_environment["ANTHROPIC_BASE_URL"] = base_url
    if not api_key.startswith("sk-cp-"):
        native_environment["ANTHROPIC_API_KEY"] = api_key
        native_environment.pop("ANTHROPIC_AUTH_TOKEN", None)
    else:
        native_environment["ANTHROPIC_AUTH_TOKEN"] = api_key
        native_environment.pop("ANTHROPIC_API_KEY", None)
    for name in _CLAUDE_MODEL_ENVIRONMENT_NAMES:
        native_environment[name] = model
    for name in (
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_USE_VERTEX",
    ):
        native_environment.pop(name, None)
    native_environment["API_TIMEOUT_MS"] = "3000000"
    native_environment["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    mode = (
        "minimax-coding-plan"
        if provider == "minimax"
        else "minimax-cn-coding-plan"
    )
    return native_environment, mode


def _option_text(context: RuntimeFactoryContext, name: str) -> str | None:
    value = context.options.get(name)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _claude_tools(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ("Read", "Grep", "Glob")
    normalized = tuple(part.strip().lower() for part in value.split(","))
    if not normalized or any(not part for part in normalized):
        raise RuntimeFactoryError("Claude Code tools configuration is invalid")
    mapping = {"read": "Read", "grep": "Grep", "glob": "Glob"}
    if any(part not in mapping for part in normalized) or len(set(normalized)) != len(normalized):
        raise RuntimeFactoryError("Claude Code tools configuration is invalid")
    return tuple(mapping[part] for part in normalized)


def _configured_timeout_option(value: object) -> float | None:
    if value is None:
        return None
    return _configured_timeout_seconds({"DCI_RPC_TIMEOUT_SECONDS": str(value)})


def _configured_timeout_seconds(environment: Mapping[str, str]) -> float | None:
    value = environment.get("DCI_RPC_TIMEOUT_SECONDS", "3600").strip()
    try:
        timeout_seconds = float(value)
    except ValueError:
        raise RuntimeFactoryError("Claude Code timeout configuration is invalid") from None
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise RuntimeFactoryError("Claude Code timeout configuration is invalid")
    return timeout_seconds or None


def _configured_path(name: str, default: Path, *, root: Path) -> Path:
    value = os.environ.get(name, "").strip()
    path = Path(value).expanduser() if value else default
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _configured_executable(name: str, default: str) -> str | None:
    value = os.environ.get(name, default).strip()
    if not value:
        return None
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        return str(candidate) if candidate.is_file() else None
    return shutil.which(value)
