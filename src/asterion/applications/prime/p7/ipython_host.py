"""Application-owned bridge to one persistent restricted IPython worker."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
import re
from time import monotonic
from typing import Literal, Protocol, cast

from asterion.agents.prime.tools import PrimeToolResult
from asterion.runtime.host import CancellationSignal


_CALL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_DEFAULT_CODE_BYTES = 16 * 1024
_DEFAULT_OUTPUT_BYTES = 64 * 1024
_DEFAULT_DEADLINE_SECONDS = 60.0
_CLEANUP_SECONDS = 30.0
_CANCEL_REAP_SECONDS = 0.1
_CLIENT_SEAL = object()


class PersistentIpythonHostError(RuntimeError):
    """Body-free application-host failure."""

    def __init__(self, *_: object) -> None:
        super().__init__("persistent IPython host is unavailable")


class P7ClientError(RuntimeError):
    """Body-free failure from the sealed game capability."""

    def __init__(self, *_: object) -> None:
        super().__init__("P7 client is unavailable")


class P7ClientFacade:
    """Sealed worker-visible facade containing only the three game operations."""

    __slots__ = ("__client", "__module_source", "__sealed")

    def __init__(
        self,
        *,
        _seal: object = None,
        client: object = None,
        module_source: bytes | None = None,
    ) -> None:
        if _seal is not _CLIENT_SEAL or (client is None) == (module_source is None):
            raise P7ClientError()
        if module_source is not None and (
            type(module_source) is not bytes
            or not module_source
            or len(module_source) > _DEFAULT_CODE_BYTES
        ):
            raise P7ClientError()
        if client is not None and any(
            not callable(getattr(client, name, None))
            for name in ("observe", "status", "act")
        ):
            raise P7ClientError()
        object.__setattr__(self, "_P7ClientFacade__client", client)
        object.__setattr__(self, "_P7ClientFacade__module_source", module_source)
        object.__setattr__(self, "_P7ClientFacade__sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_P7ClientFacade__sealed", False):
            raise AttributeError("sealed P7 client")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        del name
        raise AttributeError("sealed P7 client")

    def __repr__(self) -> str:
        return "<P7ClientFacade redacted>"

    def observe(self) -> Mapping[str, object]:
        return self.__invoke("observe")

    def status(self) -> Mapping[str, object]:
        return self.__invoke("status")

    def act(self, actions: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
        if isinstance(actions, (str, bytes, bytearray)) or not isinstance(
            actions, Sequence
        ):
            raise P7ClientError()
        return self.__invoke("act", list(actions))

    def __invoke(self, name: str, *args: object) -> Mapping[str, object]:
        try:
            if self.__client is None:
                raise ValueError
            operation = getattr(self.__client, name)
            value = operation(*args)
            if not isinstance(value, Mapping):
                raise ValueError
            return value
        except BaseException:
            raise P7ClientError() from None

    def _worker_module_source(self) -> bytes:
        """Private adapter hook; source never appears in public values."""

        if self.__module_source is None:
            raise P7ClientError()
        return self.__module_source


def p7_client_facade(client: object) -> P7ClientFacade:
    """Seal one live client behind the exact worker-visible API."""

    return P7ClientFacade(_seal=_CLIENT_SEAL, client=client)


def p7_client_module_facade(source: bytes) -> P7ClientFacade:
    """Seal the exact module bytes injected into the restricted process."""

    if not _valid_client_module(source):
        raise P7ClientError()
    return P7ClientFacade(_seal=_CLIENT_SEAL, module_source=source)


@dataclass(frozen=True, repr=False, slots=True)
class IpythonWorkerResult:
    """Private normalized outcome returned by an admitted worker adapter."""

    status: Literal["ok", "error", "uncertain"]
    output: str

    def __post_init__(self) -> None:
        if self.status not in {"ok", "error", "uncertain"} or type(self.output) is not str:
            raise PersistentIpythonHostError()

    def __repr__(self) -> str:
        return "<IpythonWorkerResult redacted>"


class RestrictedPersistentIpythonWorker(Protocol):
    """Narrow lifecycle implemented by a restricted persistent process."""

    async def start(
        self, p7_client: P7ClientFacade, *, signal: CancellationSignal
    ) -> None: ...

    async def execute_cell(
        self, code: str, *, signal: CancellationSignal
    ) -> IpythonWorkerResult: ...

    async def close(self) -> None: ...


class _ExistingP7Worker(Protocol):
    async def acquire(self, client: bytes) -> None: ...

    async def execute_cell(self, code: str) -> dict[str, object]: ...

    async def cleanup(self) -> None: ...


class _ExistingP7DockerWorkerAdapter:
    """Adapter over the established restricted persistent P7 Docker worker."""

    __slots__ = ("_worker", "_closed")

    def __init__(self, worker: object) -> None:
        if any(
            not callable(getattr(worker, name, None))
            for name in ("acquire", "execute_cell", "cleanup")
        ):
            raise PersistentIpythonHostError()
        self._worker = cast(_ExistingP7Worker, worker)
        self._closed = False

    async def start(
        self, p7_client: P7ClientFacade, *, signal: CancellationSignal
    ) -> None:
        _check_signal(signal)
        try:
            await self._worker.acquire(p7_client._worker_module_source())
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise PersistentIpythonHostError() from None
        _check_signal(signal)

    async def execute_cell(
        self, code: str, *, signal: CancellationSignal
    ) -> IpythonWorkerResult:
        _check_signal(signal)
        try:
            value = await self._worker.execute_cell(code)
            if (
                type(value) is not dict
                or set(value) != {"cell_count", "is_error", "output"}
                or type(value["cell_count"]) is not int
                or value["cell_count"] <= 0
                or type(value["is_error"]) is not bool
                or type(value["output"]) is not str
            ):
                raise ValueError
            return IpythonWorkerResult(
                "uncertain" if value["is_error"] else "ok", value["output"]
            )
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise PersistentIpythonHostError() from None

    async def close(self) -> None:
        if self._closed:
            return
        try:
            await self._worker.cleanup()
            self._closed = True
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise PersistentIpythonHostError() from None

    def __repr__(self) -> str:
        return "<_ExistingP7DockerWorkerAdapter redacted>"


class PersistentIpythonHost:
    """Serialize cells through one restricted worker and preserve its state."""

    __slots__ = (
        "_worker",
        "_p7_client",
        "_max_code_bytes",
        "_max_output_bytes",
        "_deadline_seconds",
        "_cleanup_seconds",
        "_lock",
        "_started",
        "_lost",
        "_closed",
        "_call_ids",
    )

    def __init__(
        self,
        *,
        worker: RestrictedPersistentIpythonWorker,
        p7_client: P7ClientFacade,
        max_code_bytes: int = _DEFAULT_CODE_BYTES,
        max_output_bytes: int = _DEFAULT_OUTPUT_BYTES,
        deadline_seconds: float = _DEFAULT_DEADLINE_SECONDS,
        cleanup_seconds: float = _CLEANUP_SECONDS,
    ) -> None:
        if (
            type(p7_client) is not P7ClientFacade
            or any(
                not callable(getattr(worker, name, None))
                for name in ("start", "execute_cell", "close")
            )
            or not _positive_int(max_code_bytes)
            or not _positive_int(max_output_bytes)
            or not _positive_seconds(deadline_seconds)
            or not _positive_seconds(cleanup_seconds)
        ):
            raise PersistentIpythonHostError()
        self._worker = worker
        self._p7_client = p7_client
        self._max_code_bytes = max_code_bytes
        self._max_output_bytes = max_output_bytes
        self._deadline_seconds = float(deadline_seconds)
        self._cleanup_seconds = float(cleanup_seconds)
        self._lock = asyncio.Lock()
        self._started = False
        self._lost = False
        self._closed = False
        self._call_ids: set[str] = set()

    def __repr__(self) -> str:
        return "<PersistentIpythonHost redacted>"

    async def execute(
        self, call_id: str, code: str, signal: CancellationSignal
    ) -> PrimeToolResult:
        if not _valid_call(call_id, code, signal, self._max_code_bytes):
            return _result(_safe_call_id(call_id), "error")
        async with self._lock:
            if call_id in self._call_ids:
                return _result(call_id, "error")
            self._call_ids.add(call_id)
            if self._lost or self._closed:
                return _result(call_id, "uncertain")
            if _cancelled(signal):
                return _result(call_id, "error")
            if not self._started:
                started = await self._start(signal)
                if not started:
                    return _result(call_id, "error")
            if _cancelled(signal):
                return _result(call_id, "error")

            task = asyncio.create_task(self._worker.execute_cell(code, signal=signal))
            cancelled = False
            value: object = None
            try:
                value = await self._await_operation(task, signal)
            except asyncio.CancelledError:
                await self._mark_lost()
                cancelled = True
            except BaseException:
                await self._mark_lost()
                return _result(call_id, "uncertain")
            if cancelled:
                raise asyncio.CancelledError() from None
            if type(value) is not IpythonWorkerResult:
                await self._mark_lost()
                return _result(call_id, "uncertain")
            worker_result = cast(IpythonWorkerResult, value)
            if worker_result.status != "ok":
                await self._mark_lost()
                return _result(call_id, "uncertain")
            try:
                output_size = len(worker_result.output.encode("utf-8", "strict"))
            except UnicodeError:
                await self._mark_lost()
                return _result(call_id, "uncertain")
            if output_size > self._max_output_bytes:
                await self._mark_lost()
                return _result(call_id, "uncertain")
            return _result(call_id, "ok", worker_result.output)

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            await self._bounded_close()
            self._closed = True

    async def _start(self, signal: CancellationSignal) -> bool:
        task = asyncio.create_task(self._worker.start(self._p7_client, signal=signal))
        cancelled = False
        try:
            await self._await_operation(task, signal)
        except asyncio.CancelledError:
            await self._mark_lost()
            cancelled = True
        except BaseException:
            await self._mark_lost()
            return False
        if cancelled:
            raise asyncio.CancelledError() from None
        self._started = True
        return True

    async def _await_operation(
        self, task: asyncio.Task[object], signal: CancellationSignal
    ) -> object:
        deadline = monotonic() + self._deadline_seconds
        try:
            while not task.done():
                if _cancelled(signal):
                    task.cancel()
                    await _reap_cancelled_task(task)
                    raise PersistentIpythonHostError()
                remaining = deadline - monotonic()
                if remaining <= 0:
                    task.cancel()
                    await _reap_cancelled_task(task)
                    raise TimeoutError
                await asyncio.wait({task}, timeout=min(0.01, remaining))
        except asyncio.CancelledError:
            task.cancel()
            await _reap_cancelled_task(task)
            raise
        return task.result()

    async def _mark_lost(self) -> None:
        self._lost = True
        try:
            await self._bounded_close()
        except BaseException:
            pass

    async def _bounded_close(self) -> None:
        task = asyncio.create_task(self._worker.close())
        cancelled = False
        failed = False
        try:
            await asyncio.wait_for(
                asyncio.shield(task), timeout=self._cleanup_seconds
            )
        except asyncio.CancelledError:
            cancelled = True
            task.cancel()
            await _reap_cancelled_task(task)
        except TimeoutError:
            failed = True
            task.cancel()
            await _reap_cancelled_task(task)
        except BaseException:
            failed = True
        if cancelled:
            raise asyncio.CancelledError() from None
        if failed:
            raise PersistentIpythonHostError() from None
        try:
            task.result()
        except BaseException:
            raise PersistentIpythonHostError() from None


def create_restricted_persistent_ipython_host(
    *,
    worker: object,
    p7_client_module: bytes,
    deadline_seconds: float = _DEFAULT_DEADLINE_SECONDS,
    cleanup_seconds: float = _CLEANUP_SECONDS,
) -> PersistentIpythonHost:
    """Adapt an operator-injected restricted P7 process without product imports."""

    try:
        adapter = _ExistingP7DockerWorkerAdapter(worker)
        client = p7_client_module_facade(p7_client_module)
        return PersistentIpythonHost(
            worker=adapter,
            p7_client=client,
            max_code_bytes=_DEFAULT_CODE_BYTES,
            max_output_bytes=4096,
            deadline_seconds=deadline_seconds,
            cleanup_seconds=cleanup_seconds,
        )
    except BaseException:
        raise PersistentIpythonHostError() from None


def _result(
    call_id: str,
    status: Literal["ok", "error", "uncertain"],
    output: str | None = None,
) -> PrimeToolResult:
    text = (
        output
        if status == "ok" and output is not None
        else (
            "IPython cell failed"
            if status == "error"
            else "IPython cell result is uncertain"
        )
    )
    return PrimeToolResult(call_id, status, ({"type": "text", "text": text},))


def _safe_call_id(value: object) -> str:
    return value if type(value) is str and _CALL_ID.fullmatch(value) else "invalid-call"


def _valid_call(
    call_id: object, code: object, signal: object, max_code_bytes: int
) -> bool:
    try:
        cancelled = getattr(signal, "cancelled")
        return (
            type(call_id) is str
            and _CALL_ID.fullmatch(call_id) is not None
            and type(code) is str
            and bool(code)
            and len(code.encode("utf-8", "strict")) <= max_code_bytes
            and signal is not None
            and type(cancelled) is bool
        )
    except BaseException:
        return False


def _check_signal(signal: CancellationSignal) -> None:
    if _cancelled(signal):
        raise PersistentIpythonHostError()


def _cancelled(signal: CancellationSignal) -> bool:
    try:
        value = signal.cancelled
    except BaseException:
        raise PersistentIpythonHostError() from None
    if type(value) is not bool:
        raise PersistentIpythonHostError()
    return value


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _positive_seconds(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and isfinite(value)
        and value > 0
    )


async def _reap_cancelled_task(task: asyncio.Task[object]) -> None:
    try:
        done, _ = await asyncio.wait({task}, timeout=_CANCEL_REAP_SECONDS)
        if not done:
            task.add_done_callback(_observe_detached_task)
        else:
            task.exception()
    except BaseException:
        pass


def _observe_detached_task(task: asyncio.Task[object]) -> None:
    try:
        task.exception()
    except BaseException:
        pass


def _valid_client_module(source: object) -> bool:
    if (
        type(source) is not bytes
        or not source
        or len(source) > _DEFAULT_CODE_BYTES
    ):
        return False
    try:
        module = ast.parse(source.decode("utf-8", "strict"), mode="exec")
    except (SyntaxError, UnicodeError, ValueError):
        return False
    public: dict[str, ast.FunctionDef] = {}
    for statement in module.body:
        if type(statement) is ast.Import:
            if any(
                alias.name not in {"json", "socket"}
                or alias.asname is None
                or not alias.asname.startswith("_")
                for alias in statement.names
            ):
                return False
        elif type(statement) is ast.Assign:
            if any(
                type(target) is not ast.Name or not target.id.startswith("_")
                for target in statement.targets
            ):
                return False
        elif type(statement) is ast.FunctionDef:
            if statement.name.startswith("_"):
                continue
            public[statement.name] = statement
        else:
            return False
    if set(public) != {"act", "observe", "status"}:
        return False
    return (
        _exact_arguments(public["observe"], 0)
        and _exact_arguments(public["status"], 0)
        and _exact_arguments(public["act"], 1)
        and public["act"].args.args[0].arg == "actions"
    )


def _exact_arguments(function: ast.FunctionDef, count: int) -> bool:
    arguments = function.args
    return (
        not arguments.posonlyargs
        and len(arguments.args) == count
        and arguments.vararg is None
        and not arguments.kwonlyargs
        and arguments.kwarg is None
        and not arguments.defaults
        and not arguments.kw_defaults
        and not function.decorator_list
    )


__all__ = (
    "IpythonWorkerResult",
    "P7ClientError",
    "P7ClientFacade",
    "PersistentIpythonHost",
    "PersistentIpythonHostError",
    "RestrictedPersistentIpythonWorker",
    "create_restricted_persistent_ipython_host",
    "p7_client_facade",
    "p7_client_module_facade",
)
