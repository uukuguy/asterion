from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from asterion.control.host import ControlEvent
from asterion.control.authority import (
    ActionReceipt,
    AuthorityEnvelope,
    AuthorityError,
    AuthorityLedger,
    BudgetLimit,
    RemainingBudget,
    BudgetUsage,
    PortfolioGrant,
    ProviderUsageReport,
)


ROOT = Path(__file__).resolve().parents[1]
PROPOSAL_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "agent_control"
    / "v1"
    / "valid-event-action-proposed.json"
)


def _proposal(**payload_changes: object) -> ControlEvent:
    value = json.loads(PROPOSAL_FIXTURE.read_text())
    payload = value["payload"]
    assert isinstance(payload, dict)
    value["payload"] = {**payload, **payload_changes}
    return ControlEvent.from_mapping(value)


def _limit(**changes: int) -> BudgetLimit:
    return BudgetLimit(
        controller_tokens=changes.get("controller_tokens", 1000),
        application_tokens=changes.get("application_tokens", 1000),
        child_tokens=changes.get("child_tokens", 1000),
        aggregate_tokens=changes.get("aggregate_tokens", 3000),
        cost_micros=changes.get("cost_micros", 100_000),
    )


def _envelope(**changes: object) -> AuthorityEnvelope:
    values: dict[str, object] = {
        "authority_id": "authority-1",
        "revision": 1,
        "allowed_portfolio": (
            PortfolioGrant(
                provider_id="example.provider",
                application_id="alpha",
                version="1.0.0",
                runtime_id="fake.runtime",
            ),
        ),
        "allowed_operations": ("application.invoke", "child.spawn"),
        "budget_limit": _limit(),
        "expires_at_ms": 100_000,
        "max_action_deadline_ms": 20_000,
        "max_recursion_depth": 2,
        "max_concurrent_children": 2,
        "execution_domain": "restricted",
        "host_service_grants": ("artifact.write",),
        "cancelled": False,
    }
    values.update(changes)
    return AuthorityEnvelope(**values)  # type: ignore[arg-type]


