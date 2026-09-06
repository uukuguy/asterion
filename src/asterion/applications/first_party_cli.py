"""Console wrapper for Asterion's bundled first-party products."""

from __future__ import annotations

import sys
from typing import Any

from asterion.applications.first_party_packages import builtin_capability_registrations
from asterion.applications.provider import ApplicationProviderError
from asterion.benchmarks.cli import InstalledBenchmarkCommandHost
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource
from asterion.capability_packages.sources.distribution import (
    DistributionCapabilityPackageSource,
)
from asterion.cli import _capability_package_sources, main as generic_main


def main(argv: list[str] | None = None, **kwargs: Any) -> int:
    """Run the compatibility CLI with explicit first-party package sources."""

    package_sources = kwargs.pop(
        "package_sources",
        (
            BuiltinCapabilitySource(builtin_capability_registrations()),
            DistributionCapabilityPackageSource(),
        ),
    )
    raw_argv = sys.argv[1:] if argv is None else argv
    if raw_argv[:1] == ["benchmark"]:
        try:
            package_sources = _capability_package_sources(package_sources)
        except ApplicationProviderError:
            stderr = kwargs.get("stderr", sys.stderr)
            stderr.write("asterion: command failed\n")
            return 2
        if "benchmark_host" not in kwargs:
            kwargs["benchmark_host"] = InstalledBenchmarkCommandHost(
                package_sources=package_sources
            )
    return generic_main(argv, package_sources=package_sources, **kwargs)
