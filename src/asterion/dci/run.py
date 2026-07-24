"""Native artifact boundary for an independent Asterion DCI Pi run."""

from __future__ import annotations

import hashlib
import json
import math
import time
import sys
import threading
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from asterion.dci.config import DciPaths
from asterion.dci.pi_rpc import PiRpcClient, expand_extra_args
from asterion.dci.provenance import format_pi_revision_warning
from asterion.runtime.host import RunEvent

if TYPE_CHECKING:
    from asterion.dci.artifacts import DciConversationFeatures
    from asterion.dci.config import DciRuntimeOptions
    from asterion.dci.context_profiles import DciContextProfile


@dataclass(frozen=True)
class DciRunRequest:
    """Inputs for one new Pi-backed DCI research run."""

    run_id: str
    question: str
    cwd: Path
    provider: str | None = None
    model: str | None = None
    tools: str = "read,bash"
    max_turns: int | None = None
    timeout_seconds: float | None = 3600.0
    runtime_context_level: str | None = None
    thinking_level: str | None = None
    node_max_old_space_size_mb: int | None = None
    keep_session: bool = False
    extra_args: tuple[str, ...] = ()
    prelude_questions: tuple[str, ...] = ()
    show_tools: bool = False
    system_prompt_file: Path | None = None
    append_system_prompt_file: Path | None = None
    conversation_features: DciConversationFeatures | None = None
    pi_package_dir: Path | None = None
    pi_agent_dir: Path | None = None
    pi_session_file: Path | None = None
    pi_session_id: str | None = None
    resume: bool = False
    stream_text: bool = True

    @property
    def context_profile(self) -> DciContextProfile | None:
        """Resolve the canonical paper profile selected by this request."""

        from asterion.dci.context_profiles import resolve_context_profile

        return resolve_context_profile(self.runtime_context_level)


@dataclass(frozen=True)
class DciRunResult:
    """Completed native DCI run plus its protocol-normalized events."""

    output_dir: Path
    final_text: str
    events: tuple[RunEvent, ...]
    status: str


class DciRunError(RuntimeError):
    """Safe public error for a failed Pi execution."""


_RESUME_TIMEOUT_UNSET = object()
_THINKING_LEVELS = {"off", "minimal", "low", "medium", "high", "xhigh"}


