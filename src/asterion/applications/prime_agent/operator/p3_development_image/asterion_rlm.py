"""Root-only fixed RLM RPC vocabulary."""
ALLOWED = frozenset(("spawn", "wait", "follow_up", "list", "delete"))
def validate(kind):
    if kind not in ALLOWED: raise ValueError("RLM request is unavailable")
    return kind
