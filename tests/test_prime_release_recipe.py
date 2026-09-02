"""Tests for the platform-neutral Prime release recipe and candidate policy."""

from __future__ import annotations

from dataclasses import replace
import unittest

from asterion.applications.prime_agent.operator import release_recipe as recipe
from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
)


class TestPrimeReleaseRecipe(unittest.TestCase):
    def test_recipe_pins_prime_source_and_has_no_platform_field(self) -> None:
        value = recipe.PRIME_IPYTHON_RELEASE_RECIPE
        self.assertEqual(
            value.source.commit, "a18809e00ea30638584d87b3afea7285a9d7296c"
        )
        self.assertEqual(
            value.source.tree_sha256,
            "93a4b02ecc0cc114865fa3d336521cf214047cf4de471b36b51fe610c84ab686",
        )
        self.assertEqual(
            value.source.package_lock_sha256,
            "39ee303bca10c0933cf917275613c8f44099f50de1650a5c356e7cda02b701e8",
        )
        self.assertEqual(value.python_major_minor, "3.11")
        self.assertNotIn("platform", value.__dataclass_fields__)
        self.assertIs(recipe.validate_release_recipe(value), value)

    def test_candidate_policy_resolves_exact_arm64_and_amd64_only(self) -> None:
        for target in (
            ImagePlatformDescriptor("linux", "arm64", None),
            ImagePlatformDescriptor("linux", "amd64", None),
        ):
            with self.subTest(target=target):
                self.assertEqual(recipe.resolve_candidate_target(target), target)

    def test_candidate_policy_rejects_variants_host_values_and_substitutes(
        self,
    ) -> None:
        for target in (
            ImagePlatformDescriptor("linux", "arm64", "v8"),
            ImagePlatformDescriptor("darwin", "arm64", None),
            ImagePlatformDescriptor("linux", "s390x", None),
            {"os": "linux", "architecture": "arm64", "variant": None},
        ):
            with (
                self.subTest(target=target),
                self.assertRaises(recipe.PrimeReleaseRecipeError),
            ):
                recipe.resolve_candidate_target(target)

    def test_recipe_and_policy_reject_substitutes_unsorted_and_duplicate_values(
        self,
    ) -> None:
        substitute = replace(recipe.PRIME_IPYTHON_RELEASE_RECIPE)
        unsorted = recipe.CandidateTargetPolicy(
            (
                ImagePlatformDescriptor("linux", "amd64", None),
                ImagePlatformDescriptor("linux", "arm64", None),
            )
        )
        duplicate = recipe.CandidateTargetPolicy(
            (
                ImagePlatformDescriptor("linux", "arm64", None),
                ImagePlatformDescriptor("linux", "arm64", None),
            )
        )
        for value in (substitute, {"recipe": "mapping"}):
            with (
                self.subTest(value=value),
                self.assertRaises(recipe.PrimeReleaseRecipeError),
            ):
                recipe.validate_release_recipe(value)
        for value in (unsorted, duplicate):
            with (
                self.subTest(value=value),
                self.assertRaises(recipe.PrimeReleaseRecipeError),
            ):
                recipe.validate_candidate_target_policy(value)
