from __future__ import annotations

import ast
import re
import sys
import textwrap
from importlib.machinery import ModuleSpec, PathFinder
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


def _documents(root: Path) -> tuple[Path, ...]:
    return (root / "README.md", *sorted((root / "docs").rglob("*.md")))


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
                        if _is_asterion_module(alias.name) and not _module_spec(
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
                    spec = _module_spec(node.module)
                    if spec is None:
                        errors.append(
                            f"{document}: documented import is unavailable: "
                            f"{node.module}"
                        )
                        continue
                    bindings = _source_bindings(spec)
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        if alias.name in bindings:
                            continue
                        if _module_spec(f"{node.module}.{alias.name}") is not None:
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


def _module_spec(module_name: str) -> ModuleSpec | None:
    search_path = None
    parts = module_name.split(".")
    for count in range(1, len(parts) + 1):
        qualified_name = ".".join(parts[:count])
        try:
            spec = PathFinder.find_spec(qualified_name, search_path)
        except (AttributeError, ImportError, OSError, ValueError):
            return None
        if spec is None:
            return None
        if count != len(parts):
            locations = spec.submodule_search_locations
            if locations is None:
                return None
            search_path = locations
    return spec


def _source_bindings(spec: ModuleSpec) -> frozenset[str]:
    origin = spec.origin
    if origin is None or not origin.endswith(".py"):
        return frozenset()
    try:
        source = Path(origin).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeError):
        return frozenset()

    bindings: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            for target in targets:
                bindings.update(_assigned_names(target))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bindings.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    bindings.add(alias.asname or alias.name)
    return frozenset(bindings)


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
