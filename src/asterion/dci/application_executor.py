"""Provider-owned native executor for one Asterion DCI application run."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from asterion.dci.config import (
    load_asterion_dci_env,
    resolve_dci_paths,
    resolve_dci_runtime_options,
)
from asterion.dci.run import (
    DciRunRequest,
    DciRunResult,
    request_from_runtime_options,
    run_pi_research,
)


class EnvironmentDciRunExecutor:
    """Resolve application configuration before invoking the native Pi workflow."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        run_native: Callable[..., DciRunResult] = run_pi_research,
        honor_request_tools: bool = False,
    ) -> None:
        self._repo_root = Path.cwd() if repo_root is None else Path(repo_root)
        self._run_native = run_native
        self._honor_request_tools = honor_request_tools

    def run(
        self,
        request: DciRunRequest,
        *,
        cancel_event: threading.Event | None = None,
    ) -> DciRunResult:
        root = self._repo_root.resolve()
        load_asterion_dci_env(root)
        cwd = Path(os.environ.get("ASTERION_RUNTIME_CWD", root)).resolve()
        options = resolve_dci_runtime_options()
        mapped = replace(
            request_from_runtime_options(
                options,
                run_id=request.run_id,
                question=request.question,
                cwd=cwd,
                stream_text=False,
            ),
            max_turns=request.max_turns,
            show_tools=request.show_tools,
            system_prompt_file=request.system_prompt_file,
            append_system_prompt_file=request.append_system_prompt_file,
            conversation_features=request.conversation_features,
            tools=request.tools if self._honor_request_tools else options.tools,
        )
        paths = resolve_dci_paths(root)
        if cancel_event is None:
            return self._run_native(paths, mapped)
        return self._run_native(paths, mapped, _cancel_event=cancel_event)
