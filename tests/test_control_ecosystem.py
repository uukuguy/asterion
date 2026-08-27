from __future__ import annotations

import unittest

from asterion.control.ecosystem import (
    EcosystemActivationReceipt,
    EcosystemCollision,
    EcosystemError,
    EcosystemRegistrationRef,
    EcosystemResourceRef,
    EcosystemSourceRef,
    build_ecosystem_portfolio,
    detect_ecosystem_collisions,
)


SHA256 = "a" * 64


def _source(
    source_id: str = "source-1",
    *,
    kind: str = "local-child",
    version: str = "1.0.0",
    content_sha256: str = SHA256,
) -> EcosystemSourceRef:
    return EcosystemSourceRef(source_id, kind, version, content_sha256)  # type: ignore[arg-type]


def _resource(
    resource_id: str,
    *,
    source_id: str = "source-1",
    kind: str = "prompt-template",
    scope: str = "project",
    version: str = "1.0.0",
    content_sha256: str = SHA256,
) -> EcosystemResourceRef:
    return EcosystemResourceRef(
        resource_id,
        version,
        kind,  # type: ignore[arg-type]
        scope,  # type: ignore[arg-type]
        _source(source_id),
        content_sha256,
    )


def _registration(
    registration_id: str,
    *,
    kind: str = "tool",
    extension_id: str = "extension-1",
    version: str = "1.0.0",
) -> EcosystemRegistrationRef:
    return EcosystemRegistrationRef(
        registration_id,
        kind,  # type: ignore[arg-type]
        extension_id,
        version,
    )


class TestEcosystemReferences(unittest.TestCase):
    def test_closed_resource_source_and_scope_values_are_accepted(self) -> None:
        resource_kinds = (
            "context-file",
            "prompt-template",
            "markdown-skill",
            "python-skill",
            "extension",
            "package",
            "mcp-server",
        )
        for resource_kind in resource_kinds:
            with self.subTest(resource_kind=resource_kind):
                resource = _resource(resource_kind, kind=resource_kind)
                self.assertEqual(resource.kind, resource_kind)

        for scope in ("session", "project", "global"):
            with self.subTest(scope=scope):
                self.assertEqual(_resource("resource-1", scope=scope).scope, scope)

        self.assertEqual(_source(kind="installed-distribution").kind, "installed-distribution")
        for registration_kind in ("command", "tool", "provider-model"):
            with self.subTest(registration_kind=registration_kind):
                self.assertEqual(
                    _registration("registration-1", kind=registration_kind).kind,
                    registration_kind,
                )

    def test_references_reject_invalid_closed_values_and_private_bodies(self) -> None:
        invalid = (
            lambda: _source(source_id="../SENTINEL_BODY"),
            lambda: _source(kind="remote-registry"),
            lambda: _source(version="01.0.0"),
            lambda: _source(content_sha256="A" * 64),
            lambda: _resource("resource-1", kind="script"),
            lambda: _resource("resource-1", scope="user"),
            lambda: _resource("resource-1", version="1.0"),
            lambda: _resource("resource-1", content_sha256="short"),
            lambda: _registration("registration-1", kind="provider"),
            lambda: _registration("registration-1", extension_id="/SENTINEL_BODY"),
            lambda: _registration("registration-1", version="1.0.0-beta"),
        )
        for construct in invalid:
            with self.subTest(construct=construct), self.assertRaises(EcosystemError) as raised:
                construct()
            self.assertNotIn("SENTINEL_BODY", str(raised.exception))

    def test_reference_values_are_frozen_and_body_free(self) -> None:
        resource = _resource("resource-1")
        self.assertNotIn("SENTINEL_BODY", repr(resource))
        self.assertNotIn("SENTINEL_BODY", repr(resource.source))
        with self.assertRaises((AttributeError, TypeError)):
            resource.source.source_id = "changed"  # type: ignore[misc]
        with self.assertRaises((AttributeError, TypeError)):
            resource.source = _source("source-2")  # type: ignore[misc]


