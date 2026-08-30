"""Private callback transport from Prime to an operator-owned dispatcher."""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from pathlib import Path
from types import MappingProxyType
from typing import TypeGuard, cast

from asterion.control.protocol import OPAQUE_ID
from asterion.operation.protocol import (
    MAX_SAFE_INTEGER,
    OperationReceipt,
    OperationTransaction,
)
from asterion.operation.services import OperationDispatcher


PRIME_OPERATION_HOST_PROTOCOL = "asterion.prime-operation-host/v1"
_MAX_FRAME_BYTES = 64 * 1024
_TRAILING_FRAME_GRACE_SECONDS = 0.005
_TOKEN = re.compile(r"^[0-9a-f]{64}$")
_TRANSACTION_REQUEST_FIELDS = {
    "protocol",
    "id",
    "type",
    "token",
    "session_id",
    "generation",
    "authority_id",
    "authority_revision",
    "transaction",
}
_CANCEL_REQUEST_FIELDS = {
    "protocol",
    "id",
    "type",
    "token",
    "session_id",
    "generation",
    "authority_id",
    "authority_revision",
    "operation_id",
}


class PrimeOperationHostError(RuntimeError):
    """Fixed public-safe failure for the private callback boundary."""

    def __init__(self) -> None:
        super().__init__("Prime operation host failed")


