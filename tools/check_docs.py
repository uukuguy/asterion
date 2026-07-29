from __future__ import annotations

import ast
import re
import stat
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
PYTHON_BLOCK_PATTERN = re.compile(
    r"^[ \t]*```python[ \t]*\n(.*?)^[ \t]*```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
COUNT_PATTERN = re.compile(r"\b(?:533/533|538/538)\b")
FORBIDDEN_LITERALS = (
    "uv run --project " + "asterion",
    "../../../docs/superpowers/",
    "/Users/" + "sujiangwen/",
    "90 tests",
    "1230 tests",
    "Run these checks from the parent mixed-repository root",
    "python3 tools/project_scope_check.py",
    "python3 ../tools/project_scope_check.py",
    "npm --prefix asterion/",
    "uv run ruff check asterion/",
    "uv build asterion",
    "make -C ..",
    "from dci.framework.",
)


@dataclass(frozen=True)
class _SourceBinding:
    name: str
    kind: str
    target_module: str | None = None
    target_symbol: str | None = None


@dataclass(frozen=True)
class _ResolvedModule:
    bindings: tuple[_SourceBinding, ...]
    child_roots: tuple[Path, ...]


def _documents(root: Path) -> tuple[Path, ...]:
    return (root / "README.md", *sorted((root / "docs").rglob("*.md")))


def _is_historical_document(path: Path) -> bool:
    return (
        path.parts[:2] == ("docs", "status")
        or path.parts[:3] == ("docs", "superpowers", "plans")
        or path.parts[:3] == ("docs", "superpowers", "specs")
    )


def _link_target(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    return value.split(maxsplit=1)[0]


def check_docs(root: Path) -> tuple[int, int, tuple[str, ...]]:
    project_root = root.resolve()
    documents = _documents(project_root)
    errors: list[str] = []
    local_links = 0

    for document in documents:
        relative = document.relative_to(project_root)
        if not document.is_file():
            errors.append(f"{relative}: missing markdown file")
            continue
        text = document.read_text(encoding="utf-8")
        for literal in FORBIDDEN_LITERALS:
            if literal in text:
                errors.append(f"{relative}: forbidden standalone reference")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if (
                "tools/verify_asterion_dci_product.py" in line
                and "mixed-repository only" not in line
            ):
                errors.append(
                    f"{relative}:{line_number}: mixed verifier lacks integration label"
                )
            if COUNT_PATTERN.search(line) and not re.search(
                r"historical|\u5386\u53f2|mixed-repository", line
            ):
                errors.append(
                    f"{relative}:{line_number}: integration count lacks history label"
                )
        if not _is_historical_document(relative):
            errors.extend(_check_asterion_imports(relative, text))

        for match in LINK_PATTERN.finditer(text):
            target = _link_target(match.group(1))
            if not target or target.startswith("#"):
                continue
            parsed = urlsplit(target)
            if parsed.scheme in {"http", "https", "mailto"}:
                continue
            decoded = unquote(parsed.path)
            candidate = Path(decoded)
            local_links += 1
            if candidate.is_absolute():
                errors.append(f"{relative}: absolute link is not portable")
                continue
            resolved = (document.parent / candidate).resolve()
            if not resolved.is_relative_to(project_root):
                errors.append(f"{relative}: link escapes standalone root")
            elif not resolved.exists():
                errors.append(f"{relative}: local link target is missing")

    return len(documents), local_links, tuple(errors)


def _check_asterion_imports(document: Path, text: str) -> tuple[str, ...]:
    errors: list[str] = []
    for match in PYTHON_BLOCK_PATTERN.finditer(text):
        snippet = textwrap.dedent(match.group(1))
        try:
            trees = (ast.parse(snippet),)
        except SyntaxError:
            trees, invalid = _parse_asterion_import_candidates(snippet)
            if invalid:
                errors.append(f"{document}: documented import is invalid")
        for tree in trees:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if _is_asterion_module(alias.name) and not _resolve_module(
                            alias.name
                        ):
                            errors.append(
                                f"{document}: documented import is unavailable: "
                                f"{alias.name}"
                            )
                elif (
                    isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module is not None
                    and _is_asterion_module(node.module)
                ):
                    resolved = _resolve_module(node.module)
                    if resolved is None:
                        errors.append(
                            f"{document}: documented import is unavailable: "
                            f"{node.module}"
                        )
                        continue
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        if _valid_explicit_symbol(
                            node.module,
                            alias.name,
                            frozenset(),
                        ):
                            continue
                        errors.append(
                            f"{document}: documented import is unavailable: "
                            f"{node.module}.{alias.name}"
                        )
    return tuple(errors)


def _parse_asterion_import_candidates(
    snippet: str,
) -> tuple[tuple[ast.Module, ...], bool]:
    trees: list[ast.Module] = []
    invalid = False
    lines = snippet.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not (
            stripped.startswith("import asterion")
            or stripped.startswith("from asterion")
        ):
            index += 1
            continue

        candidate = [stripped]
        depth = stripped.count("(") - stripped.count(")")
        continued = stripped.endswith("\\")
        index += 1
        while index < len(lines) and (depth > 0 or continued):
            line = lines[index]
            candidate.append(line)
            depth += line.count("(") - line.count(")")
            continued = line.rstrip().endswith("\\")
            index += 1
        try:
            trees.append(ast.parse("\n".join(candidate)))
        except SyntaxError:
            invalid = True
    return tuple(trees), invalid


def _is_asterion_module(name: str) -> bool:
    return name == "asterion" or name.startswith("asterion.")


def _resolve_module(module_name: str) -> _ResolvedModule | None:
    search_roots = _filesystem_search_roots()
    if search_roots is None:
        return None
    resolved: _ResolvedModule | None = None
    parts = module_name.split(".")
    for index, component in enumerate(parts):
        qualified_name = ".".join(parts[: index + 1])
        resolved = _resolve_component(
            component,
            qualified_name,
            search_roots,
        )
        if resolved is None:
            return None
        if index != len(parts) - 1:
            if not resolved.child_roots:
                return None
            search_roots = resolved.child_roots
    return resolved


def _filesystem_search_roots() -> tuple[Path, ...] | None:
    try:
        current_directory = Path.cwd()
    except OSError:
        return None

    roots: list[Path] = []
    for entry in sys.path:
        try:
            root = Path(entry) if entry else current_directory
            if not root.is_absolute():
                root = current_directory / root
        except (OSError, TypeError, ValueError):
            return None
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def _resolve_component(
    component: str,
    qualified_name: str,
    search_roots: tuple[Path, ...],
) -> _ResolvedModule | None:
    namespace_roots: list[Path] = []
    for root in search_roots:
        package_root = root / component
        module_source = root / f"{component}.py"
        try:
            package_mode = _path_mode(package_root)
            if package_mode is not None and stat.S_ISDIR(package_mode):
                init_source = package_root / "__init__.py"
                init_mode = _path_mode(init_source)
                if init_mode is not None and stat.S_ISREG(init_mode):
                    bindings = _source_bindings(
                        init_source,
                        qualified_name,
                        is_package=True,
                    )
                    if bindings is None:
                        return None
                    return _ResolvedModule(bindings, (package_root,))

            module_mode = _path_mode(module_source)
            if module_mode is not None and stat.S_ISREG(module_mode):
                bindings = _source_bindings(
                    module_source,
                    qualified_name,
                    is_package=False,
                )
                if bindings is None:
                    return None
                return _ResolvedModule(bindings, ())

            if package_mode is not None and stat.S_ISDIR(package_mode):
                namespace_roots.append(package_root)
        except OSError:
            return None
    if namespace_roots:
        return _ResolvedModule((), tuple(namespace_roots))
    return None


def _path_mode(path: Path) -> int | None:
    try:
        return path.stat().st_mode
    except FileNotFoundError:
        return None


def _source_bindings(
    source_path: Path,
    module_name: str,
    *,
    is_package: bool,
) -> tuple[_SourceBinding, ...] | None:
    try:
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeError):
        return None

    bindings: dict[str, _SourceBinding] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings[node.name] = _SourceBinding(node.name, "direct")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _assigned_names(target):
                    bindings[name] = _SourceBinding(name, "direct")
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = (node.target,)
            for target in targets:
                for name in _assigned_names(target):
                    bindings[name] = _SourceBinding(name, "direct")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".", 1)[0]
                if _is_asterion_module(alias.name):
                    bindings[name] = _SourceBinding(
                        name,
                        "module",
                        target_module=alias.name,
                    )
                else:
                    bindings[name] = _SourceBinding(name, "unsupported")
        elif isinstance(node, ast.ImportFrom):
            target_module = _import_from_target(
                node,
                module_name,
                is_package=is_package,
            )
            for alias in node.names:
                if alias.name != "*":
                    name = alias.asname or alias.name
                    if target_module is None:
                        # External imports fail closed: this source-only checker
                        # cannot validate them without executing import machinery.
                        bindings[name] = _SourceBinding(name, "unsupported")
                    else:
                        bindings[name] = _SourceBinding(
                            name,
                            "symbol",
                            target_module=target_module,
                            target_symbol=alias.name,
                        )
    return tuple(bindings.values())


