"""The selected Prime P3/P5/P6 application must bind executable work."""

from __future__ import annotations

import unittest

from asterion.applications.provider import compose_installed_provider
from asterion.applications.prime.provider import (
    create_prime_bounded_autonomy_provider,
    create_prime_continual_improvement_provider,
    create_prime_recursive_workflow_provider,
)
from asterion.capabilities.prime_bounded_autonomy_native.provider import (
    create_prime_bounded_autonomy_native_package,
)
from asterion.capabilities.prime_continual_improvement_native.provider import (
    create_prime_continual_improvement_native_package,
)
from asterion.capabilities.prime_recursive_workflow_native.provider import (
    create_prime_recursive_workflow_native_package,
)
from asterion.runtime.factory import RuntimeFactoryRegistry


class PrimeComposedExecutionTests(unittest.TestCase):
    def test_selected_application_binds_its_executable_capability(self) -> None:
        cases = (
            ("prime.recursive-workflow", create_prime_recursive_workflow_provider, create_prime_recursive_workflow_native_package),
            ("prime.bounded-autonomy", create_prime_bounded_autonomy_provider, create_prime_bounded_autonomy_native_package),
            ("prime.continual-improvement", create_prime_continual_improvement_provider, create_prime_continual_improvement_native_package),
        )
        for application_id, provider_factory, package_factory in cases:
            with self.subTest(application_id=application_id):
                package = package_factory()
                provider = compose_installed_provider(
                    provider_factory(),
                    runtime_factories=RuntimeFactoryRegistry(()),
                    installed_packages=(package,),
                )
                application = provider.applications[0]
                self.assertEqual(application.application_id, application_id)
                self.assertEqual(len(application.implementations), 1)
                manifest = application.assemblies[0].plan.capability_manifests
                self.assertEqual(
                    [item["capability_id"] for item in manifest if item["kind"] != "policy"],
                    [application_id],
                )


if __name__ == "__main__":
    unittest.main()
