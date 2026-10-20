"""Execute one model-written P2 retrieval statement on the context service.

The statement may call ``retrieve`` or ``transform``. It cannot import, read
the corpus, or reach any other name. The service performs the call.
"""
from __future__ import annotations

import ast

from asterion.applications.prime.p2.context_service import (
    P2ContextService,
    P2ContextSlice,
)


class P2ProgramError(ValueError):
    def __init__(self) -> None:
        super().__init__("P2 retrieval program rejected")


def _source(text: str) -> str:
    body = text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            body = "\n".join(lines[1:-1]).strip()
    if not body or len(body) > 2000 or "\x00" in body:
        raise P2ProgramError()
    return body


def _integer(node: ast.expr) -> int:
    if type(node) is ast.Constant and type(node.value) is int and not isinstance(node.value, bool):
        return node.value
    raise P2ProgramError()


def _key(node: ast.expr) -> str:
    if (
        type(node) is ast.Constant
        and type(node.value) is str
        and node.value
        and len(node.value) <= 64
    ):
        return node.value
    raise P2ProgramError()


def _bounds(start: int, end: int, record_count: int) -> None:
    if start < 0 or end > record_count or start >= end:
        raise P2ProgramError()


def interpret(source: str, record_count: int) -> dict:
    """Return the one service call a statement names. Do not read the corpus."""

    if type(source) is not str or type(record_count) is not int or record_count < 1:
        raise P2ProgramError()
    try:
        tree = ast.parse(_source(source), mode="exec")
    except SyntaxError:
        raise P2ProgramError() from None
    if len(tree.body) != 1:
        raise P2ProgramError()
    statement = tree.body[0]
    if type(statement) is ast.Assign:
        if (
            len(statement.targets) != 1
            or type(statement.targets[0]) is not ast.Name
            or statement.targets[0].id != "result"
        ):
            raise P2ProgramError()
        call = statement.value
    elif type(statement) is ast.Expr:
        call = statement.value
    else:
        raise P2ProgramError()
    if (
        type(call) is not ast.Call
        or call.keywords
        or type(call.func) is not ast.Name
    ):
        raise P2ProgramError()
    if call.func.id == "retrieve" and len(call.args) == 2:
        start, end = _integer(call.args[0]), _integer(call.args[1])
        _bounds(start, end, record_count)
        return {"operation": "retrieve", "bounds": [start, end]}
    if call.func.id == "transform" and 3 <= len(call.args) <= 18:
        start, end = _integer(call.args[0]), _integer(call.args[1])
        _bounds(start, end, record_count)
        keys = [_key(arg) for arg in call.args[2:]]
        return {"operation": "transform", "bounds": [start, end], "select_keys": keys}
    raise P2ProgramError()


def execute_program(source: str, service: P2ContextService) -> P2ContextSlice:
    """Run the statement. The slice comes only from the context service."""

    if type(service) is not P2ContextService:
        raise P2ProgramError()
    query = interpret(source, service.record_count)
    bounds = (query["bounds"][0], query["bounds"][1])
    if query["operation"] == "retrieve":
        return service.retrieve(bounds=bounds)
    return service.transform(select_keys=tuple(query["select_keys"]), bounds=bounds)


__all__ = ("P2ProgramError", "execute_program", "interpret")