class TestEcosystemPortfolio(unittest.TestCase):
    def test_portfolio_is_sorted_immutable_and_body_free(self) -> None:
        portfolio = build_ecosystem_portfolio(
            portfolio_id="portfolio-1",
            authority_id="authority-1",
            authority_revision=1,
            resources=(_resource("prompt-1", kind="prompt-template"),),
            registrations=(_registration("tool-1", kind="tool"),),
        )
        self.assertEqual(portfolio.resources[0].resource_id, "prompt-1")
        self.assertRegex(portfolio.digest, r"^[0-9a-f]{64}$")
        self.assertNotIn("SENTINEL_BODY", repr(portfolio))
        with self.assertRaises((AttributeError, TypeError)):
            portfolio.resources += (_resource("prompt-2"),)  # type: ignore[misc]

    def test_portfolio_sorting_copies_inputs_and_has_a_canonical_digest(self) -> None:
        resources = [
            _resource("resource-b", source_id="source-b"),
            _resource("resource-a", source_id="source-a"),
        ]
        registrations = [
            _registration("tool-b", extension_id="extension-b"),
            _registration("tool-a", extension_id="extension-a"),
        ]
        portfolio = build_ecosystem_portfolio(
            portfolio_id="portfolio-1",
            authority_id="authority-1",
            authority_revision=1,
            resources=resources,
            registrations=registrations,
        )
        resources.clear()
        registrations.clear()
        reversed_portfolio = build_ecosystem_portfolio(
            portfolio_id="portfolio-1",
            authority_id="authority-1",
            authority_revision=1,
            resources=tuple(reversed(portfolio.resources)),
            registrations=tuple(reversed(portfolio.registrations)),
        )
        self.assertEqual(
            tuple(resource.resource_id for resource in portfolio.resources),
            ("resource-a", "resource-b"),
        )
        self.assertEqual(
            tuple(registration.registration_id for registration in portfolio.registrations),
            ("tool-a", "tool-b"),
        )
        self.assertEqual(portfolio.digest, reversed_portfolio.digest)

    def test_collision_is_order_independent_and_rejects_before_activation(self) -> None:
        resources = (
            _resource("prompt-1", source_id="source-b"),
            _resource("prompt-1", source_id="source-a"),
        )
        forward = detect_ecosystem_collisions(resources, ())
        reverse = detect_ecosystem_collisions(tuple(reversed(resources)), ())
        self.assertEqual(forward, reverse)
        self.assertEqual(forward[0].source_ids, ("source-a", "source-b"))
        with self.assertRaisesRegex(EcosystemError, "portfolio has a collision"):
            build_ecosystem_portfolio(
                portfolio_id="portfolio-1",
                authority_id="authority-1",
                authority_revision=1,
                resources=resources,
                registrations=(),
            )

    def test_duplicate_sources_and_registration_owners_are_collisions(self) -> None:
        duplicate_source = (
            _resource("prompt-1", source_id="source-1"),
            _resource("prompt-1", source_id="source-1"),
        )
        registration_collision = (
            _registration("tool-1", extension_id="extension-b"),
            _registration("tool-1", extension_id="extension-a"),
        )
        collisions = detect_ecosystem_collisions(duplicate_source, registration_collision)
        self.assertEqual(
            collisions,
            (
                EcosystemCollision(
                    "prompt-template",
                    "project:prompt-1",
                    ("source-1",),
                    "ecosystem-resource-collision",
                ),
                EcosystemCollision(
                    "tool",
                    "tool-1",
                    ("extension-a", "extension-b"),
                    "ecosystem-resource-collision",
                ),
            ),
        )

    def test_portfolio_rejects_invalid_identity_and_boolean_revision(self) -> None:
        invalid = (
            {"portfolio_id": "/SENTINEL_BODY"},
            {"authority_id": "../SENTINEL_BODY"},
            {"authority_revision": 0},
            {"authority_revision": True},
        )
        for changes in invalid:
            values: dict[str, object] = {
                "portfolio_id": "portfolio-1",
                "authority_id": "authority-1",
                "authority_revision": 1,
                "resources": (),
                "registrations": (),
            }
            values.update(changes)
            with self.subTest(changes=changes), self.assertRaises(EcosystemError) as raised:
                build_ecosystem_portfolio(**values)  # type: ignore[arg-type]
            self.assertNotIn("SENTINEL_BODY", str(raised.exception))


class TestEcosystemActivationReceipt(unittest.TestCase):
    def test_named_terminal_constructors_validate_counts_and_feature_order(self) -> None:
        values = {
            "portfolio_digest": SHA256,
            "feature_ids": ("feature-a", "feature-b"),
            "resource_count": 2,
            "registration_count": 1,
            "package_count": 0,
            "mcp_count": 0,
            "lifecycle_count": 1,
            "provider_operations": 0,
            "model_credential_reads": 0,
            "owned_process_count": 0,
        }
        for constructor, status in (
            (EcosystemActivationReceipt.succeeded, "succeeded"),
            (EcosystemActivationReceipt.failed, "failed"),
            (EcosystemActivationReceipt.cancelled, "cancelled"),
            (EcosystemActivationReceipt.uncertain, "uncertain"),
        ):
            with self.subTest(status=status):
                receipt = constructor(**values)
                self.assertEqual(receipt.status, status)
                self.assertEqual(receipt.feature_ids, ("feature-a", "feature-b"))
                self.assertNotIn("SENTINEL_BODY", repr(receipt))

        invalid = (
            {"portfolio_digest": "SENTINEL_BODY"},
            {"feature_ids": ("feature-b", "feature-a")},
            {"feature_ids": ("feature-a", "feature-a")},
            {"resource_count": True},
            {"registration_count": -1},
            {"provider_operations": True},
            {"owned_process_count": -1},
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(EcosystemError) as raised:
                EcosystemActivationReceipt.succeeded(**(values | changes))
            self.assertNotIn("SENTINEL_BODY", str(raised.exception))

    def test_receipt_is_frozen_and_rejects_direct_status_mismatch(self) -> None:
        receipt = EcosystemActivationReceipt.succeeded(
            portfolio_digest=SHA256,
            feature_ids=(),
            resource_count=0,
            registration_count=0,
            package_count=0,
            mcp_count=0,
            lifecycle_count=0,
            provider_operations=0,
            model_credential_reads=0,
            owned_process_count=0,
        )
        with self.assertRaises((AttributeError, TypeError)):
            receipt.feature_ids += ("feature-a",)  # type: ignore[misc]
        with self.assertRaises(EcosystemError):
            EcosystemActivationReceipt(
                SHA256,
                (),
                "running",  # type: ignore[arg-type]
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            )


if __name__ == "__main__":
    unittest.main()