class PrimeOperationHostServer:
    """One private Unix endpoint bound to one snapshotted dispatcher."""

    def __init__(
        self,
        *,
        dispatcher: OperationDispatcher,
        private_root: Path,
        token: str,
        request_timeout: float = 5.0,
    ) -> None:
        try:
            session_id = object.__getattribute__(dispatcher, "session_id")
            generation = object.__getattribute__(dispatcher, "generation")
            authority_id = object.__getattribute__(dispatcher, "authority_id")
            authority_revision = object.__getattribute__(
                dispatcher, "authority_revision"
            )
            execute = object.__getattribute__(dispatcher, "execute")
            cancel = object.__getattribute__(dispatcher, "cancel")
            reconcile = object.__getattribute__(dispatcher, "reconcile")
            if (
                not isinstance(private_root, Path)
                or not isinstance(token, str)
                or _TOKEN.fullmatch(token) is None
                or not _valid_opaque(session_id)
                or not _valid_positive(generation)
                or not _valid_opaque(authority_id)
                or not _valid_positive(authority_revision)
                or not callable(execute)
                or not callable(cancel)
                or not callable(reconcile)
                or not _positive_timeout(request_timeout)
            ):
                raise ValueError
            resolved_root = private_root.resolve(strict=False)
        except Exception:
            raise PrimeOperationHostError() from None

        self._private_root = private_root
        self._resolved_root = resolved_root
        self._socket_path = resolved_root / "prime-operation.sock"
        self._token = token
        self._session_id = session_id
        self._generation = generation
        self._authority_id = authority_id
        self._authority_revision = authority_revision
        self._execute = cast(
            Callable[[OperationTransaction], Awaitable[OperationReceipt]], execute
        )
        self._cancel = cast(Callable[..., Awaitable[OperationReceipt]], cancel)
        self._reconcile = cast(
            Callable[[OperationTransaction], Awaitable[OperationReceipt]], reconcile
        )
        self._request_timeout = float(request_timeout)
        self._server: asyncio.AbstractServer | None = None
        self._handlers: set[asyncio.Task[None]] = set()
        self._created_socket_identity: tuple[int, int] | None = None
        self._started = False
        self._closed = False

    @property
    def descriptor(self) -> Mapping[str, str]:
        return MappingProxyType(
            {"socketPath": str(self._socket_path), "token": self._token}
        )

    async def start(self) -> None:
        if self._started or self._closed:
            raise PrimeOperationHostError()
        self._started = True
        try:
            if (
                not self._private_root.is_dir()
                or self._private_root.is_symlink()
                or self._private_root != self._resolved_root
                or self._private_root.resolve(strict=True) != self._resolved_root
                or self._socket_path.exists()
                or self._socket_path.is_symlink()
            ):
                raise OSError
            self._server = await asyncio.start_unix_server(
                self._handle_client,
                path=str(self._socket_path),
                limit=_MAX_FRAME_BYTES + 1,
                start_serving=False,
            )
            socket_stat = os.lstat(self._socket_path)
            if not stat.S_ISSOCK(socket_stat.st_mode):
                raise OSError
            self._created_socket_identity = (socket_stat.st_dev, socket_stat.st_ino)
            self._socket_path.chmod(0o600)
            await self._server.start_serving()
        except asyncio.CancelledError:
            with suppress(Exception):
                await self._shutdown()
            raise
        except Exception:
            await self._shutdown()
            raise PrimeOperationHostError() from None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._shutdown()
        except asyncio.CancelledError:
            raise
        except Exception:
            raise PrimeOperationHostError() from None

    async def _shutdown(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()

        current = asyncio.current_task()
        handlers = tuple(task for task in self._handlers if task is not current)
        for task in handlers:
            task.cancel()
        if handlers:
            await asyncio.gather(*handlers, return_exceptions=True)
        self._handlers.difference_update(handlers)
        if server is not None:
            await server.wait_closed()
        self._unlink_created_socket()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._handlers.add(task)
        request_id: str | None = None
        try:
            frame = await asyncio.wait_for(
                reader.readuntil(b"\n"), timeout=self._request_timeout
            )
            request_id = _extract_request_id(frame)
            if not frame or len(frame) > _MAX_FRAME_BYTES:
                raise PrimeOperationHostError()
            try:
                trailing = await asyncio.wait_for(
                    reader.read(1),
                    timeout=min(
                        self._request_timeout, _TRAILING_FRAME_GRACE_SECONDS
                    ),
                )
            except TimeoutError:
                trailing = b""
            if trailing:
                raise PrimeOperationHostError()
            request = _decode_frame(frame)
            request_id, operation, argument = self._validate_request(request)
            receipt = await asyncio.wait_for(
                self._dispatch(operation, argument), timeout=self._request_timeout
            )
            response = {
                "protocol": PRIME_OPERATION_HOST_PROTOCOL,
                "id": request_id,
                "type": "operation.receipt",
                "receipt": _json_safe(receipt.to_mapping()),
            }
            await self._write_response(writer, response)
        except asyncio.CancelledError:
            raise
        except Exception:
            if request_id is not None:
                with suppress(Exception):
                    await self._write_response(
                        writer,
                        {
                            "protocol": PRIME_OPERATION_HOST_PROTOCOL,
                            "id": request_id,
                            "type": "error",
                            "code": "operation-host-failed",
                        },
                    )
        finally:
            if task is not None:
                self._handlers.discard(task)
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    def _validate_request(
        self, request: Mapping[str, object]
    ) -> tuple[str, str, OperationTransaction | str]:
        request_id = request.get("id")
        operation = request.get("type")
        if (
            not _valid_opaque(request_id)
            or not isinstance(operation, str)
            or request.get("protocol") != PRIME_OPERATION_HOST_PROTOCOL
            or request.get("token") != self._token
            or request.get("session_id") != self._session_id
            or request.get("generation") != self._generation
            or type(request.get("generation")) is not int
            or request.get("authority_id") != self._authority_id
            or request.get("authority_revision") != self._authority_revision
            or type(request.get("authority_revision")) is not int
        ):
            raise PrimeOperationHostError()

        if operation in {"operation.execute", "operation.reconcile"}:
            if set(request) != _TRANSACTION_REQUEST_FIELDS:
                raise PrimeOperationHostError()
            raw_transaction = request.get("transaction")
            if not isinstance(raw_transaction, Mapping):
                raise PrimeOperationHostError()
            transaction = OperationTransaction.from_mapping(raw_transaction)
            self._require_transaction_identity(transaction)
            return request_id, operation, transaction

        if operation == "operation.cancel":
            operation_id = request.get("operation_id")
            if set(request) != _CANCEL_REQUEST_FIELDS or not _valid_opaque(operation_id):
                raise PrimeOperationHostError()
            return request_id, operation, operation_id
        raise PrimeOperationHostError()

    async def _dispatch(
        self, operation: str, argument: OperationTransaction | str
    ) -> OperationReceipt:
        if operation == "operation.execute":
            assert isinstance(argument, OperationTransaction)
            receipt = await self._execute(argument)
            self._require_receipt_identity(receipt, transaction=argument)
        elif operation == "operation.reconcile":
            assert isinstance(argument, OperationTransaction)
            receipt = await self._reconcile(argument)
            self._require_receipt_identity(receipt, transaction=argument)
        else:
            assert isinstance(argument, str)
            receipt = await self._cancel(
                argument, authority_revision=self._authority_revision
            )
            self._require_receipt_identity(receipt, operation_id=argument)
        return receipt

    def _require_transaction_identity(self, transaction: OperationTransaction) -> None:
        if (
            transaction.session_id != self._session_id
            or transaction.generation != self._generation
            or transaction.authority_id != self._authority_id
            or transaction.authority_revision != self._authority_revision
        ):
            raise PrimeOperationHostError()

    def _require_receipt_identity(
        self,
        receipt: object,
        *,
        transaction: OperationTransaction | None = None,
        operation_id: str | None = None,
    ) -> None:
        if type(receipt) is not OperationReceipt:
            raise PrimeOperationHostError()
        canonical = OperationReceipt.from_mapping(receipt.to_mapping())
        if (
            canonical.session_id != self._session_id
            or canonical.generation != self._generation
            or canonical.authority_id != self._authority_id
            or canonical.authority_revision != self._authority_revision
        ):
            raise PrimeOperationHostError()
        if operation_id is not None and canonical.operation_id != operation_id:
            raise PrimeOperationHostError()
        if transaction is not None and (
            canonical.operation_id != transaction.operation_id
            or canonical.request_ref != transaction.request.request_ref
            or canonical.request_sha256 != transaction.request.request_sha256
            or canonical.purpose != transaction.request.purpose
            or canonical.session_id != transaction.session_id
            or canonical.client_id != transaction.client_id
            or canonical.generation != transaction.generation
            or canonical.authority_revision != transaction.authority_revision
            or canonical.authority_id != transaction.authority_id
            or canonical.idempotency_key != transaction.idempotency_key
            or canonical.feature_id != transaction.feature_id
        ):
            raise PrimeOperationHostError()

    async def _write_response(
        self, writer: asyncio.StreamWriter, response: Mapping[str, object]
    ) -> None:
        writer.write(
            json.dumps(response, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            + b"\n"
        )
        await asyncio.wait_for(writer.drain(), timeout=self._request_timeout)

    def _unlink_created_socket(self) -> None:
        identity, self._created_socket_identity = self._created_socket_identity, None
        if identity is None:
            return
        try:
            socket_stat = os.lstat(self._socket_path)
            if (
                stat.S_ISSOCK(socket_stat.st_mode)
                and (socket_stat.st_dev, socket_stat.st_ino) == identity
            ):
                self._socket_path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            raise PrimeOperationHostError() from None


def _decode_frame(frame: bytes) -> Mapping[str, object]:
    if not frame.endswith(b"\n"):
        raise PrimeOperationHostError()

    def closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PrimeOperationHostError()
            result[key] = value
        return result

    try:
        value = json.loads(
            frame[:-1].decode("utf-8"),
            object_pairs_hook=closed_object,
            parse_constant=lambda _: (_ for _ in ()).throw(PrimeOperationHostError()),
        )
    except PrimeOperationHostError:
        raise
    except Exception:
        raise PrimeOperationHostError() from None
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise PrimeOperationHostError()
    return value


def _extract_request_id(frame: bytes) -> str | None:
    if len(frame) > _MAX_FRAME_BYTES:
        return None
    try:
        request_id = _decode_frame(frame).get("id")
    except PrimeOperationHostError:
        return None
    return request_id if _valid_opaque(request_id) else None


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_safe(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(child) for child in value]
    if value is None or type(value) in {bool, int, str}:
        return value
    raise PrimeOperationHostError()


def _valid_opaque(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and OPAQUE_ID.fullmatch(value) is not None


def _valid_positive(value: object) -> bool:
    return type(value) is int and 1 <= value <= MAX_SAFE_INTEGER


def _positive_timeout(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) > 0
        and float(value) < float("inf")
    )
