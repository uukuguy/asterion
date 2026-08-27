"""Selected-Prime translation for one sealed ecosystem portfolio."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol

from asterion.control.ecosystem import (
    EcosystemActivationReceipt,
    EcosystemPortfolio,
    EcosystemPrivateSourceStore,
)
from asterion.control.ecosystem_materialization import (
    EcosystemProjection,
    SealedEcosystemMaterializer,
)


PRIME_ECOSYSTEM_FRAME = "asterion.prime-ecosystem-frame/v1"
PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST = hashlib.sha256(
    b"asterion.prime-artifact-lock/v1"
).hexdigest()
PRIME_ECOSYSTEM_MODULE_LOCK_DIGEST = hashlib.sha256(
    b"asterion.prime-ecosystem-module-lock/v1"
).hexdigest()

_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "uncertain"})
_RECEIPT_FIELDS = frozenset(
    {
        "authorityDigest",
        "featureIds",
        "lifecycleCount",
        "mcpCount",
        "modelCredentialReads",
        "ownedProcessCount",
        "packageCount",
        "portfolioDigest",
        "providerOperations",
        "registrationCount",
        "resourceCount",
        "status",
    }
)
_LIMITS = MappingProxyType(
    {
        "deadlineMs": 30_000,
        "maxBytes": 8 * 1024 * 1024,
        "maxEntries": 4096,
        "maxProcesses": 1,
    }
)
_RESOURCE_FEATURES = {
    "context-file": (
        "ecosystem.collision-diagnostics",
        "ecosystem.context-files",
    ),
    "extension": ("ecosystem.extensions-lifecycle",),
    "markdown-skill": ("ecosystem.skills",),
    "mcp-server": ("ecosystem.mcp",),
    "package": ("ecosystem.packages",),
    "prompt-template": ("ecosystem.prompt-templates",),
    "python-skill": ("ecosystem.skills",),
}
_REGISTRATION_FEATURES = {
    "command": "ecosystem.extension-state-commands",
    "provider-model": "ecosystem.custom-providers-models",
    "tool": "ecosystem.tools",
}


class PrimeEcosystemError(RuntimeError):
    """Raised when selected-Prime ecosystem activation cannot remain exact."""

    def __init__(self, message: str = "Prime ecosystem operation failed") -> None:
        super().__init__(message)


class PrimeEcosystemClient(Protocol):
    def activate_ecosystem(
        self, frame: Mapping[str, object]
    ) -> Mapping[str, object]: ...


class McpCredentialRefresh(Protocol):
    def refresh(self, lease_id: str, challenge_digest: str) -> str: ...


class PrimeEcosystemService:
    """Materialize, translate, activate, validate, and quiescently clean up."""

    def __init__(
        self,
        client: PrimeEcosystemClient,
        materializer: SealedEcosystemMaterializer,
        source_store: EcosystemPrivateSourceStore,
    ) -> None:
        if (
            not callable(getattr(client, "activate_ecosystem", None))
            or not _is_materializer(materializer)
            or not _is_source_store(source_store)
        ):
            raise PrimeEcosystemError("Prime ecosystem service is invalid")
        self._client = client
        self._materializer = materializer
        self._source_store = source_store

    def activate(
        self,
        portfolio: EcosystemPortfolio,
        credential_refresh: McpCredentialRefresh,
    ) -> EcosystemActivationReceipt:
        if type(portfolio) is not EcosystemPortfolio or not callable(
            getattr(credential_refresh, "refresh", None)
        ):
            raise PrimeEcosystemError("Prime ecosystem activation is invalid")
        if not _portfolio_is_consistent(portfolio):
            raise PrimeEcosystemError("Prime ecosystem activation is invalid")

        projection: object | None = None
        response: object | None = None
        client_uncertain = False
        close_uncertain = False
        try:
            projection = self._materializer.materialize(portfolio, self._source_store)
            if not _projection_matches(projection, portfolio):
                raise PrimeEcosystemError("Prime ecosystem projection is invalid")
            frame = _build_frame(portfolio, projection)
            try:
                response = self._client.activate_ecosystem(frame)
            except Exception:
                client_uncertain = True
        except PrimeEcosystemError:
            raise
        except Exception:
            raise PrimeEcosystemError("Prime ecosystem operation failed") from None
        finally:
            if projection is not None:
                try:
                    self._materializer.close(projection)  # type: ignore[arg-type]
                except Exception:
                    close_uncertain = True

        expected = _expected_receipt_values(portfolio)
        if client_uncertain:
            return EcosystemActivationReceipt.uncertain(**expected)
        receipt = _validate_receipt(response, portfolio, expected)
        if close_uncertain:
            return EcosystemActivationReceipt.uncertain(**expected)
        return receipt


def _build_frame(
    portfolio: EcosystemPortfolio,
    projection: EcosystemProjection,
) -> Mapping[str, object]:
    authority_digest = _canonical_digest(
        {
            "authorityId": portfolio.authority_id,
            "authorityRevision": portfolio.authority_revision,
        }
    )
    resources = tuple(
        MappingProxyType(
            {
                "contentDigest": resource.content_sha256,
                "kind": resource.kind,
                "projectionPath": str(projection.resource_roots[resource.resource_id]),
                "resourceId": resource.resource_id,
                "scope": resource.scope,
                "source": MappingProxyType(
                    {
                        "contentDigest": resource.source.content_sha256,
                        "kind": resource.source.kind,
                        "sourceId": resource.source.source_id,
                        "version": resource.source.version,
                    }
                ),
                "version": resource.version,
            }
        )
        for resource in portfolio.resources
    )
    registrations = tuple(
        MappingProxyType(
            {
                "extensionId": registration.extension_id,
                "kind": registration.kind,
                "registrationId": registration.registration_id,
                "version": registration.version,
            }
        )
        for registration in portfolio.registrations
    )
    return MappingProxyType(
        {
            "artifactLockDigest": PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST,
            "authorityDigest": authority_digest,
            "effectId": f"ecosystem:{portfolio.portfolio_id}:{portfolio.digest[:32]}",
            "features": _feature_ids(portfolio),
            "format": PRIME_ECOSYSTEM_FRAME,
            "limits": _LIMITS,
            "mcpCredentialLeaseId": f"mcp-lease:{secrets.token_hex(16)}",
            "moduleLockDigest": PRIME_ECOSYSTEM_MODULE_LOCK_DIGEST,
            "portfolioDigest": portfolio.digest,
            "projectionRoot": str(projection.root),
            "registrations": registrations,
            "resources": resources,
        }
    )


def _validate_receipt(
    value: object,
    portfolio: EcosystemPortfolio,
    expected: Mapping[str, object],
) -> EcosystemActivationReceipt:
    try:
        if not isinstance(value, Mapping) or set(value) != _RECEIPT_FIELDS:
            raise TypeError
        integer_fields = (
            "lifecycleCount",
            "mcpCount",
            "modelCredentialReads",
            "ownedProcessCount",
            "packageCount",
            "providerOperations",
            "registrationCount",
            "resourceCount",
        )
        if any(type(value[field]) is not int for field in integer_fields):
            raise TypeError
        feature_ids = tuple(value["featureIds"])  # type: ignore[arg-type]
        status = value["status"]
        authority_digest = _canonical_digest(
            {
                "authorityId": portfolio.authority_id,
                "authorityRevision": portfolio.authority_revision,
            }
        )
        if (
            value["portfolioDigest"] != portfolio.digest
            or value["authorityDigest"] != authority_digest
            or feature_ids != expected["feature_ids"]
            or status not in _TERMINAL_STATUSES
            or value["resourceCount"] != expected["resource_count"]
            or value["registrationCount"] != expected["registration_count"]
            or value["packageCount"] != expected["package_count"]
            or value["mcpCount"] != expected["mcp_count"]
            or value["lifecycleCount"] != expected["lifecycle_count"]
            or value["providerOperations"] != 0
            or value["modelCredentialReads"] != 0
            or value["ownedProcessCount"] != 0
        ):
            raise ValueError
        constructor = getattr(EcosystemActivationReceipt, status)
        return constructor(**expected)
    except Exception:
        raise PrimeEcosystemError("Prime ecosystem receipt is invalid") from None


def _expected_receipt_values(portfolio: EcosystemPortfolio) -> Mapping[str, object]:
    return {
        "portfolio_digest": portfolio.digest,
        "feature_ids": _feature_ids(portfolio),
        "resource_count": len(portfolio.resources),
        "registration_count": len(portfolio.registrations),
        "package_count": sum(item.kind == "package" for item in portfolio.resources),
        "mcp_count": sum(item.kind == "mcp-server" for item in portfolio.resources),
        "lifecycle_count": sum(
            item.kind == "extension" for item in portfolio.resources
        ),
        "provider_operations": 0,
        "model_credential_reads": 0,
        "owned_process_count": 0,
    }


def _feature_ids(portfolio: EcosystemPortfolio) -> tuple[str, ...]:
    values: set[str] = set()
    for resource in portfolio.resources:
        values.update(_RESOURCE_FEATURES[resource.kind])
    for registration in portfolio.registrations:
        values.add(_REGISTRATION_FEATURES[registration.kind])
    return tuple(sorted(values))


def _portfolio_is_consistent(portfolio: EcosystemPortfolio) -> bool:
    extension_ids = {
        resource.resource_id
        for resource in portfolio.resources
        if resource.kind == "extension"
    }
    return all(
        registration.extension_id in extension_ids
        for registration in portfolio.registrations
    )


def _projection_matches(value: object, portfolio: EcosystemPortfolio) -> bool:
    if type(value) is not EcosystemProjection:
        return False
    expected_ids = tuple(item.resource_id for item in portfolio.resources)
    return (
        value.projection_id == portfolio.digest
        and value.portfolio_digest == portfolio.digest
        and tuple(value.resource_roots) == expected_ids
        and all(
            value.resource_roots[resource_id] == value.root / resource_id
            for resource_id in expected_ids
        )
    )


def _canonical_digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_materializer(value: object) -> bool:
    return callable(getattr(value, "materialize", None)) and callable(
        getattr(value, "close", None)
    )


def _is_source_store(value: object) -> bool:
    return callable(getattr(value, "private_resource", None)) and callable(
        getattr(value, "open_file", None)
    )
