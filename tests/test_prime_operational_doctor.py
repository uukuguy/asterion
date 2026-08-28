from __future__ import annotations

import unittest

from tests.test_operation_doctor import _doctor_request, _doctor_service, _doctor_transaction


class TestPrimeOperationalDoctor(unittest.IsolatedAsyncioTestCase):
    async def test_doctor_is_read_only_and_never_claims_repair(self) -> None:
        service, probes = _doctor_service()

        receipt = await service.execute(_doctor_transaction("doctor-prime-1"), _doctor_request())

        self.assertEqual((receipt.status, receipt.reason_code), ("succeeded", "doctor-report-ready"))
        self.assertEqual(len(service.reports), 1)
        self.assertEqual([probe.calls for probe in probes], [1, 1])  # type: ignore[attr-defined]
        for counter, count in receipt.effect_counts.items():
            with self.subTest(counter=counter):
                self.assertEqual(count, 0)
