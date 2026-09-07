"""Narrow preparation repair for interpreter-generated P7 runtime caches."""

from __future__ import annotations

from pathlib import Path
import re
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
            lib = root / "venv" / "lib"
            if lib.is_symlink() or not stat.S_ISDIR(lib.lstat().st_mode):
                raise ValueError
            sites = [
                child / "site-packages" for child in lib.iterdir()
                if re.fullmatch(r"python[0-9]+\.[0-9]+", child.name)
                and not child.is_symlink() and stat.S_ISDIR(child.lstat().st_mode)
                and not (child / "site-packages").is_symlink()
                and (child / "site-packages").is_dir()
            ]
            if len(sites) != 1:
                raise ValueError
            site = sites[0]
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