def validate_dci_run_request(
    request: DciRunRequest, paths: DciPaths | None = None
) -> None:
    """Validate every behavior-affecting request value before filesystem mutation."""

    def text(value: object, *, optional: bool = False) -> None:
        if value is None and optional:
            return
        if not isinstance(value, str) or not value.strip():
            raise ValueError("DCI run request is invalid")

    text(request.run_id)
    text(request.question)
    if (
        not isinstance(request.prelude_questions, tuple)
        or len(request.prelude_questions) > 12
        or any(
            not isinstance(value, str) or not value.strip()
            for value in request.prelude_questions
        )
        or request.prelude_questions
        and (
            request.resume
            or not request.keep_session
            or request.context_profile is None
        )
    ):
        raise ValueError("DCI run request is invalid")
    text(request.tools)
    text(request.provider, optional=True)
    text(request.model, optional=True)
    text(request.runtime_context_level, optional=True)
    if request.runtime_context_level is not None:
        from asterion.dci.context_profiles import resolve_context_profile

        resolve_context_profile(request.runtime_context_level)
    text(request.thinking_level, optional=True)
    text(request.pi_session_id, optional=True)
    if request.thinking_level not in _THINKING_LEVELS | {None}:
        raise ValueError("DCI run request is invalid")
    if request.max_turns is not None and (
        isinstance(request.max_turns, bool)
        or not isinstance(request.max_turns, int)
        or request.max_turns <= 0
    ):
        raise ValueError("DCI run request is invalid")
    if request.timeout_seconds is not None and (
        isinstance(request.timeout_seconds, bool)
        or not isinstance(request.timeout_seconds, float)
        or not math.isfinite(request.timeout_seconds)
        or request.timeout_seconds < 0
    ):
        raise ValueError("DCI run request is invalid")
    if request.node_max_old_space_size_mb is not None and (
        isinstance(request.node_max_old_space_size_mb, bool)
        or not isinstance(request.node_max_old_space_size_mb, int)
        or request.node_max_old_space_size_mb <= 0
    ):
        raise ValueError("DCI run request is invalid")
    for value in (
        request.keep_session,
        request.show_tools,
        request.resume,
        request.stream_text,
    ):
        if type(value) is not bool:
            raise ValueError("DCI run request is invalid")
    if not isinstance(request.extra_args, tuple) or any(
        not isinstance(value, str) or not value for value in request.extra_args
    ):
        raise ValueError("DCI run request is invalid")
    if request.context_profile is not None:
        reserved = (
            "--extension",
            "--dci-context-profile",
            "--dci-context-contract",
        )
        try:
            expanded_extra_args = expand_extra_args(request.extra_args)
        except ValueError:
            raise ValueError("DCI run request is invalid") from None
        if any(
            token == flag or token.startswith(f"{flag}=")
            for token in expanded_extra_args
            for flag in reserved
        ):
            raise ValueError("DCI reserved context extension argument is invalid")
    for value in (
        request.cwd,
        request.system_prompt_file,
        request.append_system_prompt_file,
        request.pi_package_dir,
        request.pi_agent_dir,
        request.pi_session_file,
    ):
        if value is not None and (
            not isinstance(value, Path) or not value.is_absolute()
        ):
            raise ValueError("DCI run request is invalid")
    if (request.pi_session_file is None) != (request.pi_session_id is None):
        raise ValueError("DCI run request is invalid")
    if request.context_profile is None and request.pi_session_file is not None:
        raise ValueError("DCI run request is invalid")
    if request.context_profile is not None:
        if request.resume and (
            not request.keep_session or request.pi_session_file is None
        ):
            raise ValueError("DCI run request is invalid")
        if not request.resume and request.pi_session_file is not None:
            raise ValueError("DCI run request is invalid")
    if request.conversation_features is not None:
        from asterion.dci.artifacts import DciConversationFeatures

        if not isinstance(request.conversation_features, DciConversationFeatures):
            raise ValueError("DCI run request is invalid")
    if paths is not None:
        for value in (
            paths.repo_root,
            paths.output_root,
            paths.pi.repo_dir,
            paths.pi.package_dir,
            paths.pi.agent_dir,
        ):
            if not isinstance(value, Path) or not value.is_absolute():
                raise ValueError("DCI run request is invalid")
        if (
            request.pi_package_dir is not None
            and request.pi_package_dir != paths.pi.package_dir
        ):
            raise ValueError("DCI run request is invalid")
        if request.pi_session_file is not None:
            session_file = request.pi_session_file
            try:
                resolved_session = session_file.resolve(strict=True)
                resolved_agent = paths.pi.agent_dir.resolve(strict=False)
            except OSError:
                raise ValueError("DCI run request is invalid") from None
            if (
                session_file.is_symlink()
                or not resolved_session.is_file()
                or not resolved_session.is_relative_to(resolved_agent)
            ):
                raise ValueError("DCI run request is invalid")
        if (
            request.pi_agent_dir is not None
            and request.pi_agent_dir != paths.pi.agent_dir
        ):
            raise ValueError("DCI run request is invalid")


def request_from_runtime_options(
    options: DciRuntimeOptions,
    *,
    run_id: str,
    question: str,
    cwd: Path,
    stream_text: bool = True,
) -> DciRunRequest:
    """Convert resolved shared runtime settings into one immutable native request."""

    request = DciRunRequest(
        run_id=run_id,
        question=question,
        cwd=cwd,
        provider=options.provider,
        model=options.model,
        tools=options.tools,
        timeout_seconds=options.timeout_seconds,
        runtime_context_level=options.runtime_context_level,
        thinking_level=options.thinking_level,
        node_max_old_space_size_mb=options.node_max_old_space_size_mb,
        keep_session=options.keep_session,
        extra_args=options.extra_args,
        stream_text=stream_text,
    )
    try:
        validate_dci_run_request(request)
    except ValueError:
        raise DciRunError("DCI resume validation failed") from None
    return request


