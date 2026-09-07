"""Narrow preparation repair for interpreter-generated P7 runtime caches."""

from __future__ import annotations

from pathlib import Path
import shutil
import stat
from typing import Callable, TypeVar

T = TypeVar("T")


def verify_p7_runtime_after_cache_repair(root: Path, verify: Callable[[Path], T]) -> T:
    """Retry once after removing only verified ARC package bytecode caches."""

    try:
        return verify(root)
    except Exception as first:
        try:
            site = root / "venv" / "lib" / "python3.11" / "site-packages"
            if site.is_symlink() or not stat.S_ISDIR(site.lstat().st_mode):
                raise ValueError
            for package in ("arc_agi", "arcengine"):
                directory = site / package
                cache = directory / "__pycache__"
                if directory.is_symlink() or not stat.S_ISDIR(directory.lstat().st_mode):
                    raise ValueError
                if cache.exists():
                    if cache.is_symlink() or not stat.S_ISDIR(cache.lstat().st_mode):
                        raise ValueError
                    for child in cache.rglob("*"):
                        if child.is_symlink() or not child.is_file():
                            raise ValueError
                    shutil.rmtree(cache)
            return verify(root)
        except Exception:
            raise first


__all__ = ("verify_p7_runtime_after_cache_repair",)
