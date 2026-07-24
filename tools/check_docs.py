from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
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
