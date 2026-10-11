"""Private descriptor transport; method semantics belong to injected services."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import socket
import threading
from asterion.agents.prime.tools import PrimeToolResult

PROTOCOL = 'asterion.prime-ipython/v1'
OUTPUT_BYTES_ENVIRONMENT = 'ASTERION_PRIME_IPYTHON_OUTPUT_BYTES'
_DEFAULT_OUTPUT_BYTES = 64 * 1024


def output_capacity(services):
    """Optional application-owned output capacity, never provider configuration."""
    value = getattr(services, 'bridge_output_bytes', _DEFAULT_OUTPUT_BYTES)
    if (type(value) is not int or value < 256
            or value > ((2 ** 53 - 1) - 8192) // 6):
        raise ValueError('Prime tool output capacity is invalid')
    return value


def line_capacity(output_bytes):
    """Match the extension's worst-case JSON escaping plus protocol overhead."""
    return max(256 * 1024, 6 * output_bytes + 8192)


class _BridgeSignal:
    def __init__(self, stop):
        self._stop = stop

    @property
    def cancelled(self):
        return self._stop.is_set()


class ToolBridgeServer:
    def __init__(self, channel, services):
        self._channel, self._services = channel, services
        self._max_output_bytes = output_capacity(services)
        self._max_line_bytes = line_capacity(self._max_output_bytes)
        self._channel.setblocking(False)
        self._stop = threading.Event()
        self._signal = _BridgeSignal(self._stop)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._started = self._close_error = self._host_closed = False
        self._loop = asyncio.new_event_loop()

    def __repr__(self):
        return '<PrimeToolBridge redacted>'

    def start(self):
        self._thread.start()
        self._started = True

    def close(self):
        self._stop.set()
        self._services.request_stop()
        try:
            self._channel.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        if self._started:
            self._thread.join(6.0)
        else:
            self._close_services()
        self._channel.close()
        if self._thread.is_alive() or self._close_error:
            raise RuntimeError('Prime computation cleanup is incomplete')

    async def _close_services_async(self):
        try:
            await self._services.close()
            self._host_closed = True
        except BaseException:
            self._close_error = True

    def _close_services(self):
        if not self._loop.is_closed():
            try:
                self._loop.run_until_complete(self._close_services_async())
            finally:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                self._loop.close()

    def _serve(self):
        # Workers retain this loop for cross-thread cleanup. Keep it running
        # while awaiting requests, including the otherwise idle periods.
        try:
            self._loop.run_until_complete(self._serve_async())
        finally:
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()
            self._channel.close()

    async def _serve_async(self):
        try:
            pending = bytearray()
            while not self._stop.is_set():
                try:
                    chunk = await self._loop.sock_recv(self._channel, 4096)
                except OSError:
                    return
                if not chunk:
                    return
                pending.extend(chunk)
                if (len(pending) > self._max_line_bytes
                        and (b'\n' not in pending or pending.index(b'\n') > self._max_line_bytes)):
                    return
                while b'\n' in pending:
                    raw, _, trailing = pending.partition(b'\n')
                    pending = bytearray(trailing)
                    response = await self._dispatch_async(bytes(raw))
                    try:
                        await self._loop.sock_sendall(self._channel, response + b'\n')
                    except OSError:
                        return
        finally:
            await self._close_services_async()

    def _dispatch(self, raw):
        return self._loop.run_until_complete(self._dispatch_async(raw))

    async def _dispatch_async(self, raw):
        request_id = 'invalid'
        response_type = 'result'
        try:
            if len(raw) > self._max_line_bytes:
                raise ValueError
            value = json.loads(raw.decode('utf-8', 'strict'))
            if type(value) is not dict or value.get('protocol') != PROTOCOL:
                raise ValueError
            request_id = value.get('request_id')
            if (type(request_id) is not str or not request_id
                    or len(request_id.encode('utf-8')) > 256):
                request_id = 'invalid'
                raise ValueError
            if value.get('type') == 'execute':
                if (set(value) != {'code', 'protocol', 'request_id', 'type'}
                        or type(value['code']) is not str or not value['code']):
                    raise ValueError
                result = await self._services.execute(request_id, value['code'], self._signal)
                if type(result) is not PrimeToolResult or result.call_id != request_id:
                    raise ValueError
                output = result.content[0].get('text', '') if result.content else ''
                response = {'output': output, 'protocol': PROTOCOL, 'request_id': request_id,
                            'status': result.status, 'type': response_type}
            elif value.get('type') == 'method_call':
                response_type = 'method_result'
                if (set(value) not in ({'protocol', 'request_id', 'type', 'method'},
                                       {'protocol', 'request_id', 'type', 'method', 'params'})
                        or type(value['method']) is not str or not value['method']):
                    raise ValueError
                response = await self._services.call(
                    request_id, value['method'], value.get('params'), self._signal,
                    params_present='params' in value)
            else:
                raise ValueError
            if (not isinstance(response, Mapping)
                    or set(response) != {'output', 'protocol', 'request_id', 'status', 'type'}
                    or response['protocol'] != PROTOCOL or response['request_id'] != request_id
                    or response['type'] != response_type or response['status'] not in ('ok', 'error', 'uncertain')
                    or type(response['output']) is not str
                    or len(response['output'].encode('utf-8')) > self._max_output_bytes):
                raise ValueError
            response = dict(response)
        except BaseException:
            response = {'output': '', 'protocol': PROTOCOL, 'request_id': request_id,
                        'status': 'error', 'type': response_type}
        return json.dumps(response, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()
