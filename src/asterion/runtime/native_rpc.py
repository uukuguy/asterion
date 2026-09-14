"""Neutral RPC construction surface for the application layer.

The concrete Pi JSONL-RPC session lives in ``asterion.runtimes.pi_rpc``. This
module re-exports only the neutral handles applications may name, so the
application layer never references the Pi implementation directly.
"""

from __future__ import annotations

from asterion.runtimes.pi_rpc import (
    build_rpc_session,
    normalize_usage,
    PiRpcSession as RpcSession,
)

__all__ = ("RpcSession", "build_rpc_session", "normalize_usage")