def resume_request_from_output_dir(
    output_dir: Path,
    *,
    extra_args: tuple[str, ...] | None = None,
    timeout_seconds: float | None | object = _RESUME_TIMEOUT_UNSET,
    _directory_fd: int | None = None,
) -> DciRunRequest:
    """Reconstruct a safe immutable resume request from native run state."""

    from asterion.dci.artifacts import (
        DciArtifactError,
        DciRunLock,
        DciConversationFeatures,
        _read_json_object_at,
        extra_args_fingerprint,
    )

    lock = None
    try:
        lock = (
            DciRunLock.acquire(Path(output_dir).absolute(), create=False)
            if _directory_fd is None
            else DciRunLock.acquire_fd(
                _directory_fd, path=Path(output_dir).absolute(), wait=False
            )
        )
        state = _read_json_object_at(lock._directory_fd, "state.json")
    except (DciArtifactError, OSError, ValueError):
        raise DciRunError("DCI resume validation failed") from None
    finally:
        if lock is not None:
            lock.release()
    status = _required_string(state, "status")
    if status not in {"failed", "incomplete", "running"}:
        raise DciRunError("DCI resume validation failed")
    run_id = _required_string(state, "run_id")
    question = _required_string(state, "question")
    cwd = Path(_required_string(state, "cwd"))
    provider = _optional_string(state, "provider")
    model = _optional_string(state, "model")
    tools = _required_string(state, "tools")
    max_turns = _optional_int(state, "max_turns")
    persisted_timeout = _optional_timeout(state, "timeout_seconds")
    runtime_context_level = _optional_string(state, "runtime_context_level")
    thinking_level = _optional_string(state, "thinking_level")
    node_max_old_space_size_mb = _optional_positive_int(
        state, "node_max_old_space_size_mb"
    )
    keep_session = _required_bool(state, "keep_session")
    extra_args_count = _required_nonnegative_int(state, "extra_args_count")
    prelude_count = _required_nonnegative_int(state, "prelude_question_count")
    prelude_fingerprint = _required_string(
        state, "prelude_questions_fingerprint"
    )
    if prelude_count != 0 or prelude_fingerprint != prelude_questions_fingerprint(()):
        raise DciRunError("DCI resume validation failed")
    persisted_fingerprint = _required_string(state, "extra_args_fingerprint")
    if extra_args is None:
        if extra_args_count:
            raise DciRunError("DCI resume validation failed")
        supplied_extra_args: tuple[str, ...] = ()
    else:
        supplied_extra_args = extra_args
    try:
        supplied_fingerprint = extra_args_fingerprint(supplied_extra_args)
    except ValueError:
        raise DciRunError("DCI resume validation failed") from None
    if (
        len(supplied_extra_args) != extra_args_count
        or supplied_fingerprint != persisted_fingerprint
    ):
        raise DciRunError("DCI resume validation failed")
    show_tools = _required_bool(state, "show_tools")
    system_prompt = _optional_path(state, "system_prompt_file")
    append_system_prompt = _optional_path(state, "append_system_prompt_file")
    stream_text = _required_bool(state, "stream_text")
    if "conversation_features" not in state:
        raise DciRunError("DCI resume validation failed")
    try:
        conversation_features = DciConversationFeatures.from_mapping(
            state.get("conversation_features")
        )
    except ValueError:
        raise DciRunError("DCI resume validation failed") from None
    pi_package_dir = Path(_required_string(state, "pi_package_dir"))
    pi_agent_dir = Path(_required_string(state, "pi_agent_dir"))
    session = state.get("pi_context_session")
    if runtime_context_level is None:
        if session is not None:
            raise DciRunError("DCI resume validation failed")
        pi_session_file = None
        pi_session_id = None
    else:
        if not isinstance(session, dict) or set(session) != {"session_file", "session_id"}:
            raise DciRunError("DCI resume validation failed")
        pi_session_file = Path(_required_string(session, "session_file"))
        pi_session_id = _required_string(session, "session_id")
    if timeout_seconds is _RESUME_TIMEOUT_UNSET:
        resumed_timeout = persisted_timeout
    elif timeout_seconds is None:
        resumed_timeout = None
    elif (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, float)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds < 0
    ):
        raise DciRunError("DCI resume validation failed")
    else:
        resumed_timeout = float(timeout_seconds)
    candidate = DciRunRequest(
        run_id=run_id,
        question=question,
        cwd=cwd,
        provider=provider,
        model=model,
        tools=tools,
        max_turns=max_turns,
        timeout_seconds=resumed_timeout,
        runtime_context_level=runtime_context_level,
        thinking_level=thinking_level,
        node_max_old_space_size_mb=node_max_old_space_size_mb,
        keep_session=keep_session,
        extra_args=supplied_extra_args,
        show_tools=show_tools,
        system_prompt_file=system_prompt,
        append_system_prompt_file=append_system_prompt,
        conversation_features=conversation_features,
        pi_package_dir=pi_package_dir,
        pi_agent_dir=pi_agent_dir,
        pi_session_file=pi_session_file,
        pi_session_id=pi_session_id,
        resume=True,
        stream_text=stream_text,
    )
    try:
        validate_dci_run_request(candidate)
    except (TypeError, ValueError):
        raise DciRunError("DCI resume validation failed") from None
    return candidate


