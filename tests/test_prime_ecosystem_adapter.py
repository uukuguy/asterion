from __future__ import annotations

import hashlib
import json
import unittest
from collections.abc import Mapping
from pathlib import Path

from asterion.control.ecosystem import (
    EcosystemRegistrationRef,
    EcosystemResourceRef,
    EcosystemSourceRef,
    build_ecosystem_portfolio,
)
from asterion.control.ecosystem_materialization import EcosystemProjection
from asterion.control.providers.prime.client import PrimeControlPlaneClient
from asterion.control.providers.prime.ecosystem import (
    PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST,
    PRIME_ECOSYSTEM_MODULE_LOCK_DIGEST,
    PrimeEcosystemError,
    PrimeEcosystemService,
)


_BODY = "SENTINEL_BODY"
_PATH = "/private/SENTINEL_PATH"
_SERVICE_ERROR = "SENTINEL_SERVICE_EXCEPTION"


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _portfolio():
    kinds = (
        "context-file",
        "extension",
        "markdown-skill",
        "mcp-server",
        "package",
        "prompt-template",
        "python-skill",
    )
    resources = tuple(
        EcosystemResourceRef(
            f"resource-{kind}",
            "1.0.0",
            kind,  # type: ignore[arg-type]
            "project",
            EcosystemSourceRef(
                f"source-{kind}", "local-child", "1.0.0", _sha256([kind])
            ),
            _sha256({"kind": kind}),
        )
        for kind in kinds
    )
    registrations = tuple(
        EcosystemRegistrationRef(
            f"registration-{kind}", kind, "resource-extension", "1.0.0"  # type: ignore[arg-type]
        )
        for kind in ("command", "provider-model", "tool")
    )
    return build_ecosystem_portfolio(
        portfolio_id="portfolio-1",
        authority_id="authority-1",
        authority_revision=7,
        resources=resources,
        registrations=registrations,
    )


class _SourceStore:
    def private_resource(self, resource_id: str):
        raise AssertionError(resource_id)

    def open_file(self, resource_id: str, relative_path: str):
        raise AssertionError((resource_id, relative_path))


class _Materializer:
    def __init__(
        self, *, close_error: bool = False, materialize_error: bool = False
    ) -> None:
        self.calls: list[object] = []
        self.close_error = close_error
        self.materialize_error = materialize_error

    def materialize(self, portfolio, store):
        self.calls.append(("materialize", portfolio.digest, store))
        if self.materialize_error:
            raise RuntimeError(_SERVICE_ERROR)
        root = Path(_PATH)
        return EcosystemProjection(
            projection_id=portfolio.digest,
            portfolio_digest=portfolio.digest,
            root=root,
            resource_roots={
                resource.resource_id: root / resource.resource_id
                for resource in portfolio.resources
            },
        )

    def close(self, projection):
        self.calls.append(("close", projection.projection_id))
        if self.close_error:
            raise RuntimeError(_SERVICE_ERROR)


class _CredentialRefresh:
    def __init__(self) -> None:
        self.calls = 0

    def refresh(self, lease_id: str, challenge_digest: str) -> str:
        del lease_id, challenge_digest
        self.calls += 1
        return _BODY


class _RecordingClient:
    def __init__(self, *, changes: Mapping[str, object] | None = None) -> None:
        self.frames: list[Mapping[str, object]] = []
        self.changes = dict(changes or {})

    def activate_ecosystem(self, frame: Mapping[str, object]) -> Mapping[str, object]:
        self.frames.append(frame)
        resources = tuple(frame["resources"])  # type: ignore[arg-type]
        registrations = tuple(frame["registrations"])  # type: ignore[arg-type]
        response = {
            "authorityDigest": frame["authorityDigest"],
            "featureIds": frame["features"],
            "lifecycleCount": sum(item["kind"] == "extension" for item in resources),  # type: ignore[index]
            "mcpCount": sum(item["kind"] == "mcp-server" for item in resources),  # type: ignore[index]
            "modelCredentialReads": 0,
            "ownedProcessCount": 0,
            "packageCount": sum(item["kind"] == "package" for item in resources),  # type: ignore[index]
            "portfolioDigest": frame["portfolioDigest"],
            "providerOperations": 0,
            "registrationCount": len(registrations),
            "resourceCount": len(resources),
            "status": "succeeded",
        }
        response.update(self.changes)
        return response


class _FailingClient:
    def activate_ecosystem(self, frame: Mapping[str, object]) -> Mapping[str, object]:
        del frame
        raise RuntimeError(_SERVICE_ERROR)


