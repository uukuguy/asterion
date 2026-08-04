"""Bright optimization finalization stays evidence-closed and body-free."""

from __future__ import annotations

import unittest
from pathlib import Path


class TestBrightOptimizationFinalization(unittest.TestCase):
    def test_public_finalizer_exports_the_exact_pre_registered_criteria(self) -> None:
        from asterion.capabilities.dci.implementation.pathlight.optimization import (
            BRIGHT_OPTIMIZATION_CRITERIA,
            finalize_bright_optimization,
        )

        self.assertEqual(
            (
                BRIGHT_OPTIMIZATION_CRITERIA.minimum_mean_gain_microunits,
                BRIGHT_OPTIMIZATION_CRITERIA.maximum_cost_increase_microunits,
                BRIGHT_OPTIMIZATION_CRITERIA.maximum_time_increase_microunits,
            ),
            (50_000, 250_000, 250_000),
        )
        self.assertTrue(callable(finalize_bright_optimization))

    def test_native_case_lineage_reader_rejects_missing_native_root(self) -> None:
        from asterion.capabilities.dci.implementation.pathlight.optimization import (
            DciBrightOptimizationError,
            read_native_case_lineage,
        )

        with self.assertRaises(DciBrightOptimizationError):
            read_native_case_lineage(Path("/definitely-not-a-native-root"), "bright.biology")