def run_pi_research(
    paths: DciPaths,
    request: DciRunRequest,
    *,
    output_dir: Path | None = None,
    conversation_features: DciConversationFeatures | None = None,
    _cancel_event: threading.Event | None = None,
    _output_directory_fd: int | None = None,
    _resource_fds: tuple[int, ...] = (),
    _system_prompt_override: Path | None = None,
    _append_system_prompt_override: Path | None = None,
) -> DciRunResult:
    """Run Pi once and persist complete native conversation evidence."""

    from asterion.dci.artifacts import DciArtifactError, DciRunRecorder

    if conversation_features is not None:
        if (
            request.conversation_features is not None
            and request.conversation_features != conversation_features
        ):
            raise DciRunError(
                "DCI resume validation failed"
                if request.resume
                else "DCI run request is invalid"
            )
        request = replace(request, conversation_features=conversation_features)
    try:
        validate_dci_run_request(request, paths)
    except ValueError:
        raise DciRunError(
            "DCI resume validation failed"
            if request.resume
            else "DCI run request is invalid"
        ) from None
    destination = (
        Path(output_dir)
        if output_dir is not None
        else paths.output_root / request.run_id
    )
    destination = destination.absolute()
    resource_stack = ExitStack()
    context_extension = None
    context_profile = request.context_profile
    if context_profile is not None:
        from asterion.dci.context_extension import (
            ContextExtensionError,
            resolve_context_extension,
        )

        try:
            context_extension = resource_stack.enter_context(
                resolve_context_extension()
            )
        except ContextExtensionError:
            resource_stack.close()
            raise DciRunError(
                "DCI resume validation failed"
                if request.resume
                else "DCI context extension is invalid"
            ) from None
    try:
        recorder = DciRunRecorder(
            output_dir=destination,
            request=request,
            paths=paths,
            features=request.conversation_features,
            resume=request.resume,
            directory_fd=_output_directory_fd,
            context_extension=context_extension,
        )
    except DciArtifactError as exc:
        resource_stack.close()
        message = "DCI resume validation failed" if request.resume else str(exc)
        raise DciRunError(message) from None
    except ValueError:
        resource_stack.close()
        message = (
            "DCI resume validation failed"
            if request.resume
            else "DCI artifact setup failed"
        )
        raise DciRunError(message) from None

    client: PiRpcClient | None = None
    context_evidence_recorded = False
    try:
        warning = format_pi_revision_warning(recorder.pi_source)
        if warning is not None:
            recorder.add_note(warning)
            print(f"[runner] WARNING: {warning}", file=sys.stderr)
        client = PiRpcClient(
            package_dir=paths.pi.package_dir,
            cwd=request.cwd,
            agent_dir=paths.pi.agent_dir,
            provider=request.provider,
            model=request.model,
            tools=request.tools,
            show_tools=request.show_tools,
            system_prompt_file=(
                _system_prompt_override
                if _system_prompt_override is not None
                else request.system_prompt_file
            ),
            append_system_prompt_file=(
                _append_system_prompt_override
                if _append_system_prompt_override is not None
                else request.append_system_prompt_file
            ),
            extra_args=request.extra_args,
            literal_extra_args=_pi_extra_args(request),
            keep_session=request.keep_session,
            node_max_old_space_size_mb=request.node_max_old_space_size_mb,
            stream_text=request.stream_text,
            inherited_fds=_resource_fds,
            extension_path=(
                context_extension.path if context_extension is not None else None
            ),
            context_profile=(
                context_profile.name if context_profile is not None else None
            ),
            context_contract=(
                context_profile.contract_version
                if context_profile is not None
                else None
            ),
            session_file=request.pi_session_file,
        )
        client.start()
        if context_profile is not None and request.keep_session:
            session_file, session_id = _validate_pi_context_session(
                client.probe_protocol(), paths, require_file=False
            )
            if request.resume and (
                session_file != request.pi_session_file
                or session_id != request.pi_session_id
            ):
                raise RuntimeError("Pi context session identity is invalid")
            recorder.record_context_session(session_file, session_id)
        prompt_deadline = (
            time.monotonic() + request.timeout_seconds
            if request.timeout_seconds and request.timeout_seconds > 0
            else None
        )
        final_text = ""
        prompts = (*request.prelude_questions, request.question)
        for prompt_index, prompt in enumerate(prompts):
            if _cancel_event is not None and _cancel_event.is_set():
                raise RuntimeError("RPC prompt was cancelled")
            remaining = (
                None
                if prompt_deadline is None
                else max(0.0, prompt_deadline - time.monotonic())
            )
            if remaining is not None and remaining <= 0:
                raise RuntimeError("RPC prompt sequence timed out")
            final_text = client.prompt_and_wait(
                prompt,
                max_turns=request.max_turns,
                timeout_seconds=remaining,
                on_event=recorder.record_event,
                cancel_event=_cancel_event,
                recover_empty_final=prompt_index == len(prompts) - 1,
            )
        if not final_text.strip():
            raise RuntimeError("Pi provider returned no final answer")
        if context_profile is not None and request.keep_session:
            materialized_file, materialized_id = _validate_pi_context_session(
                {"sessionFile": str(session_file), "sessionId": session_id},
                paths,
                require_file=True,
            )
            if materialized_file != session_file or materialized_id != session_id:
                raise RuntimeError("Pi context session identity is invalid")
        if context_profile is not None:
            assert context_extension is not None
            context_entries = _get_context_entries(
                client, recorder.context_entry_cursor
            )
            _validate_context_entries(
                context_entries, context_profile, context_extension.version
            )
            recorder.record_context_policy(context_entries)
            context_evidence_recorded = True
        stderr_getter = getattr(client, "get_stderr", None)
        stderr_text = stderr_getter() if callable(stderr_getter) else ""
        normalized_events = recorder.finalize(
            status="completed",
            final_text=final_text,
            stderr_text=stderr_text,
            release_lock=False,
        )
        return DciRunResult(
            output_dir=destination,
            final_text=final_text,
            events=normalized_events,
            status="completed",
        )
    except (OSError, RuntimeError, ValueError):
        if (
            context_profile is not None
            and context_extension is not None
            and client is not None
            and not context_evidence_recorded
        ):
            try:
                context_entries = _get_context_entries(
                    client, recorder.context_entry_cursor
                )
                _validate_context_entries(
                    context_entries, context_profile, context_extension.version
                )
                recorder.record_context_policy(context_entries)
            except (OSError, RuntimeError, ValueError, DciArtifactError):
                pass
        stderr_getter = (
            getattr(client, "get_stderr", None) if client is not None else None
        )
        stderr_text = stderr_getter() if callable(stderr_getter) else ""
        if not recorder._finalization_started:
            recorder.finalize(
                status="failed", stderr_text=stderr_text, release_lock=False
            )
        raise DciRunError("DCI Pi execution failed") from None
    finally:
        try:
            if client is not None:
                client.stop()
        finally:
            try:
                recorder.close()
            finally:
                resource_stack.close()


