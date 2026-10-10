"""Ownership of existing Prime workers and explicit source/JSON restoration."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path
from asterion.agents.prime.ipython import (
    KernelBootstrap, KernelExport, KernelLimits, PersistentIpythonHost,
)
from asterion.runtime.host import CancellationSignal
from asterion.agents.prime.ipython_worker import SubprocessPythonWorker
from asterion.runtime.protocol import ProtocolError


class WorkspaceOwner:
    def __init__(self):
        self._workspaces = {}
        self._closed = False

    def create_workspace(self, bootstrap: KernelBootstrap, limits: KernelLimits, *,
                         python: Path | None = None,
                         observer: Callable[[str, Mapping[str, object]], None] | None = None) -> PersistentIpythonHost:
        if self._closed:
            raise ProtocolError('Prime workspace owner is closed')
        if python is not None and (not isinstance(python, Path) or not python.is_absolute()):
            raise ProtocolError('Prime workspace executable is invalid')
        worker = SubprocessPythonWorker(python=python)
        host = PersistentIpythonHost(worker=worker,
                                     bootstrap=bootstrap, limits=limits, observer=observer)
        self._workspaces[host] = (bootstrap, limits, python, observer, worker)
        return host

    async def restore_workspace(
        self, previous: PersistentIpythonHost, source_exports: tuple[KernelExport, ...],
        data_exports: Mapping[str, KernelExport], signal: CancellationSignal,
    ) -> PersistentIpythonHost:
        if self._closed or previous not in self._workspaces:
            raise ProtocolError('Prime workspace is unavailable')
        bootstrap, limits, python, observer, _ = self._workspaces[previous]
        replacement = self.create_workspace(bootstrap, limits, python=python, observer=observer)
        try:
            await replacement.restore(source_exports, data_exports, signal)
            await previous.close()
        except BaseException:
            await replacement.close()
            raise
        return replacement

    async def close(self) -> bool:
        self._closed = True
        complete = True
        # Signal every owned generation before awaiting any host's active-cell
        # lock. Worker cleanup has no dependency on domain cancellation.
        for _, _, _, _, worker in self._workspaces.values():
            try:
                worker._request_stop()
            except BaseException:
                complete = False
        for host, (_, limits, _, _, worker) in self._workspaces.items():
            try:
                await asyncio.wait_for(worker.close(), limits.cleanup_seconds)
            except BaseException:
                complete = False
            try:
                await asyncio.wait_for(host.close(), limits.cleanup_seconds)
            except BaseException:
                complete = False
        return complete
