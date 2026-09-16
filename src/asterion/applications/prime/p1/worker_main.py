"""Installed trusted P1 worker entry point; restrictions are not an OS sandbox.

Only this module owns the IPython namespace and instrumentation channel. Cell
code is validated before IPython executes it; no host/oracle object is seeded.
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import sys
import types
import uuid
from contextlib import redirect_stderr, redirect_stdout

from IPython.core.interactiveshell import InteractiveShell
from IPython.core.interactiveshell import ExecutionInfo, ExecutionResult
from traitlets.config import Config

CODE_CAP = 16384
OUTPUT_CAP = 65536
WIRE_CAP = 524288
WRITE_CALL_CAP = 4096
WRITE_CELL_CAP = 16384
ROOT_BYTES_CAP = 32768
ROOT_FILE_CAP = 32


class _Denied(RuntimeError):
    pass


class _Output(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.size = 0

    def write(self, text: str) -> int:
        self.size += len(text.encode("utf-8"))
        if self.size > OUTPUT_CAP:
            raise _Denied("P1 cell output rejected")
        return super().write(text)


class _ReadFile:
    def __init__(self, stream, state: dict, tracked: bool, append: bool) -> None:
        self._stream, self._state, self._tracked = stream, state, tracked
        self._append = append

    def read(self, size: int = -1):
        value = self._stream.read(size)
        if self._tracked:
            self._state["file_reads"] += 1
            data = value.encode("utf-8") if type(value) is str else value
            self._state["file_read_sha256"].append(hashlib.sha256(data).hexdigest())
        return value

    def write(self, value):
        state = self._state
        if type(value) not in {str, bytes, bytearray} or len(value) > WRITE_CALL_CAP:
            state["audit_denials"] += 1
            raise _Denied("P1 file write rejected")
        data = value.encode("utf-8") if type(value) is str else value
        size = len(data)
        info = os.fstat(self._stream.fileno())
        identity = (info.st_dev, info.st_ino)
        position = info.st_size if self._append else self._stream.tell()
        projected = max(info.st_size, position + size)
        projected_total = (
            sum(state["root_sizes"].values())
            - state["root_sizes"].get(identity, 0)
            + projected
        )
        if (
            size > WRITE_CALL_CAP
            or state["cell_write_bytes"] + size > WRITE_CELL_CAP
            or projected_total > ROOT_BYTES_CAP
        ):
            state["audit_denials"] += 1
            raise _Denied("P1 file write rejected")
        state["cell_write_bytes"] += size
        result = self._stream.write(value)
        self._stream.flush()
        state["root_sizes"][identity] = os.fstat(self._stream.fileno()).st_size
        if self._tracked:
            self._state["file_write_calls"] += 1
            self._state["file_write_bytes"] += size
        return result

    def close(self) -> None:
        self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *unused) -> None:
        self.close()


def _root_sizes(directory_fd: int) -> dict[tuple[int, int], int]:
    """Count logical regular-file bytes through the held root descriptor."""
    result = {}
    for name in os.listdir(directory_fd):
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child_fd = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd
            )
            try:
                result.update(_root_sizes(child_fd))
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(info.st_mode):
            result[(info.st_dev, info.st_ino)] = info.st_size
    return result


def _safe_underscore_names(tree: ast.AST) -> set[str]:
    """Single-underscore names whose every read provably follows a binding.

    A cell may name its own locals whatever it likes, including with a leading
    underscore, but only a binding that has actually happened makes it safe:
    an unbound underscore name falls through to the IPython namespace. So the
    walk is order-aware *and* scope-aware, and deliberately conservative.

    Admitted: a plain "bind it, then use it" in the same block, a `with ... as`
    name inside its own body, a loop target inside its own body, and a
    parameter inside its own function.

    Never admitted: a binding made inside an `if`, a `try`, a loop body or a
    comprehension, for code outside it — nothing proves it ran. Reading before
    the binding, in the same block, is not admitted either.
    """
    safe: set[str] = set()

    def guarded(name: str) -> bool:
        return name.startswith("_") and not name.startswith("__")

    def note_reads(node: ast.AST | list | None, bound: set[str]) -> None:
        if node is None:
            return
        nodes = node if isinstance(node, list) else [node]
        for candidate in nodes:
            for child in ast.walk(candidate):
                if (
                    isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Load)
                    and guarded(child.id)
                    and child.id in bound
                ):
                    safe.add(child.id)

    def store_names(node: ast.AST | list | None) -> set[str]:
        if node is None:
            return set()
        nodes = node if isinstance(node, list) else [node]
        found: set[str] = set()
        for candidate in nodes:
            for child in ast.walk(candidate):
                if (
                    isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Store)
                    and guarded(child.id)
                ):
                    found.add(child.id)
        return found

    def walk_body(statements: list[ast.stmt], bound: set[str]) -> None:
        for statement in statements:
            walk_statement(statement, bound)

    def walk_statement(statement: ast.stmt, bound: set[str]) -> None:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            note_reads(statement.decorator_list, bound)
            note_reads(statement.args.defaults, bound)
            inner = set(bound)
            arguments = statement.args
            for argument in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
            ):
                inner.add(argument.arg)
            for optional in (arguments.vararg, arguments.kwarg):
                if optional is not None:
                    inner.add(optional.arg)
            walk_body(statement.body, inner)
            return
        if isinstance(statement, ast.ClassDef):
            walk_body(statement.body, set(bound))
            return
        if isinstance(statement, ast.With):
            inner = set(bound)
            for item in statement.items:
                note_reads(item.context_expr, bound)
                inner |= store_names(item.optional_vars)
            walk_body(statement.body, inner)
            return
        if isinstance(statement, ast.Assign):
            note_reads(statement.value, bound)
            bound |= store_names(statement.targets)
            return
        if isinstance(statement, ast.AnnAssign):
            if statement.value is not None:
                note_reads(statement.value, bound)
            bound |= store_names(statement.target)
            return
        if isinstance(statement, ast.AugAssign):
            # `_a += 1` reads its target before writing it.
            note_reads(statement.target, bound)
            note_reads(statement.value, bound)
            bound |= store_names(statement.target)
            return
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            note_reads(statement.iter, bound)
            walk_body(statement.body, bound | store_names(statement.target))
            note_reads(statement.orelse, bound)
            walk_body(statement.orelse, set(bound))
            return
        if isinstance(statement, ast.If):
            note_reads(statement.test, bound)
            walk_body(statement.body, set(bound))
            walk_body(statement.orelse, set(bound))
            return
        if isinstance(statement, ast.While):
            note_reads(statement.test, bound)
            walk_body(statement.body, set(bound))
            walk_body(statement.orelse, set(bound))
            return
        if isinstance(statement, ast.Try):
            walk_body(statement.body, set(bound))
            for handler in statement.handlers:
                note_reads(handler.type, bound)
                inner = set(bound)
                if handler.name is not None:
                    inner.add(handler.name)
                walk_body(handler.body, inner)
            walk_body(statement.orelse, set(bound))
            walk_body(statement.finalbody, set(bound))
            return
        # Any other statement reads against the bindings already made, and
        # contributes none of its own.
        note_reads(statement, bound)

    if isinstance(tree, ast.Module):
        walk_body(tree.body, set())
    return safe


def _validate(tree: ast.AST, state: dict) -> None:
    forbidden_names = {
        "eval",
        "exec",
        "compile",
        "get_ipython",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "type",
        "object",
        "super",
        "help",
        "breakpoint",
        "exit",
        "quit",
        "display",
        "oracle",
        "host",
    }
    safe = _safe_underscore_names(tree)
    for node in ast.walk(tree):
        bad = isinstance(
            node,
            (
                ast.Global,
                ast.Nonlocal,
                ast.Delete,
                ast.AsyncFunctionDef,
                ast.Await,
                ast.Match,
            ),
        )
        if isinstance(node, ast.Name):
            bad = (
                bad
                or node.id in forbidden_names
                # Dunder names reach interpreter internals (`__builtins__`,
                # `__import__`, `__loader__`) whether or not the cell binds
                # one, so they stay denied in every position.
                or node.id.startswith("__")
                # A single-underscore name is admitted only where the cell
                # provably bound it first; anywhere else it may read
                # interpreter state, such as the IPython history buffers.
                or node.id.startswith("_")
                and node.id not in safe
            )
        if isinstance(node, ast.Attribute):
            bad = (
                bad
                or node.attr.startswith("_")
                or node.attr in {"format", "format_map"}
            )
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
            )
            bad = bad or any(name not in {"json", "hashlib", "math"} for name in names)
            bad = (
                bad
                or isinstance(node, ast.ImportFrom)
                and (
                    node.level != 0
                    or any(alias.name.startswith("_") for alias in node.names)
                )
            )
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            bad = bad or bool(node.decorator_list)
            bad = (
                bad
                or node.name.startswith("_")
                and node.name not in {"__init__", "__call__"}
            )
            if isinstance(node, ast.ClassDef):
                bad = bad or bool(node.bases or node.keywords)
        if bad:
            state["audit_denials"] += 1
            raise _Denied("P1 cell rejected")


async def _serve(root_fd: int, input_tuple: tuple, task_statement: str) -> None:
    root_stat = os.fstat(root_fd)
    cwd_stat = os.stat(".")
    if not stat.S_ISDIR(root_stat.st_mode) or (root_stat.st_dev, root_stat.st_ino) != (
        cwd_stat.st_dev,
        cwd_stat.st_ino,
    ):
        return
    root_path = Path.cwd()
    namespace_nonce = uuid.uuid4().hex
    # IPython performs its trusted imports and setup before cell restrictions.
    shell = InteractiveShell(
        user_ns={},
        ipython_dir=str(root_path / ".ipython"),
        config=Config({"HistoryManager": {"enabled": False, "hist_file": ":memory:"}}),
    )
    if shell.history_manager is not None:
        shell.history_manager.enabled = False
    shell.showtraceback = lambda *args, **kwargs: None
    # Warm IPython's execution imports before narrowing access.
    await shell.run_code(compile("pass", "<p1-init>", "exec"))
    state = {
        "active": False,
        "allowed_code": None,
        "audit_denials": 0,
        "file_reads": 0,
        "file_read_sha256": [],
        "file_write_calls": 0,
        "file_write_bytes": 0,
        "file_write_opens": 0,
        "cell_write_bytes": 0,
        "root_sizes": _root_sizes(root_fd),
        "fd_open": False,
    }
    module_surfaces = {
        "json": types.SimpleNamespace(dumps=json.dumps, loads=json.loads),
        "hashlib": types.SimpleNamespace(sha256=hashlib.sha256),
        "math": types.SimpleNamespace(
            **{
                name: getattr(math, name)
                for name in ("ceil", "floor", "sqrt", "isfinite", "gcd", "pi", "e")
            }
        ),
    }

    def deny() -> None:
        state["audit_denials"] += 1
        raise _Denied("P1 cell rejected")

    def audited(event: str, args: tuple) -> None:
        if not state["active"]:
            return
        if event.startswith(
            (
                "socket.",
                "subprocess.",
                "ctypes.",
                "os.exec",
                "os.spawn",
                "os.fork",
                "os.posix_spawn",
            )
        ) or event in {
            "os.system",
            "os.putenv",
            "os.unsetenv",
            "sys.settrace",
            "sys.setprofile",
            "os.chdir",
            "os.fchdir",
        }:
            deny()
        if event == "exec" and args[0] is not state["allowed_code"]:
            deny()
        if event == "open" and not state["fd_open"]:
            path = args[0]
            if type(path) is not str:
                deny()
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = root_path / candidate
            if not candidate.resolve().is_relative_to(root_path):
                deny()

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level != 0 or name not in module_surfaces:
            deny()
        return module_surfaces[name]

    def safe_open(path, mode="r", *, encoding=None):
        if (
            type(path) is not str
            or type(mode) is not str
            or mode not in {"r", "rb", "w", "wb", "a", "ab", "x", "xb"}
            or encoding not in {None, "utf-8"}
        ):
            deny()
        parts = Path(path).parts
        if (
            not parts
            or Path(path).is_absolute()
            or any(part in {"..", "."} for part in parts)
        ):
            deny()
        parent_fd = os.dup(root_fd)
        try:
            state["fd_open"] = True
            for part in parts[:-1]:
                next_fd = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
                )
                os.close(parent_fd)
                parent_fd = next_fd
            flags = os.O_RDONLY if mode[0] == "r" else os.O_WRONLY | os.O_CREAT
            if mode[0] != "r" and len(state["root_sizes"]) >= ROOT_FILE_CAP:
                try:
                    os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    deny()
            if mode[0] == "w":
                flags |= os.O_TRUNC
            if mode[0] == "a":
                flags |= os.O_APPEND
            if mode[0] == "x":
                flags |= os.O_EXCL
            fd = os.open(
                parts[-1],
                flags | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=parent_fd,
            )
            file_info = os.fstat(fd)
            if not stat.S_ISREG(file_info.st_mode):
                os.close(fd)
                deny()
            stream = os.fdopen(
                fd, mode, encoding=None if "b" in mode else (encoding or "utf-8")
            )
            state["root_sizes"][(file_info.st_dev, file_info.st_ino)] = (
                file_info.st_size
            )
            tracked = parts == ("stage-one.json",)
            if tracked and mode[0] != "r":
                state["file_write_opens"] += 1
            return _ReadFile(stream, state, tracked, mode[0] == "a")
        except OSError:
            deny()
        finally:
            state["fd_open"] = False
            os.close(parent_fd)

    allowed = (
        "abs",
        "all",
        "any",
        "bool",
        "bytes",
        "bytearray",
        "dict",
        "enumerate",
        "float",
        "int",
        "isinstance",
        "issubclass",
        "len",
        "list",
        "max",
        "min",
        "pow",
        "print",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
        "Exception",
        "ValueError",
        "AssertionError",
        "id",
        "__build_class__",
    )
    cell_builtins = {name: getattr(builtins, name) for name in allowed}
    cell_builtins.update({"open": safe_open, "__import__": safe_import})
    namespace = {
        "__builtins__": cell_builtins,
        "__name__": "p1_cell",
        "input_tuple": input_tuple,
        "task_statement": task_statement,
    }
    shell.user_ns.clear()
    shell.user_ns.update(namespace)
    namespace = shell.user_ns
    # IPython normally adds rich hooks. The low-level code path uses only this namespace.
    os.environ.clear()
    sys.addaudithook(audited)
    output_stream = sys.stdout

    def emit(value: dict) -> None:
        encoded = json.dumps(value, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode()) > WIRE_CAP:
            raise _Denied("P1 worker frame rejected")
        output_stream.write(encoded + "\n")
        output_stream.flush()

    emit(
        {
            "type": "ready",
            "pid": os.getpid(),
            "namespace_nonce": namespace_nonce,
            "cwd": [root_stat.st_dev, root_stat.st_ino],
            "seeded_symbols": ["input_tuple", "task_statement"],
        }
    )
    seen = set()
    sequence = 0
    while True:
        line = sys.stdin.buffer.readline(WIRE_CAP + 1)
        if not line:
            return
        if len(line) > WIRE_CAP or not line.endswith(b"\n"):
            return
        try:
            request = json.loads(line)
            if (
                set(request) != {"type", "request_id", "turn_id", "code"}
                or request["type"] != "cell"
            ):
                return
            code, request_id = request["code"], request["request_id"]
            if (
                type(code) is not str
                or not 0 < len(code.encode()) <= CODE_CAP
                or type(request_id) is not str
                or request_id in seen
            ):
                return
            seen.add(request_id)
            sequence += 1
            state["file_reads"] = 0
            state["file_read_sha256"] = []
            state["file_write_calls"] = 0
            state["file_write_bytes"] = 0
            state["file_write_opens"] = 0
            state["cell_write_bytes"] = 0
            state["root_sizes"] = _root_sizes(root_fd)
            if (
                sum(state["root_sizes"].values()) > ROOT_BYTES_CAP
                or len(state["root_sizes"]) > ROOT_FILE_CAP
            ):
                state["audit_denials"] += 1
            calls = []

            def profile(frame, event, arg):
                if event == "return" and frame.f_code.co_name == "__call__":
                    names = frame.f_code.co_varnames
                    if len(names) >= 2:
                        instance = frame.f_locals.get(names[0])
                        value = frame.f_locals.get(names[1])
                        if type(value) is int and type(arg) is int and len(calls) < 128:
                            calls.append([id(instance), value, arg])

            buffer = _Output()
            failed = False
            try:
                tree = ast.parse(code, mode="exec")
                _validate(tree, state)
                compiled = compile(tree, "<p1-cell>", "exec")
                state["allowed_code"] = compiled
                sys.setprofile(profile)
                state["active"] = True
                with redirect_stdout(buffer), redirect_stderr(buffer):
                    result = ExecutionResult(
                        ExecutionInfo(code, False, True, False, None)
                    )
                    failed = await shell.run_code(compiled, result=result)
            except BaseException:
                failed = True
            finally:
                state["active"] = False
                sys.setprofile(None)
                state["allowed_code"] = None
            failed = failed or state["audit_denials"] > 0 or buffer.size > OUTPUT_CAP
            instance = namespace.get("accumulator")
            cls = namespace.get("AffineAccumulator")
            class_name = None
            probe = None
            if type(cls) is type and type(instance) is cls:
                class_name = cls.__name__
                function = cls.__dict__.get("__call__")
                attrs = object.__getattribute__(instance, "__dict__")
                if type(function) is types.FunctionType and all(
                    type(v) in {int, str, bool, float} for v in attrs.values()
                ):
                    try:
                        clone = object.__new__(cls)
                        object.__getattribute__(clone, "__dict__").update(attrs)
                        pure_builtins = {
                            name: value
                            for name, value in cell_builtins.items()
                            if name not in {"open", "__import__", "print"}
                        }
                        pure = types.FunctionType(
                            function.__code__, {"__builtins__": pure_builtins}
                        )
                        with redirect_stdout(buffer), redirect_stderr(buffer):
                            values = [
                                pure(clone, input_tuple[2]),
                                pure(clone, input_tuple[3]),
                            ]
                        if all(type(v) is int for v in values):
                            probe = values
                    except BaseException:
                        pass
            verified = namespace.get("stage_one_verified")
            if type(verified) is not dict or any(
                type(k) is not str or type(v) not in {int, str, bool}
                for k, v in verified.items()
            ):
                verified = None
            final = namespace.get("final_result")
            emit(
                {
                    "type": "cell",
                    "request_id": request_id,
                    "turn_id": request["turn_id"],
                    "sequence": sequence,
                    "status": "uncertain" if failed else "completed",
                    "output": "" if failed else buffer.getvalue(),
                    "accumulator_id": None if instance is None else id(instance),
                    "class_name": class_name,
                    "callable_probe": probe,
                    "stage_one_verified": verified,
                    "final_result": final if type(final) is int else None,
                    "call_observations": calls,
                    "file_reads": state["file_reads"],
                    "file_read_sha256": state["file_read_sha256"],
                    "file_write_calls": state["file_write_calls"],
                    "file_write_bytes": state["file_write_bytes"],
                    "file_write_opens": state["file_write_opens"],
                    "cell_write_bytes": state["cell_write_bytes"],
                    "root_bytes": sum(state["root_sizes"].values()),
                    "audit_denials": state["audit_denials"],
                }
            )
            if failed:
                return
        except BaseException:
            return


def main() -> None:
    try:
        # Seeds travel privately over stdin; source/package is never searched from cwd.
        root_fd = int(sys.argv[1])
        line = sys.stdin.buffer.readline(WIRE_CAP + 1)
        if len(line) > WIRE_CAP:
            return
        seed = json.loads(line)
        if set(seed) != {"input_tuple", "task_statement"}:
            return
        asyncio.run(_serve(root_fd, tuple(seed["input_tuple"]), seed["task_statement"]))
    except BaseException:
        return


if __name__ == "__main__":
    main()
