from __future__ import annotations

import asyncio
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
from asterion.control.providers.prime.client import PrimeControlError
from asterion.control.providers.prime.ecosystem import (
    PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST,
    PRIME_ECOSYSTEM_MODULE_LOCK_DIGEST,
    PrimeEcosystemError,
    PrimeEcosystemService,
)
from asterion.control.providers.prime.process import (
    PrimeSidecarProcessError,
    _validate_response,
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
    def __init__(
        self,
        *,
        changes: Mapping[str, object] | None = None,
        timeline: list[str] | None = None,
    ) -> None:
        self.frames: list[Mapping[str, object]] = []
        self.changes = dict(changes or {})
        self.timeline = timeline
        self.quiesce_calls = 0

    async def activate_ecosystem(
        self, frame: Mapping[str, object]
    ) -> Mapping[str, object]:
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

    async def quiesce_ecosystem(self) -> None:
        self.quiesce_calls += 1
        if self.timeline is not None:
            self.timeline.append("consumer-quiesced")


class _FailingClient:
    async def activate_ecosystem(
        self, frame: Mapping[str, object]
    ) -> Mapping[str, object]:
        del frame
        raise RuntimeError(_SERVICE_ERROR)

    async def quiesce_ecosystem(self) -> None:
        return None


def _service(
    client,
    materializer=None,
    source_store=None,
    *,
    authority_id: str = "authority-1",
    authority_revision: int = 7,
):
    return PrimeEcosystemService(
        client,
        materializer if materializer is not None else _Materializer(),
        source_store if source_store is not None else _SourceStore(),
        authority_id=authority_id,
        authority_revision=authority_revision,
    )


class _ExplodingProbe:
    def __getattribute__(self, name: str):
        del name
        raise RuntimeError(_SERVICE_ERROR)


class TestPrimeEcosystemService(unittest.IsolatedAsyncioTestCase):
    async def test_activation_materializes_before_client_and_returns_body_free_receipt(
        self,
    ) -> None:
        portfolio = _portfolio()
        materializer = _Materializer()
        client = _RecordingClient()
        credential_refresh = _CredentialRefresh()

        receipt = await _service(client, materializer).activate(
            portfolio, credential_refresh
        )

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

    async def test_private_frame_is_exact_canonical_and_immutable(self) -> None:
        portfolio = _portfolio()
        client = _RecordingClient()
        service = _service(client)

        await service.activate(portfolio, _CredentialRefresh())

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

    async def test_receipt_drift_and_feature_resource_inconsistency_fail_redacted(
        self,
    ) -> None:
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
            timeline: list[str] = []
            materializer = _QuiescenceMaterializer(timeline)
            client = _RecordingClient(changes=changes, timeline=timeline)
            with self.subTest(changes=changes), self.assertRaises(
                PrimeEcosystemError
            ) as raised:
                await _service(client, materializer).activate(
                    portfolio, _CredentialRefresh()
                )
            self.assertEqual(client.quiesce_calls, 1)
            self.assertEqual(
                timeline,
                ["consumer-quiesced", "projection-closed"],
            )
            self.assertEqual(materializer.calls[-1][0], "close")
            self.assertNotIn(_BODY, str(raised.exception))
            self.assertNotIn(_SERVICE_ERROR, str(raised.exception))
            self.assertNotIn(_PATH, str(raised.exception))

    async def test_all_terminal_paths_close_and_cleanup_uncertainty_is_terminal(
        self,
    ) -> None:
        portfolio = _portfolio()
        for status in ("succeeded", "failed", "cancelled", "uncertain"):
            materializer = _Materializer()
            receipt = await _service(
                _RecordingClient(changes={"status": status}),
                materializer,
            ).activate(portfolio, _CredentialRefresh())
            with self.subTest(status=status):
                self.assertEqual(receipt.status, status)
                self.assertEqual(materializer.calls[-1][0], "close")

        receipt = await _service(
            _RecordingClient(), _Materializer(close_error=True)
        ).activate(portfolio, _CredentialRefresh())
        self.assertEqual(receipt.status, "uncertain")
        self.assertNotIn(_SERVICE_ERROR, repr(receipt))

    async def test_post_materialization_client_exception_is_redacted_uncertainty(
        self,
    ) -> None:
        materializer = _Materializer()
        receipt = await _service(_FailingClient(), materializer).activate(
            _portfolio(), _CredentialRefresh()
        )

        self.assertEqual(receipt.status, "uncertain")
        self.assertEqual(materializer.calls[-1][0], "close")
        self.assertNotIn(_SERVICE_ERROR, repr(receipt))

    async def test_wrong_protocol_objects_fail_before_materialization(self) -> None:
        valid = (_RecordingClient(), _Materializer(), _SourceStore())
        invalid = (
            (object(), valid[1], valid[2]),
            (valid[0], object(), valid[2]),
            (valid[0], valid[1], object()),
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(PrimeEcosystemError):
                _service(*values)  # type: ignore[arg-type]

        materializer = _Materializer()
        service = _service(_RecordingClient(), materializer)
        with self.assertRaises(PrimeEcosystemError):
            await service.activate(_portfolio(), object())  # type: ignore[arg-type]
        self.assertEqual(materializer.calls, [])

    async def test_registration_without_exact_extension_resource_rejects_before_materialization(
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
            await _service(
                _RecordingClient(),
                materializer,
                authority_revision=1,
            ).activate(portfolio, _CredentialRefresh())

        self.assertEqual(materializer.calls, [])

    async def test_extension_portfolio_exposes_only_extension_feature_package(
        self,
    ) -> None:
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

        receipt = await _service(
            _RecordingClient(), authority_revision=1
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

    async def test_materializer_exception_text_is_redacted(self) -> None:
        with self.assertRaises(PrimeEcosystemError) as raised:
            await _service(
                _RecordingClient(),
                _Materializer(materialize_error=True),
            ).activate(_portfolio(), _CredentialRefresh())

        self.assertNotIn(_SERVICE_ERROR, str(raised.exception))

    async def test_authority_drift_rejects_before_materialization_or_client(self) -> None:
        client = _RecordingClient()
        materializer = _Materializer()
        service = _service(
            client,
            materializer,
            authority_id="other-authority",
            authority_revision=7,
        )

        with self.assertRaises(PrimeEcosystemError):
            await service.activate(_portfolio(), _CredentialRefresh())

        self.assertEqual(materializer.calls, [])
        self.assertEqual(client.frames, [])

        transport = _AsyncTransport()
        concrete_client = PrimeControlPlaneClient(
            process=transport,
            private_content=_PrivateContent(),
        )
        concrete_materializer = _Materializer()
        with self.assertRaises(PrimeEcosystemError):
            await _service(
                concrete_client,
                concrete_materializer,
                authority_id="other-authority",
                authority_revision=7,
            ).activate(_portfolio(), _CredentialRefresh())
        self.assertEqual(concrete_materializer.calls, [])
        self.assertEqual(transport.envelopes, [])

    async def test_exception_throwing_protocol_probes_are_redacted(self) -> None:
        for values in (
            (_ExplodingProbe(), _Materializer(), _SourceStore()),
            (_RecordingClient(), _ExplodingProbe(), _SourceStore()),
            (_RecordingClient(), _Materializer(), _ExplodingProbe()),
        ):
            with self.subTest(values=values), self.assertRaises(
                PrimeEcosystemError
            ) as raised:
                _service(*values)
            self.assertNotIn(_SERVICE_ERROR, str(raised.exception))

        service = _service(_RecordingClient())
        with self.assertRaises(PrimeEcosystemError) as raised:
            await service.activate(_portfolio(), _ExplodingProbe())  # type: ignore[arg-type]
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


class _AwaitingTransport(_AsyncTransport):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        self.envelopes.append(envelope)
        self.started.set()
        await self.release.wait()
        frame = envelope["frame"]
        resources = tuple(frame["resources"])  # type: ignore[index,arg-type]
        registrations = tuple(frame["registrations"])  # type: ignore[index,arg-type]
        return {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": envelope["id"],
            "type": "ecosystem_receipt",
            "receipt": {
                "authorityDigest": frame["authorityDigest"],  # type: ignore[index]
                "featureIds": frame["features"],  # type: ignore[index]
                "lifecycleCount": sum(
                    item["kind"] == "extension" for item in resources
                ),
                "mcpCount": sum(item["kind"] == "mcp-server" for item in resources),
                "modelCredentialReads": 0,
                "ownedProcessCount": 0,
                "packageCount": sum(item["kind"] == "package" for item in resources),
                "portfolioDigest": frame["portfolioDigest"],  # type: ignore[index]
                "providerOperations": 0,
                "registrationCount": len(registrations),
                "resourceCount": len(resources),
                "status": "succeeded",
            },
        }


class _FailingLiveTransport(_AsyncTransport):
    def __init__(self, mode: str, timeline: list[str]) -> None:
        super().__init__()
        self.mode = mode
        self.timeline = timeline
        self.close_started = asyncio.Event()
        self.allow_close = asyncio.Event()

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        self.envelopes.append(envelope)
        self.timeline.append("consumer-failed")
        if self.mode == "timeout":
            raise TimeoutError(_SERVICE_ERROR)
        return {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": envelope["id"],
            "type": "ecosystem_receipt",
            "receipt": [],
        }

    async def close(self) -> None:
        self.timeline.append("consumer-close-started")
        self.close_started.set()
        await self.allow_close.wait()
        self.timeline.append("consumer-quiesced")


class _SemanticDriftLiveTransport(_FailingLiveTransport):
    def __init__(
        self,
        changes: Mapping[str, object],
        timeline: list[str],
        *,
        close_error: bool = False,
    ) -> None:
        super().__init__("semantic-drift", timeline)
        self.changes = dict(changes)
        self.close_error = close_error

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        self.envelopes.append(envelope)
        self.timeline.append("semantic-drift-received")
        frame = envelope["frame"]
        resources = tuple(frame["resources"])  # type: ignore[index,arg-type]
        registrations = tuple(frame["registrations"])  # type: ignore[index,arg-type]
        receipt = {
            "authorityDigest": frame["authorityDigest"],  # type: ignore[index]
            "featureIds": frame["features"],  # type: ignore[index]
            "lifecycleCount": sum(
                item["kind"] == "extension" for item in resources
            ),
            "mcpCount": sum(item["kind"] == "mcp-server" for item in resources),
            "modelCredentialReads": 0,
            "ownedProcessCount": 0,
            "packageCount": sum(item["kind"] == "package" for item in resources),
            "portfolioDigest": frame["portfolioDigest"],  # type: ignore[index]
            "providerOperations": 0,
            "registrationCount": len(registrations),
            "resourceCount": len(resources),
            "status": "succeeded",
        }
        receipt.update(self.changes)
        return {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": envelope["id"],
            "type": "ecosystem_receipt",
            "receipt": receipt,
        }

    async def close(self) -> None:
        self.timeline.append("consumer-close-started")
        self.close_started.set()
        if self.close_error:
            raise RuntimeError(_SERVICE_ERROR)
        await self.allow_close.wait()
        self.timeline.append("consumer-quiesced")


class _QuiescenceMaterializer(_Materializer):
    def __init__(self, timeline: list[str]) -> None:
        super().__init__()
        self.timeline = timeline

    def close(self, projection):
        self.timeline.append("projection-closed")
        super().close(projection)


class _UnquiesceableTransport(_AsyncTransport):
    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        self.envelopes.append(envelope)
        raise TimeoutError(_SERVICE_ERROR)

    async def close(self) -> None:
        raise RuntimeError(_SERVICE_ERROR)


class _AwaitingUnquiesceableTransport(_UnquiesceableTransport):
    def __init__(self) -> None:
        super().__init__()
        self.request_started = asyncio.Event()
        self.allow_failure = asyncio.Event()

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        self.envelopes.append(envelope)
        self.request_started.set()
        await self.allow_failure.wait()
        raise TimeoutError(_SERVICE_ERROR)


class _ExplodingMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        del key
        raise RuntimeError(_SERVICE_ERROR)

    def __iter__(self):
        raise RuntimeError(_SERVICE_ERROR)

    def __len__(self) -> int:
        raise RuntimeError(_SERVICE_ERROR)


class TestPrimeEcosystemClient(unittest.IsolatedAsyncioTestCase):
    def test_process_accepts_only_exact_ecosystem_receipt_response(self) -> None:
        request = {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": "ecosystem-request-1",
            "type": "ecosystem_activate",
            "frame": {},
        }
        response = {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": "ecosystem-request-1",
            "type": "ecosystem_receipt",
            "receipt": {},
        }

        self.assertEqual(_validate_response(response, request), response)
        invalid = (
            {**response, "extra": "SENTINEL_SECRET"},
            {key: value for key, value in response.items() if key != "receipt"},
            {**response, "receipt": []},
            {**response, "type": "session-context.receipt"},
        )
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(
                PrimeSidecarProcessError
            ):
                _validate_response(candidate, request)

    async def test_client_constructor_probe_exception_is_fixed_and_redacted(self) -> None:
        with self.assertRaises(PrimeControlError) as raised:
            PrimeControlPlaneClient(
                process=_AsyncTransport(), private_content=_ExplodingProbe()
            )

        self.assertNotIn(_SERVICE_ERROR, str(raised.exception))

    async def test_selected_client_adds_only_private_ecosystem_activate_request(self) -> None:
        transport = _AsyncTransport()
        client = PrimeControlPlaneClient(process=transport, private_content=_PrivateContent())
        frame = {"format": "asterion.prime-ecosystem-frame/v1", "body": _BODY}

        receipt = await client.activate_ecosystem(frame)

        self.assertEqual(receipt, {"status": "succeeded"})
        self.assertEqual(transport.envelopes[0]["type"], "ecosystem_activate")
        self.assertEqual(transport.envelopes[0]["frame"], frame)
        self.assertNotIn("ecosystem", client.manifest.to_mapping())

    async def test_concrete_client_service_awaits_ipc_before_projection_cleanup(
        self,
    ) -> None:
        transport = _AwaitingTransport()
        client = PrimeControlPlaneClient(
            process=transport, private_content=_PrivateContent()
        )
        materializer = _Materializer()
        service = _service(client, materializer)

        activation = asyncio.create_task(
            service.activate(_portfolio(), _CredentialRefresh())
        )
        await transport.started.wait()
        self.assertEqual(
            tuple(item[0] for item in materializer.calls), ("materialize",)
        )

        transport.release.set()
        receipt = await activation

        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(
            tuple(item[0] for item in materializer.calls),
            ("materialize", "close"),
        )

    async def test_transport_failure_quiesces_consumer_before_projection_cleanup(
        self,
    ) -> None:
        for mode in ("timeout", "invalid-response"):
            timeline: list[str] = []
            transport = _FailingLiveTransport(mode, timeline)
            client = PrimeControlPlaneClient(
                process=transport,
                private_content=_PrivateContent(),
            )
            materializer = _QuiescenceMaterializer(timeline)
            activation = asyncio.create_task(
                _service(client, materializer).activate(
                    _portfolio(), _CredentialRefresh()
                )
            )
            close_started = asyncio.create_task(transport.close_started.wait())

            done, _ = await asyncio.wait(
                {activation, close_started},
                return_when=asyncio.FIRST_COMPLETED,
            )
            close_started_first = close_started in done
            activation_waited_for_close = activation not in done
            pre_quiescence_calls = tuple(
                item[0] for item in materializer.calls
            )
            transport.allow_close.set()
            receipt = await activation
            if not close_started.done():
                close_started.cancel()
            await asyncio.gather(close_started, return_exceptions=True)

            with self.subTest(mode=mode):
                self.assertTrue(close_started_first)
                self.assertTrue(activation_waited_for_close)
                self.assertEqual(
                    pre_quiescence_calls,
                    ("materialize",),
                )
                self.assertEqual(receipt.status, "uncertain")
                self.assertEqual(
                    timeline,
                    [
                        "consumer-failed",
                        "consumer-close-started",
                        "consumer-quiesced",
                        "projection-closed",
                    ],
                )

    async def test_semantic_receipt_drift_quiesces_before_projection_cleanup(
        self,
    ) -> None:
        cases = (
            {"ownedProcessCount": 1},
            {"authorityDigest": "f" * 64},
            {"resourceCount": 6},
            {"status": "running"},
        )
        for changes in cases:
            timeline: list[str] = []
            transport = _SemanticDriftLiveTransport(changes, timeline)
            client = PrimeControlPlaneClient(
                process=transport,
                private_content=_PrivateContent(),
            )
            materializer = _QuiescenceMaterializer(timeline)
            activation = asyncio.create_task(
                _service(client, materializer).activate(
                    _portfolio(), _CredentialRefresh()
                )
            )
            close_started = asyncio.create_task(transport.close_started.wait())
            done, _ = await asyncio.wait(
                {activation, close_started},
                return_when=asyncio.FIRST_COMPLETED,
            )

            with self.subTest(changes=changes):
                self.assertIn(close_started, done)
                self.assertNotIn(activation, done)
                self.assertEqual(
                    tuple(item[0] for item in materializer.calls),
                    ("materialize",),
                )

            transport.allow_close.set()
            with self.assertRaises(PrimeEcosystemError) as raised:
                await activation
            if not close_started.done():
                close_started.cancel()
            await asyncio.gather(close_started, return_exceptions=True)

            with self.subTest(changes=changes):
                self.assertNotIn(_SERVICE_ERROR, str(raised.exception))
                self.assertEqual(
                    timeline,
                    [
                        "semantic-drift-received",
                        "consumer-close-started",
                        "consumer-quiesced",
                        "projection-closed",
                    ],
                )

    async def test_unquiesceable_semantic_drift_retains_projection(self) -> None:
        timeline: list[str] = []
        transport = _SemanticDriftLiveTransport(
            {"ownedProcessCount": 1},
            timeline,
            close_error=True,
        )
        client = PrimeControlPlaneClient(
            process=transport,
            private_content=_PrivateContent(),
        )
        materializer = _QuiescenceMaterializer(timeline)

        with self.assertRaises(PrimeEcosystemError) as raised:
            await _service(client, materializer).activate(
                _portfolio(), _CredentialRefresh()
            )

        self.assertEqual(
            tuple(item[0] for item in materializer.calls),
            ("materialize",),
        )
        self.assertEqual(
            timeline,
            ["semantic-drift-received", "consumer-close-started"],
        )
        self.assertNotIn(_SERVICE_ERROR, str(raised.exception))

    async def test_unquiesced_consumer_never_releases_projection(self) -> None:
        transport = _UnquiesceableTransport()
        client = PrimeControlPlaneClient(
            process=transport,
            private_content=_PrivateContent(),
        )
        materializer = _Materializer()

        with self.assertRaises(PrimeEcosystemError) as raised:
            await _service(client, materializer).activate(
                _portfolio(), _CredentialRefresh()
            )

        self.assertEqual(
            tuple(item[0] for item in materializer.calls),
            ("materialize",),
        )
        self.assertNotIn(_SERVICE_ERROR, str(raised.exception))

    async def test_cancellation_waits_for_failure_quiescence_before_cleanup(
        self,
    ) -> None:
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        loop_contexts: list[Mapping[str, object]] = []
        loop.set_exception_handler(
            lambda unused_loop, context: loop_contexts.append(context)
        )
        timeline: list[str] = []
        transport = _FailingLiveTransport("timeout", timeline)
        client = PrimeControlPlaneClient(
            process=transport,
            private_content=_PrivateContent(),
        )
        materializer = _QuiescenceMaterializer(timeline)
        activation = asyncio.create_task(
            _service(client, materializer).activate(
                _portfolio(), _CredentialRefresh()
            )
        )
        await transport.close_started.wait()

        activation.cancel()
        done, _ = await asyncio.wait({activation}, timeout=0)
        self.assertEqual(done, set())
        self.assertEqual(
            tuple(item[0] for item in materializer.calls),
            ("materialize",),
        )

        transport.allow_close.set()
        with self.assertRaises(asyncio.CancelledError):
            await activation

        loop.set_exception_handler(previous_handler)

        self.assertEqual(
            timeline,
            [
                "consumer-failed",
                "consumer-close-started",
                "consumer-quiesced",
                "projection-closed",
            ],
        )
        self.assertEqual(loop_contexts, [])

    async def test_cancelled_unquiesced_consumer_never_releases_projection(
        self,
    ) -> None:
        transport = _AwaitingUnquiesceableTransport()
        client = PrimeControlPlaneClient(
            process=transport,
            private_content=_PrivateContent(),
        )
        materializer = _Materializer()
        activation = asyncio.create_task(
            _service(client, materializer).activate(
                _portfolio(), _CredentialRefresh()
            )
        )

        await transport.request_started.wait()
        activation.cancel()
        transport.allow_failure.set()
        with self.assertRaises(asyncio.CancelledError):
            await activation

        self.assertEqual(
            tuple(item[0] for item in materializer.calls),
            ("materialize",),
        )

    async def test_frame_conversion_exception_is_fixed_and_redacted(self) -> None:
        transport = _AsyncTransport()
        client = PrimeControlPlaneClient(
            process=transport, private_content=_PrivateContent()
        )

        with self.assertRaises(PrimeControlError) as raised:
            await client.activate_ecosystem(_ExplodingMapping())

        self.assertEqual(transport.envelopes, [])
        self.assertNotIn(_SERVICE_ERROR, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
