"""Offline tests for the explicit Prime release staging boundary."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable
import unittest
from unittest import mock

from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
    ReleaseArtifact,
    ReleaseSpecification,
)
from asterion.applications.prime_agent.operator import release_recipe
from tools import materialize_prime_ipython_inputs as materializer
from tests.prime_release_test_support import complete_amd64_candidate_fixture


class _Response:
    url: str
    content_length: int
    body: Iterable[bytes]

    def __init__(self, url: str, body: bytes, *, final_url: str | None = None) -> None:
        self.url = final_url or url
        self.content_length = len(body)
        self.body = (body,)


class _Transport:
    def __init__(self, responses: dict[str, _Response]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def fetch(self, url: str) -> _Response:
        self.calls.append(url)
        return self.responses[url]


def _spec(*, url: str = "https://release.example.invalid/node.tar", path: str = "node/node.tar", body: bytes = b"node") -> ReleaseSpecification:
    return ReleaseSpecification(
        release_recipe.PRIME_IPYTHON_RELEASE_RECIPE,
        ImagePlatformDescriptor("linux", "arm64", None),
        (ReleaseArtifact("node-archive", url, path, len(body), sha256(body).hexdigest()),),
    )


def _complete_spec() -> tuple[ReleaseSpecification, dict[str, _Response]]:
    fixture = complete_amd64_candidate_fixture()
    artifacts = tuple(
        ReleaseArtifact(
            capture.artifact_kind,
            capture.object.url,
            capture.artifact_path,
            capture.object.size,
            capture.object.sha256,
        )
        for capture in fixture.request.claims
    )
    return (
        ReleaseSpecification(
            release_recipe.PRIME_IPYTHON_RELEASE_RECIPE,
            ImagePlatformDescriptor("linux", "amd64", None),
            artifacts,
            fixture.request,
        ),
        {
            url: _Response(url, body)
            for url, body in fixture.bodies_by_url.items()
        },
    )


class TestPrimeImageReleaseMaterializer(unittest.TestCase):
    def test_release_rejects_artifacts_that_differ_from_complete_candidate_before_fetching(
        self,
    ) -> None:
        spec, responses = _complete_spec()
        first, *remaining = spec.artifacts
        substituted = replace(first, kind="node-archive")
        mismatched = replace(
            spec,
            artifacts=tuple(sorted((substituted, *remaining), key=lambda item: item.path)),
        )
        transport = _Transport(responses)

        with TemporaryDirectory() as directory:
            with self.assertRaises(materializer.PrimeImageMaterializerError):
                materializer.materialize_authorized_release(
                    Path(directory) / "fresh",
                    mismatched.platform,
                    mismatched,
                    transport,
                    authorization=materializer._mint_release_authorization_from_operator_cli(),
                )

        self.assertEqual(transport.calls, [])

    def test_release_rejects_an_incomplete_candidate_graph_before_fetching(
        self,
    ) -> None:
        spec = _spec()
        transport = _Transport(
            {spec.artifacts[0].url: _Response(spec.artifacts[0].url, b"node")}
        )

        with TemporaryDirectory() as directory:
            with self.assertRaises(materializer.PrimeImageMaterializerError):
                materializer.materialize_authorized_release(
                    Path(directory) / "fresh",
                    spec.platform,
                    spec,
                    transport,
                    authorization=materializer._mint_release_authorization_from_operator_cli(),
                )

        self.assertEqual(transport.calls, [])

    def test_staging_fails_closed_without_descriptor_relative_directory_open(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "fresh"
            root.mkdir(mode=0o700)
            with (
                mock.patch.object(materializer.os, "O_DIRECTORY", None),
                self.assertRaises(ValueError),
            ):
                materializer._write_checked_file(
                    root, "node/node.tar", (b"node",), 4, sha256(b"node").hexdigest()
                )
            self.assertFalse((root / "node/node.tar").exists())

    def test_plan_accepts_candidate_target_without_promoted_lock(self) -> None:
        descriptor = ImagePlatformDescriptor("linux", "arm64", None)
        with TemporaryDirectory() as directory:
            plan = materializer.plan_materialization(Path(directory) / "fresh", descriptor)

        self.assertEqual(plan.platform, descriptor)
        self.assertEqual(
            plan.recipe_sha256,
            release_recipe.release_recipe_sha256(
                release_recipe.PRIME_IPYTHON_RELEASE_RECIPE
            ),
        )
        with TemporaryDirectory() as directory:
            with self.assertRaises(TypeError):
                materializer.plan_materialization(Path(directory) / "fresh")  # type: ignore[call-arg]

    def test_release_rejects_specification_target_different_from_selected_lock(self) -> None:
        selected = ImagePlatformDescriptor("linux", "arm64", None)
        mismatched, responses = _complete_spec()
        transport = _Transport(responses)
        with TemporaryDirectory() as directory:
            with self.assertRaises(materializer.PrimeImageMaterializerError):
                materializer.materialize_authorized_release(
                    Path(directory) / "fresh", selected, mismatched, transport,
                    authorization=materializer._mint_release_authorization_from_operator_cli(),
                )
        self.assertEqual(transport.calls, [])

    def test_release_rejects_non_candidate_recipe_substitute_and_wrong_source_before_fetching(self) -> None:
        spec, responses = _complete_spec()
        substituted_recipe = replace(
            release_recipe.PRIME_IPYTHON_RELEASE_RECIPE,
            recipe_revision="prime-ipython-release-recipe/v2",
        )
        wrong_source = replace(
            release_recipe.PRIME_IPYTHON_RELEASE_RECIPE,
            source=replace(
                release_recipe.PRIME_IPYTHON_SOURCE,
                commit="d" * 40,
            ),
        )
        cases = (
            (ImagePlatformDescriptor("linux", "s390x", None), spec),
            (
                spec.platform,
                ReleaseSpecification(substituted_recipe, spec.platform, spec.artifacts),
            ),
            (
                spec.platform,
                ReleaseSpecification(wrong_source, spec.platform, spec.artifacts),
            ),
        )
        for platform, candidate in cases:
            transport = _Transport(responses)
            with TemporaryDirectory() as directory:
                with self.subTest(platform=platform, candidate=candidate), self.assertRaises(
                    materializer.PrimeImageMaterializerError
                ):
                    materializer.materialize_authorized_release(
                        Path(directory) / "fresh",
                        platform,
                        candidate,
                        transport,
                        authorization=materializer._mint_release_authorization_from_operator_cli(),
                    )
            self.assertEqual(transport.calls, [])
    def test_requires_explicit_authorization_before_fetching(self) -> None:
        spec = _spec()
        transport = _Transport({spec.artifacts[0].url: _Response(spec.artifacts[0].url, b"node")})
        with TemporaryDirectory() as directory:
            with self.assertRaises(materializer.PrimeImageMaterializerError):
                materializer.materialize_authorized_release(Path(directory) / "fresh", spec.platform, spec, transport)
        self.assertEqual(transport.calls, [])

    def test_stages_fresh_external_root_and_returns_only_untrusted_proposal(self) -> None:
        spec, responses = _complete_spec()
        transport = _Transport(responses)
        with TemporaryDirectory() as directory:
            root = Path(directory) / "fresh"
            result = materializer.materialize_authorized_release(
                root, spec.platform, spec, transport, authorization=materializer._mint_release_authorization_from_operator_cli(),
            )
            node = next(artifact for artifact in spec.artifacts if artifact.kind == "node-archive")
            self.assertEqual((root / node.path).read_bytes(), next(iter(responses[node.url].body)))
            self.assertEqual((root.stat().st_mode & 0o777), 0o700)
        self.assertEqual(result.target_id, sha256(str(root.resolve()).encode()).hexdigest())
        self.assertEqual(result.count, len(spec.artifacts))
        self.assertEqual(result.digests, tuple(artifact.sha256 for artifact in spec.artifacts))
        self.assertNotIsInstance(result, materializer.VerifiedImageInputArtifactSet)
        self.assertTrue(result.proposal.untrusted)
        self.assertEqual(
            result.proposal.recipe_revision,
            release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.recipe_revision,
        )
        self.assertEqual(
            result.proposal.recipe_sha256,
            release_recipe.release_recipe_sha256(
                release_recipe.PRIME_IPYTHON_RELEASE_RECIPE
            ),
        )
        self.assertNotIn(spec.artifacts[0].url, str(result))

    def test_rejects_redirect_and_preserves_no_proposal(self) -> None:
        spec, responses = _complete_spec()
        first = spec.artifacts[0]
        responses[first.url] = _Response(
            first.url,
            next(iter(responses[first.url].body)),
            final_url="https://other.invalid/node",
        )
        transport = _Transport(responses)
        with TemporaryDirectory() as directory:
            with self.assertRaises(materializer.PrimeImageMaterializerError):
                materializer.materialize_authorized_release(
                    Path(directory) / "fresh", spec.platform, spec, transport, authorization=materializer._mint_release_authorization_from_operator_cli(),
                )

    def test_canonicalizes_a_symlink_ancestor_for_staging_and_identity(self) -> None:
        spec, responses = _complete_spec()
        transport = _Transport(responses)
        with TemporaryDirectory() as directory:
            base = Path(directory)
            canonical_parent = base / "canonical"
            canonical_parent.mkdir()
            alias = base / "alias"
            alias.symlink_to(canonical_parent, target_is_directory=True)
            requested = alias / "fresh"
            canonical = canonical_parent / "fresh"
            result = materializer.materialize_authorized_release(
                requested, spec.platform, spec, transport, authorization=materializer._mint_release_authorization_from_operator_cli(),
            )
            node = next(artifact for artifact in spec.artifacts if artifact.kind == "node-archive")
            self.assertEqual((canonical / node.path).read_bytes(), next(iter(responses[node.url].body)))
            self.assertEqual(result.target_id, sha256(str(canonical.resolve()).encode()).hexdigest())

    def test_rejects_direct_or_replayed_authorization_before_fetching(self) -> None:
        spec, responses = _complete_spec()
        transport = _Transport(responses)
        with self.assertRaises(TypeError):
            materializer._ReleaseAuthorization(object())
        with TemporaryDirectory() as directory:
            token = materializer._mint_release_authorization_from_operator_cli()
            materializer.materialize_authorized_release(Path(directory) / "first", spec.platform, spec, transport, authorization=token)
            with self.assertRaises(materializer.PrimeImageMaterializerError):
                materializer.materialize_authorized_release(Path(directory) / "second", spec.platform, spec, transport, authorization=token)
            with self.assertRaises(materializer.PrimeImageMaterializerError):
                materializer.materialize_authorized_release(Path(directory) / "third", spec.platform, spec, transport, authorization=object())
        self.assertEqual(transport.calls, [artifact.url for artifact in spec.artifacts])

    def test_operator_cli_path_requires_exact_release_action_before_fetching(self) -> None:
        spec = _spec()
        transport = _Transport({spec.artifacts[0].url: _Response(spec.artifacts[0].url, b"node")})
        with TemporaryDirectory() as directory:
            with self.assertRaises(materializer.PrimeImageMaterializerError):
                materializer.materialize_release_from_operator_cli(
                    ("plan",), Path(directory) / "fresh", spec.platform, spec, transport,
                )
        self.assertEqual(transport.calls, [])

    def test_release_specification_rejects_non_https_traversal_and_duplicate_downloads(self) -> None:
        valid = _spec()
        cases = (
            _spec(url="http://release.example.invalid/node.tar"),
            _spec(path="../node.tar"),
            ReleaseSpecification(valid.recipe, valid.platform, (valid.artifacts[0], valid.artifacts[0])),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                materializer.validate_release_specification(value)

    def test_rejects_wrong_length_or_hash(self) -> None:
        spec, responses = _complete_spec()
        first = spec.artifacts[0]
        for body in (b"bad", next(iter(responses[first.url].body)) + b"extra"):
            changed = dict(responses)
            changed[first.url] = _Response(first.url, body)
            transport = _Transport(changed)
            with TemporaryDirectory() as directory:
                with self.subTest(body=body), self.assertRaises(materializer.PrimeImageMaterializerError):
                    materializer.materialize_authorized_release(
                        Path(directory) / "fresh", spec.platform, spec, transport, authorization=materializer._mint_release_authorization_from_operator_cli(),
                    )