def _pi_extra_args(request: DciRunRequest) -> tuple[str, ...]:
    """Return only typed controls advertised by the current Pi CLI."""

    values: list[str] = []
    if request.thinking_level:
        values.extend(["--thinking", request.thinking_level])
    return tuple(values)


def prelude_questions_fingerprint(values: tuple[str, ...]) -> str:
    """Return a stable private-input identity without persisting prompt bodies."""

    if not isinstance(values, tuple) or any(not isinstance(value, str) for value in values):
        raise ValueError("DCI prelude questions are invalid")
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _validate_context_entries(
    entries: tuple[dict[str, object], ...],
    profile: DciContextProfile,
    extension_version: str,
) -> None:
    telemetry_count = 0
    state_count = 0
    startup_count = 0
    for entry in entries:
        data = entry.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Pi context extension evidence is invalid")
        if (
            data.get("profile") != profile.name
            or data.get("contractVersion") != profile.contract_version
        ):
            raise RuntimeError("Pi context extension evidence is invalid")
        if entry.get("customType") == "dci-context-telemetry":
            telemetry_count += 1
            startup_count += data.get("event") == "startup"
            if data.get("extensionVersion") != extension_version:
                raise RuntimeError("Pi context extension evidence is invalid")
        elif entry.get("customType") == "dci-context-state":
            state_count += 1
        else:
            raise RuntimeError("Pi context extension evidence is invalid")
    if telemetry_count == 0 or state_count == 0 or startup_count != 1:
        raise RuntimeError("Pi context extension evidence is invalid")


