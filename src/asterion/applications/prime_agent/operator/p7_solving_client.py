"""Generate the sole model-facing P7 solving client module."""

from __future__ import annotations


class P7SolvingClientError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 solving client is unavailable")


def p7_solving_client_module_bytes(socket_path: object, token: object) -> bytes:
    if (
        type(socket_path) is not str
        or not socket_path.startswith("/")
        or type(token) is not str
        or not token
    ):
        raise P7SolvingClientError()
    source = """import json as _j
import socket as _s
_PATH=%r
_TOKEN=%r
_SEQUENCE=0
_CAP=1048576
def _canonical(value): return _j.dumps(value,allow_nan=False,separators=(",",":"),sort_keys=True).encode()
def _call(method,data):
 global _SEQUENCE
 sequence=_SEQUENCE+1
 raw=_canonical({"data":data,"method":method,"sequence":sequence,"token":_TOKEN})+b"\\n"
 if len(raw)>_CAP: raise RuntimeError("P7 solving client unavailable")
 try:
  with _s.socket(_s.AF_UNIX,_s.SOCK_STREAM) as client:
   client.settimeout(30);client.connect(_PATH);client.sendall(raw);response=client.makefile("rb").readline(_CAP+1)
  if not response.endswith(b"\\n") or len(response)>_CAP: raise ValueError
  value=_j.loads(response[:-1].decode("utf-8","strict"))
  if _canonical(value)!=response[:-1] or type(value) is not dict or set(value)!={"ok","result"} or value["ok"] is not True or type(value["result"]) is not dict: raise ValueError
  _SEQUENCE=sequence
  return value["result"]
 except Exception: raise RuntimeError("P7 solving client unavailable") from None
def observe(): return _call("observe",{})
def status(): return _call("status",{})
def act(actions): return _call("act",{"actions":actions})
""" % (socket_path, token)
    return source.encode()


__all__ = ("P7SolvingClientError", "p7_solving_client_module_bytes")