def _import_from_target(
    node: ast.ImportFrom,
    module_name: str,
    *,
    is_package: bool,
) -> str | None:
    if node.level == 0:
        target = node.module
    else:
        package_name = (
            module_name
            if is_package
            else module_name.rpartition(".")[0]
        )
        package_parts = package_name.split(".") if package_name else []
        if node.level > len(package_parts):
            return None
        retained = len(package_parts) - node.level + 1
        target_parts = package_parts[:retained]
        if node.module is not None:
            target_parts.extend(node.module.split("."))
        target = ".".join(target_parts)
    if target is None or not _is_asterion_module(target):
        return None
    return target


def _valid_explicit_symbol(
    module_name: str,
    symbol_name: str,
    resolving: frozenset[tuple[str, str]],
) -> bool:
    key = (module_name, symbol_name)
    if key in resolving:
        return False
    resolved = _resolve_module(module_name)
    if resolved is None:
        return False
    binding = next(
        (item for item in resolved.bindings if item.name == symbol_name),
        None,
    )
    if binding is None:
        return _resolve_module(f"{module_name}.{symbol_name}") is not None
    if binding.kind == "direct":
        return True
    if binding.kind == "module":
        return (
            binding.target_module is not None
            and _resolve_module(binding.target_module) is not None
        )
    if (
        binding.kind == "symbol"
        and binding.target_module is not None
        and binding.target_symbol is not None
    ):
        return (
            _valid_explicit_symbol(
                binding.target_module,
                binding.target_symbol,
                resolving | {key},
            )
            or _resolve_module(
                f"{binding.target_module}.{binding.target_symbol}"
            )
            is not None
        )
    return False


def _assigned_names(target: ast.expr) -> frozenset[str]:
    if isinstance(target, ast.Name):
        return frozenset((target.id,))
    if isinstance(target, (ast.List, ast.Tuple)):
        return frozenset(
            name
            for element in target.elts
            for name in _assigned_names(element)
        )
    return frozenset()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    file_count, link_count, errors = check_docs(root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"checked {file_count} markdown files, {link_count} local links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
