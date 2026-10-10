"""P7 admits the exact model pair while preserving historical trace readers.

``ASTERION_PRIME_PROVIDER`` / ``ASTERION_PRIME_MODEL`` must resolve to the exact
approved pair. Runtime options and Prime-owned commands follow that pair;
offline trace readers retain support for earlier model identities.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


_CATALOG = {
    "openai-codex": {"models": [{"id": "gpt-6-sol"}, {"id": "gpt-6-astra"}]},
    "deepseek": {"models": [{"id": "deepseek-flash"}]},
}
_AUTH = {"openai-codex": {"type": "oauth", "access": "profile-token"}}


def _profile(directory: str, *, catalog: object = _CATALOG, auth: object = _AUTH) -> str:
    """Materialize one minimal Pi profile the operator would supply."""

    root = Path(directory) / "profile"
    root.mkdir()
    (root / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
    (root / "models-store.json").write_text(json.dumps(catalog), encoding="utf-8")
    return str(root)


class TestP7ModelSelection(unittest.TestCase):
    def test_defaults_apply_when_the_environment_declares_nothing(self) -> None:
        from asterion.applications.prime.p7.model_selection import (
            resolve_model_selection,
        )

        with tempfile.TemporaryDirectory() as directory:
            selection = resolve_model_selection(
                {"ASTERION_PRIME_PI_AGENT_DIR": _profile(directory)}
            )
        self.assertEqual((selection.provider, selection.model), ("openai-codex", "gpt-6.1-sol"))

    def test_explicit_exact_pair_reaches_runtime_options(self) -> None:
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import (
            p7_runtime_options,
            resolve_p7_runtime,
        )

        environment = {
            "ASTERION_PRIME_PROVIDER": "openai-codex",
            "ASTERION_PRIME_MODEL": "gpt-6.1-sol",
        }
        with tempfile.TemporaryDirectory() as directory:
            environment["ASTERION_PRIME_PI_AGENT_DIR"] = _profile(directory)
            selection = resolve_p7_runtime(
                environment, P7GameSelection("ls20-9607627b", 0, 1)
            )
            options = dict(
                p7_runtime_options(
                    selection, P7GameSelection("ls20-9607627b", 0, 1)
                )
            )
        self.assertEqual((selection.provider, selection.model), ("openai-codex", "gpt-6.1-sol"))
        self.assertEqual(options["model"], "gpt-6.1-sol")
        self.assertEqual(options["provider"], "openai-codex")

    def test_an_environment_key_provider_resolves_without_auth_entry(self) -> None:
        from asterion.applications.prime.p7.model_selection import (
            resolve_model_selection,
        )

        environment = {
            "ASTERION_PRIME_PROVIDER": "openai-codex",
            "ASTERION_PRIME_MODEL": "gpt-6.1-sol",
            "CODEX_API_KEY": "operator-secret",
        }
        with tempfile.TemporaryDirectory() as directory:
            environment["ASTERION_PRIME_PI_AGENT_DIR"] = _profile(directory, auth={})
            selection = resolve_model_selection(environment)
        self.assertEqual((selection.provider, selection.model), ("openai-codex", "gpt-6.1-sol"))

    def test_incompatible_pair_rejects_before_profile_or_model_effects(self) -> None:
        from asterion.applications.prime.p7 import model_selection

        for provider, model in (("openai-codex", "gpt-6-astra"),
                                ("openai-codex", "gpt-6-sol"),
                                ("deepseek", "deepseek-flash"),
                                ("deepseek", "gpt-6.1-sol")):
            with (
                self.subTest(provider=provider, model=model),
                mock.patch.object(model_selection, "_agent_dir") as profile,
                mock.patch.object(model_selection, "_catalog") as catalog,
                mock.patch.object(model_selection, "_has_credential") as credential,
            ):
                with self.assertRaisesRegex(model_selection.P7ModelSelectionError, "^P7 model selection is incompatible$"):
                    model_selection.resolve_model_selection({
                        "ASTERION_PRIME_PROVIDER": provider, "ASTERION_PRIME_MODEL": model,
                        "CODEX_API_KEY": "PRIVATE-KEY",
                    })
                profile.assert_not_called()
                catalog.assert_not_called()
                credential.assert_not_called()

    def test_well_formed_model_can_be_selected_before_profile_catalog_refresh(self) -> None:
        from asterion.applications.prime.p7.model_selection import resolve_model_selection

        environment = {
            "ASTERION_PRIME_PROVIDER": "openai-codex",
            "ASTERION_PRIME_MODEL": "gpt-6.1-sol",
        }
        with tempfile.TemporaryDirectory() as directory:
            environment["ASTERION_PRIME_PI_AGENT_DIR"] = _profile(directory)
            selection = resolve_model_selection(environment)
        self.assertEqual((selection.provider, selection.model), ("openai-codex", "gpt-6.1-sol"))

    def test_trace_identities_follow_the_selected_model(self) -> None:
        from asterion.applications.prime.p7.gameplay_trace import (
            GAMEPLAY_TRACE_IDENTITIES,
        )
        from asterion.applications.prime.p7.gameplay_trace import (
            trace_identities_for as gameplay_identities,
        )
        from asterion.applications.prime.p7.private_trace import (
            P7_TRACE_IDENTITIES,
            are_p7_trace_identities,
        )
        from asterion.applications.prime.p7.private_trace import (
            trace_identities_for as solve_identities,
        )

        for model in ("gpt-6-sol", "gpt-6-astra", "deepseek-flash"):
            with self.subTest(model=model):
                solve = solve_identities(model)
                gameplay = gameplay_identities(model)
                self.assertEqual(solve["model_id"], model)
                self.assertEqual(gameplay["model_id"], model)
                self.assertEqual(
                    set(solve) - {"model_id"}, set(P7_TRACE_IDENTITIES) - {"model_id"}
                )
                self.assertEqual(
                    set(gameplay) - {"model_id"},
                    set(GAMEPLAY_TRACE_IDENTITIES) - {"model_id"},
                )
                self.assertTrue(are_p7_trace_identities(solve))
                self.assertTrue(are_p7_trace_identities(solve, model_id=model))
                self.assertFalse(are_p7_trace_identities(solve, model_id="gpt-6-luna"))

    def test_foreign_or_malformed_identities_are_rejected(self) -> None:
        from asterion.applications.prime.p7.private_trace import (
            P7_TRACE_IDENTITIES,
            are_p7_trace_identities,
        )

        for value in (
            None,
            {},
            "identities",
            {**P7_TRACE_IDENTITIES, "application_id": "other.application"},
            {**P7_TRACE_IDENTITIES, "runtime_id": "other.runtime"},
            {**P7_TRACE_IDENTITIES, "model_id": ""},
            {**P7_TRACE_IDENTITIES, "model_id": "bad model"},
            {**P7_TRACE_IDENTITIES, "model_id": "bad\nmodel"},
        ):
            with self.subTest(value=value):
                self.assertFalse(are_p7_trace_identities(value))

    def test_unusable_selections_fail_closed_with_a_body_free_error(self) -> None:
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import (
            P7OperatorError,
            resolve_p7_runtime,
        )

        cases = (
            ("missing-profile", None),
            ("blank-profile", {"ASTERION_PRIME_PI_AGENT_DIR": "   "}),
            ("unlisted-provider", {"ASTERION_PRIME_PROVIDER": "mystery"}),
            ("unauthenticated", {"ASTERION_PRIME_MODEL": "gpt-6.1-sol"}),
            ("malformed-model", {"ASTERION_PRIME_MODEL": "bad name"}),
            ("oversize-model", {"ASTERION_PRIME_MODEL": "x" * 129}),
            ("non-ascii-model", {"ASTERION_PRIME_MODEL": "模型"}),
        )
        for name, change in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                if change is None:
                    environment: dict[str, str] = {}
                elif name == "unauthenticated":
                    environment = {
                        "ASTERION_PRIME_PI_AGENT_DIR": _profile(directory, auth={})
                    }
                else:
                    environment = {
                        "ASTERION_PRIME_PI_AGENT_DIR": _profile(directory)
                    }
                environment.update(change or {})
                with self.assertRaisesRegex(
                    P7OperatorError, "P7 model host is unavailable"
                ) as raised:
                    resolve_p7_runtime(
                        environment, P7GameSelection("ls20-9607627b", 0, 1)
                    )
                self.assertNotIn("ASTERION_PRIME_", str(raised.exception))

    def test_declared_exact_pair_is_available_without_profile_validation(self) -> None:
        from asterion.applications.prime.p7.model_selection import (
            declared_model_selection,
        )

        selection = declared_model_selection(
            {"ASTERION_PRIME_PROVIDER": "openai-codex", "ASTERION_PRIME_MODEL": "gpt-6.1-sol"}
        )
        self.assertEqual(selection.provider, "openai-codex")
        self.assertEqual(selection.model, "gpt-6.1-sol")

    def test_prefix_reuse_is_strict_only_on_the_runtime_path(self) -> None:
        from asterion.applications.prime.p7.private_trace import (
            P7_TRACE_IDENTITIES,
            trace_identities_for,
        )
        from asterion.applications.prime.p7.solutions import _known_trace_identities

        active = trace_identities_for("gpt-6-astra")
        historical = {**P7_TRACE_IDENTITIES, "model_id": "deepseek-v4-flash"}
        self.assertTrue(_known_trace_identities(active, "gpt-6-astra"))
        self.assertTrue(_known_trace_identities(P7_TRACE_IDENTITIES, "gpt-6.1-sol"))
        self.assertTrue(_known_trace_identities(historical, "gpt-6-astra"))
        self.assertFalse(_known_trace_identities(active, "gpt-6-sol"))
        self.assertTrue(_known_trace_identities(active, None))
        self.assertFalse(_known_trace_identities({"application_id": "other"}, None))
        self.assertFalse(_known_trace_identities("identities", None))

    def test_core_owned_command_declares_exactly_one_model_pair(self) -> None:
        from asterion.agents.prime import _launch
        from asterion.agents.prime.application import (
            PrimeApplicationSpec, PrimeOperatorContext, PrimeToolModuleArtifact,
        )
        from asterion.applications.prime.p7.tool_registry import P7_LEGACY_TOOL_REGISTRY

        operator = PrimeOperatorContext(
            executable=Path("/tmp/node"), entry=Path("/tmp/pi.mjs"), cwd=Path("/tmp"),
            provider="openai-codex", model="gpt-6.1-sol", effort="high",
            environment={}, task_deadline=None,
        )
        spec = PrimeApplicationSpec("prime.arc-agi-3-solving", "1.0.0", "persistent-code-tools",
            tools=PrimeToolModuleArtifact(Path("/tmp/extension.mjs"), P7_LEGACY_TOOL_REGISTRY))
        lease = SimpleNamespace(command_args=lambda: ("--extension", "/tmp/loader.mjs"))
        command = _launch.persistent_command(operator, spec, lease)
        self.assertEqual(command[:2], ("/tmp/node", "/tmp/pi.mjs"))
        self.assertEqual(command.count("--provider"), 1)
        self.assertEqual(command.count("--model"), 1)
        self.assertEqual(command[command.index("--provider") + 1], "openai-codex")
        self.assertEqual(command[command.index("--model") + 1], "gpt-6.1-sol")


if __name__ == "__main__":
    unittest.main()
