"""Public processing warnings preserve known outcomes without private exception text."""

import importlib.util
import unittest


class TestProcessingDiagnostics(unittest.TestCase):
    def module(self):
        name = "asterion.applications.prime.p7.processing_diagnostics"
        self.assertIsNotNone(importlib.util.find_spec(name), "processing diagnostics are missing")
        return __import__(name, fromlist=["DiagnosticLog"])

    def diagnostic(self):
        return {
            "diagnostic_id": "diagnostic-1", "code": "evidence-write-failed",
            "severity": "error", "stage": "validated-not-durable",
            "action_sequence": 97, "outcome_known": True, "durable": False,
            "observed": None, "limit": None, "unit": None,
            "recovery": "pause-and-rebuild",
        }

    def test_repeated_fault_preserves_first_latest_count_and_recovery(self):
        log = self.module().DiagnosticLog()
        first = log.record(self.diagnostic(), timestamp="2026-10-06T00:00:00Z")
        latest = log.record(self.diagnostic(), timestamp="2026-10-06T00:01:00Z")
        self.assertEqual(first["count"], 1)
        self.assertEqual(latest["count"], 2)
        self.assertEqual(latest["first_seen"], first["first_seen"])
        self.assertEqual(latest["last_seen"], "2026-10-06T00:01:00Z")
        log.resolve("diagnostic-1", timestamp="2026-10-06T00:02:00Z")
        projection = log.projection()
        self.assertEqual(projection[0]["status"], "recovered")
        self.assertEqual(projection[0]["count"], 2)
        projection[0]["code"] = "changed"
        self.assertEqual(log.projection()[0]["code"], "evidence-write-failed")

    def test_public_diagnostic_rejects_private_fields_and_text(self):
        validate = self.module().public_diagnostic
        for change in ({"message": "SENTINELSECRET"}, {"code": "/private/SENTINELSECRET"},
                       {"recovery": "Bearer SENTINELSECRET"}, {"stage": "OPENAI_API_KEY=SENTINELSECRET"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate({**self.diagnostic(), **change})

    def test_public_diagnostic_retains_known_result_without_invented_capacity_limit(self):
        result = self.module().public_diagnostic(self.diagnostic())
        self.assertTrue(result["outcome_known"])
        self.assertFalse(result["durable"])
        self.assertIsNone(result["limit"])
        with self.assertRaises(ValueError):
            self.module().public_diagnostic({**self.diagnostic(), "observed": -1})


if __name__ == "__main__":
    unittest.main()
