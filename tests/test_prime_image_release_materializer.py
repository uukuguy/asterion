"""Offline tests for the explicit Prime release staging boundary."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable
import unittest

from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
    ReleaseArtifact,
    ReleaseSpecification,
)
from tools import materialize_prime_ipython_inputs as materializer


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
        source_commit="a" * 40,
        source_tree_sha256="b" * 64,
        source_package_lock_sha256="c" * 64,
        platform=ImagePlatformDescriptor("linux", "amd64", None),
        artifacts=(ReleaseArtifact("node-archive", url, path, len(body), sha256(body).hexdigest()),),
    )


class TestPrimeImageReleaseMaterializer(unittest.TestCase):
    def test_plan_requires_exact_requested_target_and_retains_it(self) -> None:
        descriptor = ImagePlatformDescriptor("linux", "amd64", None)
        with TemporaryDirectory() as directory:
            plan = materializer.plan_materialization(Path(directory) / "fresh", descriptor)

        self.assertEqual(plan.platform, descriptor)
        with TemporaryDirectory() as directory:
            with self.assertRaises(TypeError):
                materializer.plan_materialization(Path(directory) / "fresh")  # type: ignore[call-arg]

    def test_release_rejects_specification_target_different_from_selected_lock(self) -> None:
        selected = ImagePlatformDescriptor("linux", "amd64", None)
        mismatched = ReleaseSpecification(
            "a" * 40, "b" * 64, "c" * 64,
            ImagePlatformDescriptor("linux", "arm64", None),
            (ReleaseArtifact("node-archive", "https://release.example.invalid/node.tar", "node/node.tar", 4, sha256(b"node").hexdigest()),),
        )
        transport = _Transport({mismatched.artifacts[0].url: _Response(mismatched.artifacts[0].url, b"node")})
        with TemporaryDirectory() as directory:
            with self.assertRaises(materializer.PrimeImageMaterializerError):
                materializer.materialize_authorized_release(
                    Path(directory) / "fresh", selected, mismatched, transport,
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
        spec = _spec()
        transport = _Transport({spec.artifacts[0].url: _Response(spec.artifacts[0].url, b"node")})
        with TemporaryDirectory() as directory:
            root = Path(directory) / "fresh"
            result = materializer.materialize_authorized_release(
                root, spec.platform, spec, transport, authorization=materializer._mint_release_authorization_from_operator_cli(),
            )
            self.assertEqual((root / "node/node.tar").read_bytes(), b"node")
            self.assertEqual((root.stat().st_mode & 0o777), 0o700)
        self.assertEqual(result.target_id, sha256(str(root.resolve()).encode()).hexdigest())
        self.assertEqual(result.count, 1)
        self.assertEqual(result.digests, (sha256(b"node").hexdigest(),))
        self.assertNotIsInstance(result, materializer.VerifiedImageInputArtifactSet)
        self.assertTrue(result.proposal.untrusted)

    def test_rejects_redirect_and_preserves_no_proposal(self) -> None:
        spec = _spec()
        transport = _Transport({spec.artifacts[0].url: _Response(spec.artifacts[0].url, b"node", final_url="https://other.invalid/node")})
        with TemporaryDirectory() as directory:
            with self.assertRaises(materializer.PrimeImageMaterializerError):
                materializer.materialize_authorized_release(
                    Path(directory) / "fresh", spec.platform, spec, transport, authorization=materializer._mint_release_authorization_from_operator_cli(),
                )

    def test_canonicalizes_a_symlink_ancestor_for_staging_and_identity(self) -> None:
        spec = _spec()
        transport = _Transport({spec.artifacts[0].url: _Response(spec.artifacts[0].url, b"node")})
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
            self.assertEqual((canonical / "node/node.tar").read_bytes(), b"node")
            self.assertEqual(result.target_id, sha256(str(canonical.resolve()).encode()).hexdigest())

    def test_rejects_direct_or_replayed_authorization_before_fetching(self) -> None:
        spec = _spec()
        transport = _Transport({spec.artifacts[0].url: _Response(spec.artifacts[0].url, b"node")})
        with self.assertRaises(TypeError):
            materializer._ReleaseAuthorization(object())
        with TemporaryDirectory() as directory:
            token = materializer._mint_release_authorization_from_operator_cli()
            materializer.materialize_authorized_release(Path(directory) / "first", spec.platform, spec, transport, authorization=token)
            with self.assertRaises(materializer.PrimeImageMaterializerError):
                materializer.materialize_authorized_release(Path(directory) / "second", spec.platform, spec, transport, authorization=token)
            with self.assertRaises(materializer.PrimeImageMaterializerError):
                materializer.materialize_authorized_release(Path(directory) / "third", spec.platform, spec, transport, authorization=object())
        self.assertEqual(transport.calls, [spec.artifacts[0].url])

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
            ReleaseSpecification(valid.source_commit, valid.source_tree_sha256, valid.source_package_lock_sha256, valid.platform, (valid.artifacts[0], valid.artifacts[0])),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                materializer.validate_release_specification(value)

    def test_rejects_wrong_length_or_hash(self) -> None:
        spec = _spec()
        for response in (_Response(spec.artifacts[0].url, b"bad"), _Response(spec.artifacts[0].url, b"nodeX")):
            transport = _Transport({spec.artifacts[0].url: response})
            with TemporaryDirectory() as directory:
                with self.subTest(response=response.body), self.assertRaises(materializer.PrimeImageMaterializerError):
                    materializer.materialize_authorized_release(
                        Path(directory) / "fresh", spec.platform, spec, transport, authorization=materializer._mint_release_authorization_from_operator_cli(),
                    )
