"""Explicit first-party runtime factories for the Asterion CLI."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import stat
from collections.abc import Mapping
from pathlib import Path

from asterion.runtime.factory import (
    RuntimeFactoryBinding,
    RuntimeFactoryContext,
    RuntimeFactoryError,
    RuntimeFactoryRegistry,
)
from asterion.runtime.working_directory import ProcessDirectoryAuthority
from asterion.runtimes.claude_code import ClaudeCodeRuntimeClient
from asterion.runtimes.pi import PiRuntimeClient, prepare_pi_evidence_root
from asterion.runtimes.prime_agent import (
    PRIME_IPYTHON_CAPABILITY,
    PRIME_P1_PROFILE,
    PRIME_P2_PROFILE,
    PRIME_RUNTIME_ID,
    PrimeAgentRuntimeClient,
)
from asterion.runtimes.prime_agent_host import PrimeSmallVerificationService


PI_CAPABILITIES = ("filesystem.read", "pi.tool.grep")
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
            RuntimeFactoryBinding(
                runtime_id=PRIME_RUNTIME_ID,
                capabilities=(PRIME_IPYTHON_CAPABILITY,),
                factory=_create_prime_agent_runtime,
            ),
        )
    )


def _create_prime_agent_runtime(context: RuntimeFactoryContext) -> PrimeAgentRuntimeClient:
    if (
        context.provider_id != "prime-agent"
        or context.application_version != "1.0.0"
        or context.runtime_id != PRIME_RUNTIME_ID
        or context.options
    ):
        raise RuntimeFactoryError("Prime runtime configuration is invalid")
    routes = {
        "prime.ipython-coding": ("prime.ipython-production", PRIME_P1_PROFILE),
        "prime.programmatic-long-context": (
            "prime.programmatic-long-context-development",
            PRIME_P2_PROFILE,
        ),
    }
    try:
        host_key, profile = routes[context.application_id]
    except KeyError:
        raise RuntimeFactoryError("Prime runtime configuration is invalid") from None
    if set(context.host_services) != {host_key}:
        raise RuntimeFactoryError("Prime runtime configuration is invalid")
    service = context.host_services[host_key]
    if not isinstance(service, PrimeSmallVerificationService):
        raise RuntimeFactoryError("Prime runtime configuration is invalid")
    return PrimeAgentRuntimeClient(service, profile=profile)


def _create_pi_runtime(context: RuntimeFactoryContext) -> PiRuntimeClient:
    if context.runtime_id != "pi.reference":
        raise RuntimeFactoryError("runtime factory context is invalid")
    allowed = {
        "command",
        "context_profile",
        "cwd",
        "cwd_host_capability",
        "environment",
        "evidence_root",
        "max_turns",
        "model",
        "provider",
        "tools",
    }
    required = {
        "command",
        "environment",
        "evidence_root",
        "max_turns",
        "tools",
    }
    has_cwd = "cwd" in context.options
    has_host_cwd = "cwd_host_capability" in context.options
    directory_authorities = _directory_authorities(context)
    if (
        set(context.options) - allowed
        or not required.issubset(context.options)
        or has_cwd == has_host_cwd
        or (directory_authorities and has_cwd)
        or (directory_authorities and not has_host_cwd)
    ):
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    command = list(_pi_command(context.options["command"]))
    cwd_authority = (
        _host_directory_authority(context)
        if has_host_cwd
        else None
    )
    if cwd_authority is None:
        runtime_cwd: Path | None = _pi_exact_path(
            context.options["cwd"], require_directory=True
        )
    else:
        runtime_cwd = None
    evidence_root_path = _pi_exact_path(
        context.options["evidence_root"], require_directory=False
    )
    environment = _pi_environment(context.options["environment"])
    tools = context.options["tools"]
    if type(tools) is not str or tools != "read,grep":
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    normalized_tools = ("read", "grep")
    provider = _pi_identity_option(context.options.get("provider"))
    model = _pi_identity_option(context.options.get("model"))
    if (provider is None) != (model is None):
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    context_profile = context.options.get("context_profile")
    if context_profile not in {None, "level3"}:
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    raw_max_turns = context.options["max_turns"]
    if type(raw_max_turns) is not str:
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    try:
        max_turns = int(raw_max_turns)
    except ValueError:
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid") from None
    if max_turns <= 0 or str(max_turns) != raw_max_turns:
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    try:
        evidence_root = prepare_pi_evidence_root(evidence_root_path)
    except ValueError:
        raise RuntimeFactoryError(
            "Pi reference runtime configuration is invalid"
        ) from None

    for option, value in (
        ("--provider", provider),
        ("--model", model),
        ("--tools", ",".join(normalized_tools)),
    ):
        if value is not None:
            command.extend((option, value))
    return PiRuntimeClient(
        command=command,
        cwd=runtime_cwd,
        cwd_authority=cwd_authority,
        capabilities=PI_CAPABILITIES,
        env=environment,
        max_turns=max_turns,
        evidence_root=evidence_root,
        provider=provider,
        model=model,
        tools=normalized_tools,
        context_profile=context_profile,
    )


def _host_directory_authority(
    context: RuntimeFactoryContext,
) -> ProcessDirectoryAuthority:
    capability_id = context.options["cwd_host_capability"]
    if (
        type(capability_id) is not str
        or re.fullmatch(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*", capability_id)
        is None
    ):
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    try:
        service = context.host_services[capability_id]
    except Exception:
        raise RuntimeFactoryError(
            "runtime host directory service is unavailable"
        ) from None
    if not isinstance(service, ProcessDirectoryAuthority):
        raise RuntimeFactoryError("runtime host directory service is invalid")
    authorities = _directory_authorities(context)
    if (
        len(authorities) != 1
        or authorities[0][0] != capability_id
        or authorities[0][1] is not service
    ):
        raise RuntimeFactoryError("runtime host directory service is ambiguous")
    try:
        path = service.directory_path
    except Exception:
        raise RuntimeFactoryError(
            "runtime host directory service is unavailable"
        ) from None
    if not isinstance(path, Path):
        raise RuntimeFactoryError("runtime host directory service is invalid")
    _pi_exact_path(str(path), require_directory=True)
    return service


def _directory_authorities(
    context: RuntimeFactoryContext,
) -> tuple[tuple[str, ProcessDirectoryAuthority], ...]:
    return tuple(
        (capability_id, service)
        for capability_id, service in context.host_services.items()
        if isinstance(service, ProcessDirectoryAuthority)
    )


def _pi_command(value: str) -> tuple[str, ...]:
    parsed = _pi_exact_json(value, sort_keys=False)
    if (
        not isinstance(parsed, list)
        or not parsed
        or any(type(item) is not str or not item for item in parsed)
    ):
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    executable = _pi_exact_path(parsed[0], require_directory=False)
    try:
        details = executable.stat(follow_symlinks=False)
    except OSError:
        raise RuntimeFactoryError("Pi reference runtime is unavailable") from None
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) & 0o111 == 0
        or not os.access(executable, os.X_OK)
    ):
        raise RuntimeFactoryError("Pi reference runtime is unavailable")
    return tuple(parsed)


def _pi_exact_path(value: str, *, require_directory: bool) -> Path:
    if type(value) is not str:
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    path = Path(value)
    if (
        not path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts[1:])
        or str(path.resolve(strict=False)) != value
    ):
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    current = Path(path.anchor)
    try:
        details = current.stat(follow_symlinks=False)
    except OSError:
        raise RuntimeFactoryError("Pi reference runtime is unavailable") from None
    for component in path.parts[1:]:
        current /= component
        try:
            details = current.stat(follow_symlinks=False)
        except FileNotFoundError:
            if current == path and not require_directory:
                return path
            raise RuntimeFactoryError("Pi reference runtime is unavailable") from None
        except OSError:
            raise RuntimeFactoryError("Pi reference runtime is unavailable") from None
        if stat.S_ISLNK(details.st_mode):
            raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    if require_directory and not stat.S_ISDIR(details.st_mode):
        raise RuntimeFactoryError("Pi reference runtime is unavailable")
    return path


def _pi_environment(value: str) -> dict[str, str]:
    parsed = _pi_exact_json(value, sort_keys=True)
    if not isinstance(parsed, dict) or any(
        type(key) is not str
        or not key
        or type(item) is not str
        for key, item in parsed.items()
    ):
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    return dict(parsed)


def _pi_exact_json(value: str, *, sort_keys: bool) -> object:
    if type(value) is not str:
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError
            result[key] = item
        return result

    try:
        parsed = json.loads(value, object_pairs_hook=unique_object)
    except (TypeError, ValueError):
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid") from None
    canonical = json.dumps(
        parsed,
        ensure_ascii=False,
        sort_keys=sort_keys,
        separators=(",", ":"),
    )
    if canonical != value:
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    return parsed


def _pi_identity_option(value: str | None) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+-]*", value) is None
    ):
        raise RuntimeFactoryError("Pi reference runtime configuration is invalid")
    return value


def _create_claude_code_runtime(
    context: RuntimeFactoryContext,
) -> ClaudeCodeRuntimeClient:
    if context.runtime_id != "claude-code.reference":
        raise RuntimeFactoryError("runtime factory context is invalid")
    allowed = {
        "authentication_mode",
        "context_profile",
        "cwd",
        "cwd_host_capability",
        "evidence_root",
        "model",
        "provider",
        "thinking_level",
        "timeout_seconds",
        "tools",
    }
    if set(context.options) - allowed:
        raise RuntimeFactoryError("Claude Code runtime configuration is invalid")
    executable = _configured_executable("ASTERION_CLAUDE_EXECUTABLE", "claude")
    has_host_cwd = "cwd_host_capability" in context.options
    directory_authorities = _directory_authorities(context)
    has_direct_cwd = "cwd" in context.options
    has_ambient_cwd = bool(
        os.environ.get("ASTERION_RUNTIME_CWD", "").strip()
    )
    if (
        (directory_authorities and not has_host_cwd)
        or (directory_authorities and (has_direct_cwd or has_ambient_cwd))
    ):
        raise RuntimeFactoryError("Claude Code runtime configuration is invalid")
    if has_host_cwd:
        if (
            has_direct_cwd
            or has_ambient_cwd
            or "evidence_root" not in context.options
        ):
            raise RuntimeFactoryError("Claude Code runtime configuration is invalid")
        cwd_authority: ProcessDirectoryAuthority | None = (
            _host_directory_authority(context)
        )
        runtime_cwd: Path | None = None
        evidence_root = _pi_exact_path(
            context.options["evidence_root"], require_directory=False
        )
    else:
        if "cwd_host_capability" in context.options:
            raise RuntimeFactoryError("Claude Code runtime configuration is invalid")
        current = Path.cwd()
        if "cwd" in context.options:
            runtime_cwd = _pi_exact_path(
                context.options["cwd"], require_directory=True
            )
        else:
            runtime_cwd = _configured_path(
                "ASTERION_RUNTIME_CWD", current, root=current
            )
        cwd_authority = None
        if "evidence_root" in context.options:
            evidence_root = _pi_exact_path(
                context.options["evidence_root"], require_directory=False
            )
        else:
            evidence_root = _configured_path(
                "ASTERION_CLAUDE_OUTPUT_ROOT",
                current / "outputs/asterion-claude-runs",
                root=current,
            )
    if executable is None or (
        runtime_cwd is not None and not runtime_cwd.is_dir()
    ):
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
        cwd_authority=cwd_authority,
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


def _configured_timeout_option(value: str | None) -> float | None:
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