def _get_context_entries(
    client: PiRpcClient, cursor: str | None
) -> tuple[dict[str, object], ...]:
    if cursor is None:
        return client.get_entries()
    return client.get_entries(since=cursor)


def _validate_pi_context_session(
    state: dict[str, object], paths: DciPaths, *, require_file: bool = True
) -> tuple[Path, str]:
    session_file_value = state.get("sessionFile")
    session_id = state.get("sessionId")
    if (
        not isinstance(session_file_value, str)
        or not session_file_value
        or not isinstance(session_id, str)
        or not session_id
    ):
        raise RuntimeError("Pi context session identity is invalid")
    session_file = Path(session_file_value)
    try:
        resolved = session_file.resolve(strict=require_file)
        agent_dir = paths.pi.agent_dir.resolve(strict=False)
    except OSError:
        raise RuntimeError("Pi context session identity is invalid") from None
    if (
        not session_file.is_absolute()
        or session_file.is_symlink()
        or (require_file and not resolved.is_file())
        or not resolved.is_relative_to(agent_dir)
    ):
        raise RuntimeError("Pi context session identity is invalid")
    return resolved, session_id


def _required_string(state: dict[str, object], name: str) -> str:
    value = state.get(name)
    if not isinstance(value, str) or not value:
        raise DciRunError("DCI resume validation failed")
    return value


def _optional_string(state: dict[str, object], name: str) -> str | None:
    value = state.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DciRunError("DCI resume validation failed")
    return value


def _optional_int(state: dict[str, object], name: str) -> int | None:
    value = state.get(name)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise DciRunError("DCI resume validation failed")
    return value


def _optional_positive_int(state: dict[str, object], name: str) -> int | None:
    value = _optional_int(state, name)
    if value is not None and value <= 0:
        raise DciRunError("DCI resume validation failed")
    return value


def _required_nonnegative_int(state: dict[str, object], name: str) -> int:
    value = _optional_int(state, name)
    if value is None or value < 0:
        raise DciRunError("DCI resume validation failed")
    return value


def _optional_timeout(state: dict[str, object], name: str) -> float | None:
    value = state.get(name)
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, float)
        or not math.isfinite(value)
        or value < 0
    ):
        raise DciRunError("DCI resume validation failed")
    return float(value)


def _optional_path(state: dict[str, object], name: str) -> Path | None:
    value = _optional_string(state, name)
    return Path(value) if value is not None else None


def _required_bool(state: dict[str, object], name: str) -> bool:
    value = state.get(name)
    if not isinstance(value, bool):
        raise DciRunError("DCI resume validation failed")
    return value
