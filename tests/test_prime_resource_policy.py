from dataclasses import FrozenInstanceError, asdict
import unittest

from asterion.agents.prime.compaction_budget import (
    ModelPrice, PrimeCompactionPolicy, _quote_from_json,
    quote_compaction_reservation,
)
from asterion.services.diagnostics import ResourceLimitExceeded


class TestPrimeResourcePolicy(unittest.TestCase):
    def test_default_and_invalid_values(self):
        self.assertEqual(asdict(PrimeCompactionPolicy()), {
            "max_total_tokens": 262144, "max_frame_bytes": 16777216,
            "max_material_bytes": 65536,
        })
        for changes in ({"max_total_tokens": True}, {"max_total_tokens": 0},
                        {"max_frame_bytes": 2**32}, {"max_frame_bytes": 0},
                        {"max_material_bytes": 16777216}, {"max_material_bytes": -1},
                        {"max_material_bytes": 1.5}, {"max_total_tokens": 2**53}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                PrimeCompactionPolicy(**changes)
        with self.assertRaises(FrozenInstanceError):
            PrimeCompactionPolicy().max_total_tokens = 1

    def test_unequal_branches_and_component_rounding(self):
        quote = quote_compaction_reservation(branch_input_caps=(40000, 1000),
            branch_output_caps=(3276, 3276), price=ModelPrice(1, 1))
        self.assertEqual(quote.reserved_tokens, 47552)
        self.assertEqual(quote.cost_micro_units, 4)
        self.assertEqual(tuple(branch.cost_micro_units for branch in quote.branch_quotes), (2, 2))
        with self.assertRaises(ResourceLimitExceeded) as caught:
            quote_compaction_reservation(branch_input_caps=(40000, 1000),
                branch_output_caps=(3276, 3276), price=ModelPrice(1, 1),
                policy=PrimeCompactionPolicy(max_total_tokens=16000),
                config_source="application")
        diagnostic = caught.exception.limit_diagnostic
        self.assertEqual(diagnostic.limit, 16000)
        self.assertEqual(diagnostic.observed, 47552)
        self.assertEqual(diagnostic.measurement, "conservative-bound")
        self.assertEqual(diagnostic.config_source, "application")

    def test_source_retains_explicit_application_default_origin(self):
        for source in ("framework-default", "application", "operator", "authority"):
            with self.subTest(source=source), self.assertRaises(ResourceLimitExceeded) as caught:
                quote_compaction_reservation(branch_input_caps=(262145, 0),
                    branch_output_caps=(0, 0), price=ModelPrice(0, 0),
                    policy=PrimeCompactionPolicy(), config_source=source)
            self.assertEqual(caught.exception.limit_diagnostic.config_source, source)

    def test_token_boundary_and_no_fixed_output_or_cost_ceiling(self):
        quote = quote_compaction_reservation(branch_input_caps=(100000, 100000),
            branch_output_caps=(31072, 31072), price=ModelPrice(1_000_000, 1_000_000))
        self.assertEqual(quote.reserved_tokens, 262144)
        self.assertEqual(quote.cost_micro_units, 262144)
        with self.assertRaises(ResourceLimitExceeded) as caught:
            quote_compaction_reservation(branch_input_caps=(100001, 100000),
                branch_output_caps=(31072, 31072), price=ModelPrice(0, 0))
        self.assertEqual(caught.exception.limit_diagnostic.config_source, "framework-default")

    def test_caps_types_components_and_aggregates_must_be_safe(self):
        valid = {"branch_input_caps": (1, 1), "branch_output_caps": (1, 1), "price": ModelPrice(0, 0),
                 "policy": PrimeCompactionPolicy(max_total_tokens=2**53-1)}
        for field in ("branch_input_caps", "branch_output_caps"):
            for value in ([1, 1], (1,), (1, 1, 1), (True, 1), (-1, 1), (1.5, 1), (2**53, 1)):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "^invalid compaction reservation$"):
                    quote_compaction_reservation(**(valid | {field: value}))
        for changes in ({"price": object()}, {"policy": object()}, {"config_source": "PRIVATE"},
                        {"config_source": []}, {"branch_input_caps": (2**53-1, 1)},
                        {"branch_input_caps": (2**52, 2**52)},
                        {"price": ModelPrice(2**53-1, 0), "branch_input_caps": (1_000_001, 0)},
                        {"price": ModelPrice(2**53-1, 2**53-1),
                         "branch_input_caps": (600_000, 0), "branch_output_caps": (600_000, 0)},
                        {"price": ModelPrice(2**53-1, 0), "branch_input_caps": (600_000, 600_000)}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "^invalid compaction reservation$"):
                quote_compaction_reservation(**(valid | changes))

    def test_cli_payload_keeps_legacy_shape(self):
        payload = {"branch_input_caps": [40000, 1000], "branch_output_caps": [3276, 3276],
                   "price": {"input_per_million": 1, "output_per_million": 1}}
        self.assertEqual(_quote_from_json(payload).reserved_tokens, 47552)
        with self.assertRaises(ValueError):
            _quote_from_json(payload | {"policy": {"max_total_tokens": 50000}})