class TestControlAuthority(unittest.TestCase):
    def test_remaining_budget_subtracts_effective_usage_and_reservations(self) -> None:
        ledger = AuthorityLedger(_envelope())
        ledger.record_provider_usage(
            ProviderUsageReport(BudgetUsage(30, 20, 0, 50, 7))
        )
        decision = ledger.evaluate(_proposal(), now_ms=1_000)
        ledger.reserve(decision)

        self.assertEqual(
            ledger.remaining_budget(now_ms=90_000),
            RemainingBudget(970, 880, 1000, 2850, 94_993, 10_000),
        )
        self.assertEqual(
            AuthorityLedger(_envelope(cancelled=True)).remaining_budget(now_ms=1_000),
            RemainingBudget(0, 0, 0, 0, 0, 0),
        )
        self.assertEqual(
            AuthorityLedger(_envelope()).remaining_budget(now_ms=100_000),
            RemainingBudget(0, 0, 0, 0, 0, 0),
        )

    def test_cumulative_provider_usage_is_maxed_not_double_counted(self) -> None:
        ledger = AuthorityLedger(_envelope())
        ledger.record_provider_usage(
            ProviderUsageReport(BudgetUsage(30, 80, 0, 110, 7))
        )
        decision = ledger.evaluate(_proposal(), now_ms=1_000)
        ledger.reserve(decision)
        ledger.settle(
            "action-1",
            ActionReceipt("action-1", "receipt-1", BudgetUsage(0, 80, 0, 80, 7)),
        )
        self.assertEqual(ledger.usage, BudgetUsage(30, 80, 0, 110, 7))

    def test_controller_report_and_disjoint_receipt_have_coherent_aggregate(self) -> None:
        ledger = AuthorityLedger(_envelope())
        ledger.record_provider_usage(ProviderUsageReport(BudgetUsage(30, 0, 0, 30, 0)))
        decision = ledger.evaluate(_proposal(), now_ms=1_000)
        ledger.reserve(decision)
        ledger.settle("action-1", ActionReceipt("action-1", "receipt-1", BudgetUsage(0, 80, 0, 80, 0)))
        self.assertEqual(ledger.usage.aggregate_tokens, 110)

    def test_provider_reports_are_monotonic_coherent_and_immutable_on_failure(self) -> None:
        ledger = AuthorityLedger(_envelope())
        report = ProviderUsageReport(BudgetUsage(10, 0, 0, 10, 0))
        ledger.record_provider_usage(report)
        for invalid in (
            ProviderUsageReport(BudgetUsage(5, 0, 0, 5, 0)),
        ):
            with self.assertRaises(AuthorityError):
                ledger.record_provider_usage(invalid)
            self.assertEqual(ledger.reported_usage, report.usage)
        with self.assertRaises(AuthorityError):
            ProviderUsageReport(BudgetUsage(10, 1, 0, 10, 0))

    def test_sequential_settlements_and_report_exhaust_later_admission(self) -> None:
        ledger = AuthorityLedger(
            _envelope(budget_limit=_limit(child_tokens=100, aggregate_tokens=100))
        )
        budget = {
            "controller_tokens": 0, "application_tokens": 0, "child_tokens": 30,
            "aggregate_tokens": 30, "cost_micros": 0, "deadline_ms": 1_000,
        }
        for action_id in ("action-1", "action-2"):
            decision = ledger.evaluate(
                _proposal(action_id=action_id, idempotency_key=f"key-{action_id}", budget=budget),
                now_ms=1_000,
            )
            ledger.reserve(decision)
            ledger.settle(
                action_id,
                ActionReceipt(action_id, f"receipt-{action_id}", BudgetUsage(0, 0, 30, 30, 0)),
            )
        ledger.record_provider_usage(ProviderUsageReport(BudgetUsage(20, 0, 0, 20, 0)))
        self.assertEqual(ledger.usage, BudgetUsage(20, 0, 60, 80, 0))
        third = ledger.evaluate(
            _proposal(
                action_id="action-3", idempotency_key="key-action-3",
                budget={**budget, "child_tokens": 50, "aggregate_tokens": 50},
            ), now_ms=1_000,
        )
        self.assertEqual(third.reason, "budget-exceeded")
    def test_evaluate_does_not_mutate_and_reserve_settle_are_idempotent(self) -> None:
        ledger = AuthorityLedger(_envelope())
        proposal = _proposal()

        decision = ledger.evaluate(proposal, now_ms=1_000)

        self.assertEqual(decision.status, "admitted")
        self.assertEqual(decision.reason, "authorized")
        self.assertEqual(ledger.usage, BudgetUsage.zero())
        ledger.reserve(decision)
        ledger.reserve(decision)
        self.assertEqual(ledger.reserved_action_ids, ("action-1",))

        receipt = ActionReceipt(
            action_id="action-1",
            receipt_ref="receipt-1",
            usage=BudgetUsage(
                controller_tokens=0,
                application_tokens=80,
                child_tokens=0,
                aggregate_tokens=80,
                cost_micros=4_000,
            ),
        )
        ledger.settle("action-1", receipt)
        ledger.settle("action-1", receipt)
        self.assertEqual(ledger.usage, receipt.usage)
        self.assertEqual(ledger.reserved_action_ids, ())

    def test_rejects_target_operation_and_stale_revision_without_reservation(self) -> None:
        ledger = AuthorityLedger(_envelope())
        cases = (
            (
                _proposal(
                    target={
                        "kind": "application",
                        "provider_id": "example.provider",
                        "application_id": "zeta",
                        "version": "2.0.0",
                        "runtime_id": "fake.runtime",
                    }
                ),
                "target-not-authorized",
            ),
            (
                _proposal(
                    kind="goal.complete",
                    target={"kind": "goal", "goal_id": "goal-1"},
                ),
                "operation-not-authorized",
            ),
            (_proposal(authority_revision=2), "authority-revision-mismatch"),
        )
        for proposal, reason in cases:
            with self.subTest(reason=reason):
                decision = ledger.evaluate(proposal, now_ms=1_000)
                self.assertEqual((decision.status, decision.reason), ("rejected", reason))
        self.assertEqual(ledger.usage, BudgetUsage.zero())
        self.assertEqual(ledger.reserved_action_ids, ())

    def test_enforces_budget_deadline_expiry_cancellation_and_service_grants(self) -> None:
        budget = {
            "controller_tokens": 0,
            "application_tokens": 101,
            "child_tokens": 0,
            "aggregate_tokens": 101,
            "cost_micros": 5_000,
            "deadline_ms": 10_000,
        }
        cases = (
            (
                AuthorityLedger(_envelope(budget_limit=_limit(application_tokens=100))),
                _proposal(budget=budget),
                1_000,
                (),
                "budget-exceeded",
            ),
            (
                AuthorityLedger(_envelope(max_action_deadline_ms=9_999)),
                _proposal(),
                1_000,
                (),
                "deadline-not-authorized",
            ),
            (
                AuthorityLedger(_envelope(expires_at_ms=1_000)),
                _proposal(),
                1_000,
                (),
                "authority-expired",
            ),
            (
                AuthorityLedger(_envelope(cancelled=True)),
                _proposal(),
                1_000,
                (),
                "authority-cancelled",
            ),
            (
                AuthorityLedger(_envelope()),
                _proposal(),
                1_000,
                ("network.private",),
                "host-service-not-authorized",
            ),
        )
        for ledger, proposal, now_ms, services, reason in cases:
            with self.subTest(reason=reason):
                decision = ledger.evaluate(
                    proposal,
                    now_ms=now_ms,
                    requested_host_services=services,
                )
                self.assertEqual((decision.status, decision.reason), ("rejected", reason))

    def test_enforces_child_depth_and_concurrency(self) -> None:
        child = _proposal(
            kind="child.spawn",
            target={"kind": "child", "child_id": "child-1"},
        )
        ledger = AuthorityLedger(_envelope())

        depth = ledger.evaluate(child, now_ms=1_000, recursion_depth=3)
        concurrency = ledger.evaluate(child, now_ms=1_000, active_children=2)

        self.assertEqual(depth.reason, "recursion-depth-exceeded")
        self.assertEqual(concurrency.reason, "child-concurrency-exceeded")

    def test_over_settlement_and_divergent_replay_fail_closed(self) -> None:
        ledger = AuthorityLedger(_envelope())
        decision = ledger.evaluate(_proposal(), now_ms=1_000)
        ledger.reserve(decision)
        excessive = ActionReceipt(
            action_id="action-1",
            receipt_ref="receipt-1",
            usage=BudgetUsage(
                controller_tokens=0,
                application_tokens=101,
                child_tokens=0,
                aggregate_tokens=101,
                cost_micros=5_001,
            ),
        )
        with self.assertRaises(AuthorityError):
            ledger.settle("action-1", excessive)

        receipt = replace(
            excessive,
            usage=replace(
                excessive.usage,
                application_tokens=80,
                aggregate_tokens=80,
                cost_micros=4_000,
            ),
        )
        ledger.settle("action-1", receipt)
        with self.assertRaises(AuthorityError):
            ledger.settle("action-1", replace(receipt, receipt_ref="receipt-2"))

    def test_authority_replacement_requires_monotonic_compatible_revision(self) -> None:
        ledger = AuthorityLedger(_envelope())
        decision = ledger.evaluate(_proposal(), now_ms=1_000)
        ledger.reserve(decision)

        updated = replace(_envelope(), revision=2, expires_at_ms=200_000)
        ledger.replace_authority(updated)
        self.assertEqual(ledger.envelope.revision, 2)
        for invalid in (
            replace(updated, revision=2),
            replace(updated, authority_id="authority-2", revision=3),
            replace(updated, revision=3, budget_limit=_limit(application_tokens=50)),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(AuthorityError):
                ledger.replace_authority(invalid)

    def test_envelope_copies_grants_and_rejects_noncanonical_values(self) -> None:
        operations = ["application.invoke", "child.spawn"]
        envelope = _envelope(allowed_operations=operations)
        operations.clear()
        self.assertEqual(envelope.allowed_operations, ("application.invoke", "child.spawn"))

        for invalid in (
            {"allowed_operations": ("child.spawn", "application.invoke")},
            {"host_service_grants": ("z.service", "a.service")},
            {"execution_domain": "sandboxed"},
            {"revision": 0},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(AuthorityError):
                _envelope(**invalid)


if __name__ == "__main__":
    unittest.main()