class TestPrimeEcosystemService(unittest.TestCase):
    def test_activation_materializes_before_client_and_returns_body_free_receipt(self) -> None:
        portfolio = _portfolio()
        materializer = _Materializer()
        client = _RecordingClient()
        credential_refresh = _CredentialRefresh()

        receipt = PrimeEcosystemService(
            client, materializer, _SourceStore()
        ).activate(portfolio, credential_refresh)

        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(receipt.provider_operations, 0)
        self.assertEqual(receipt.model_credential_reads, 0)
        self.assertEqual(
            tuple(item[0] for item in materializer.calls),
            ("materialize", "close"),
        )
        self.assertEqual(len(client.frames), 1)
        self.assertNotIn(_BODY, repr(receipt))
        self.assertNotIn(_PATH, repr(receipt))
        self.assertEqual(credential_refresh.calls, 0)

    def test_private_frame_is_exact_canonical_and_immutable(self) -> None:
        portfolio = _portfolio()
        client = _RecordingClient()
        service = PrimeEcosystemService(client, _Materializer(), _SourceStore())

        service.activate(portfolio, _CredentialRefresh())

        frame = client.frames[0]
        self.assertEqual(
            set(frame),
            {
                "artifactLockDigest",
                "authorityDigest",
                "effectId",
                "features",
                "format",
                "limits",
                "mcpCredentialLeaseId",
                "moduleLockDigest",
                "portfolioDigest",
                "projectionRoot",
                "registrations",
                "resources",
            },
        )
        self.assertEqual(frame["format"], "asterion.prime-ecosystem-frame/v1")
        self.assertEqual(frame["portfolioDigest"], portfolio.digest)
        self.assertEqual(
            frame["authorityDigest"],
            _sha256({"authorityId": "authority-1", "authorityRevision": 7}),
        )
        self.assertEqual(frame["artifactLockDigest"], PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST)
        self.assertEqual(frame["moduleLockDigest"], PRIME_ECOSYSTEM_MODULE_LOCK_DIGEST)
        self.assertEqual(
            frame["features"],
            (
                "ecosystem.collision-diagnostics",
                "ecosystem.context-files",
                "ecosystem.custom-providers-models",
                "ecosystem.extension-state-commands",
                "ecosystem.extensions-lifecycle",
                "ecosystem.mcp",
                "ecosystem.packages",
                "ecosystem.prompt-templates",
                "ecosystem.skills",
                "ecosystem.tools",
            ),
        )
        self.assertEqual(
            tuple(item["resourceId"] for item in frame["resources"]),  # type: ignore[index]
            tuple(item.resource_id for item in portfolio.resources),
        )
        self.assertEqual(
            tuple(item["registrationId"] for item in frame["registrations"]),  # type: ignore[index]
            tuple(item.registration_id for item in portfolio.registrations),
        )
        self.assertRegex(frame["mcpCredentialLeaseId"], r"^[A-Za-z0-9._:-]+$")  # type: ignore[arg-type]
        self.assertEqual(
            frame["limits"],
            {
                "deadlineMs": 30_000,
                "maxBytes": 8 * 1024 * 1024,
                "maxEntries": 4096,
                "maxProcesses": 1,
            },
        )
        with self.assertRaises(TypeError):
            frame["features"] = ()  # type: ignore[index]
        with self.assertRaises(TypeError):
            frame["limits"]["maxBytes"] = 1  # type: ignore[index]

    def test_receipt_drift_and_feature_resource_inconsistency_fail_redacted(self) -> None:
        portfolio = _portfolio()
        cases = (
            {"authorityDigest": "f" * 64},
            {"portfolioDigest": "f" * 64},
            {"featureIds": ("ecosystem.mcp",)},
            {"resourceCount": 6},
            {"providerOperations": 1},
            {"providerOperations": False},
            {"modelCredentialReads": 1},
            {"extra": _BODY},
        )
        for changes in cases:
            materializer = _Materializer()
            with self.subTest(changes=changes), self.assertRaises(
                PrimeEcosystemError
            ) as raised:
                PrimeEcosystemService(
                    _RecordingClient(changes=changes), materializer, _SourceStore()
                ).activate(portfolio, _CredentialRefresh())
            self.assertEqual(materializer.calls[-1][0], "close")
            self.assertNotIn(_BODY, str(raised.exception))
            self.assertNotIn(_SERVICE_ERROR, str(raised.exception))
            self.assertNotIn(_PATH, str(raised.exception))

    def test_all_terminal_paths_close_and_cleanup_uncertainty_is_terminal(self) -> None:
        portfolio = _portfolio()
        for status in ("succeeded", "failed", "cancelled", "uncertain"):
            materializer = _Materializer()
            receipt = PrimeEcosystemService(
                _RecordingClient(changes={"status": status}),
                materializer,
                _SourceStore(),
            ).activate(portfolio, _CredentialRefresh())
            with self.subTest(status=status):
                self.assertEqual(receipt.status, status)
                self.assertEqual(materializer.calls[-1][0], "close")

        receipt = PrimeEcosystemService(
            _RecordingClient(), _Materializer(close_error=True), _SourceStore()
        ).activate(portfolio, _CredentialRefresh())
        self.assertEqual(receipt.status, "uncertain")
        self.assertNotIn(_SERVICE_ERROR, repr(receipt))

    def test_post_materialization_client_exception_is_redacted_uncertainty(self) -> None:
        materializer = _Materializer()
        receipt = PrimeEcosystemService(
            _FailingClient(), materializer, _SourceStore()
        ).activate(_portfolio(), _CredentialRefresh())

        self.assertEqual(receipt.status, "uncertain")
        self.assertEqual(materializer.calls[-1][0], "close")
        self.assertNotIn(_SERVICE_ERROR, repr(receipt))

    def test_wrong_protocol_objects_fail_before_materialization(self) -> None:
        valid = (_RecordingClient(), _Materializer(), _SourceStore())
        invalid = (
            (object(), valid[1], valid[2]),
            (valid[0], object(), valid[2]),
            (valid[0], valid[1], object()),
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(PrimeEcosystemError):
                PrimeEcosystemService(*values)  # type: ignore[arg-type]

        materializer = _Materializer()
        service = PrimeEcosystemService(_RecordingClient(), materializer, _SourceStore())
        with self.assertRaises(PrimeEcosystemError):
            service.activate(_portfolio(), object())  # type: ignore[arg-type]
        self.assertEqual(materializer.calls, [])

    def test_registration_without_exact_extension_resource_rejects_before_materialization(
        self,
    ) -> None:
        portfolio = build_ecosystem_portfolio(
            portfolio_id="portfolio-1",
            authority_id="authority-1",
            authority_revision=1,
            resources=(),
            registrations=(
                EcosystemRegistrationRef(
                    "registration-tool", "tool", "missing-extension", "1.0.0"
                ),
            ),
        )
        materializer = _Materializer()

        with self.assertRaises(PrimeEcosystemError):
            PrimeEcosystemService(
                _RecordingClient(), materializer, _SourceStore()
            ).activate(portfolio, _CredentialRefresh())

        self.assertEqual(materializer.calls, [])

    def test_extension_portfolio_exposes_only_extension_feature_package(self) -> None:
        resource = EcosystemResourceRef(
            "extension-1",
            "1.0.0",
            "extension",
            "project",
            EcosystemSourceRef(
                "source-extension", "local-child", "1.0.0", "a" * 64
            ),
            "b" * 64,
        )
        portfolio = build_ecosystem_portfolio(
            portfolio_id="portfolio-1",
            authority_id="authority-1",
            authority_revision=1,
            resources=(resource,),
            registrations=tuple(
                EcosystemRegistrationRef(
                    f"registration-{kind}", kind, "extension-1", "1.0.0"  # type: ignore[arg-type]
                )
                for kind in ("command", "provider-model", "tool")
            ),
        )

        receipt = PrimeEcosystemService(
            _RecordingClient(), _Materializer(), _SourceStore()
        ).activate(portfolio, _CredentialRefresh())

        self.assertEqual(
            receipt.feature_ids,
            (
                "ecosystem.custom-providers-models",
                "ecosystem.extension-state-commands",
                "ecosystem.extensions-lifecycle",
                "ecosystem.tools",
            ),
        )

    def test_materializer_exception_text_is_redacted(self) -> None:
        with self.assertRaises(PrimeEcosystemError) as raised:
            PrimeEcosystemService(
                _RecordingClient(),
                _Materializer(materialize_error=True),
                _SourceStore(),
            ).activate(_portfolio(), _CredentialRefresh())

        self.assertNotIn(_SERVICE_ERROR, str(raised.exception))


class _PrivateContent:
    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        del reference, max_bytes
        return "private"


class _AsyncTransport:
    def __init__(self) -> None:
        self.envelopes: list[Mapping[str, object]] = []

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        self.envelopes.append(envelope)
        return {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": envelope["id"],
            "type": "ecosystem_receipt",
            "receipt": {"status": "succeeded"},
        }

    async def close(self) -> None:
        return None

    async def events(self, envelope):
        del envelope
        if False:
            yield {}


class TestPrimeEcosystemClient(unittest.IsolatedAsyncioTestCase):
    async def test_selected_client_adds_only_private_ecosystem_activate_request(self) -> None:
        transport = _AsyncTransport()
        client = PrimeControlPlaneClient(process=transport, private_content=_PrivateContent())
        frame = {"format": "asterion.prime-ecosystem-frame/v1", "body": _BODY}

        receipt = await client.activate_ecosystem(frame)

        self.assertEqual(receipt, {"status": "succeeded"})
        self.assertEqual(transport.envelopes[0]["type"], "ecosystem_activate")
        self.assertEqual(transport.envelopes[0]["frame"], frame)
        self.assertNotIn("ecosystem", client.manifest.to_mapping())


if __name__ == "__main__":
    unittest.main()
