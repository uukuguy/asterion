from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError

from asterion.services.registry import (
    HostServiceFactoryBinding,
    HostServiceFactoryRegistry,
    HostServiceRegistryError,
    parse_host_service_options,
)


class _EntryPoint:
    group = "asterion.host_services"

    def __init__(self, name: str, factory) -> None:
        self.name = name
        self._factory = factory
        self.loads = 0

    def load(self):
        self.loads += 1
        return self._factory


def _binding(
    capability_id: str,
    *,
    option_names: tuple[str, ...] = (),
    events: list[str] | None = None,
) -> HostServiceFactoryBinding:
    @asynccontextmanager
    async def service(context):
        if events is not None:
            events.append(f"enter:{context.capability_id}")
        try:
            yield context
        finally:
            if events is not None:
                events.append(f"exit:{context.capability_id}")

    return HostServiceFactoryBinding(
        capability_id=capability_id,
        option_names=option_names,
        factory=service,
    )


class HostServiceOptionTests(unittest.TestCase):
    def test_options_are_grouped_by_exact_capability_and_frozen(self) -> None:
        parsed = parse_host_service_options(
            ("corpus.local-root:root=/private/corpus", "service.other:mode=strict")
        )

        self.assertEqual(
            parsed,
            {
                "corpus.local-root": {"root": "/private/corpus"},
                "service.other": {"mode": "strict"},
            },
        )
        with self.assertRaises(TypeError):
            parsed["corpus.local-root"]["root"] = "replacement"
        self.assertNotIn("/private/corpus", repr(parsed))

    def test_invalid_or_duplicate_options_are_rejected_without_echoing_values(
        self,
    ) -> None:
        sentinel = "SECRET-HOST-OPTION"
        cases = (
            (f"missing={sentinel}",),
            (f"Bad.capability:key={sentinel}",),
            (f"valid.capability:Bad_key={sentinel}",),
            (f"valid.capability:key={sentinel}\n",),
            (
                f"valid.capability:key={sentinel}",
                "valid.capability:key=replacement",
            ),
            (object(),),
        )
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(HostServiceRegistryError) as raised:
                    parse_host_service_options(values)
                self.assertNotIn(sentinel, str(raised.exception))


class HostServiceFactoryRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_factories_receive_frozen_exact_contexts(self) -> None:
        events: list[str] = []
        selected = _EntryPoint(
            "corpus.local-root",
            lambda: _binding(
                "corpus.local-root", option_names=("root",), events=events
            ),
        )
        adjacent = _EntryPoint(
            "service.adjacent",
            lambda: (_ for _ in ()).throw(AssertionError("adjacent loaded")),
        )
        registry = HostServiceFactoryRegistry((adjacent, selected))

        async with registry.open(
            provider_id="dci-agent-lite",
            application_id="dci.research-capability",
            application_version="1.0.0",
            capability_ids=("corpus.local-root",),
            options={"corpus.local-root": {"root": "/private/corpus"}},
        ) as services:
            context = services["corpus.local-root"]
            self.assertEqual(context.provider_id, "dci-agent-lite")
            self.assertEqual(context.application_id, "dci.research-capability")
            self.assertEqual(context.application_version, "1.0.0")
            self.assertEqual(context.capability_id, "corpus.local-root")
            self.assertEqual(context.options, {"root": "/private/corpus"})
            self.assertNotIn("/private/corpus", repr(context))
            with self.assertRaises(FrozenInstanceError):
                context.capability_id = "service.other"
            with self.assertRaises(TypeError):
                context.options["root"] = "replacement"
            with self.assertRaises(TypeError):
                services["service.other"] = object()

        self.assertEqual(selected.loads, 1)
        self.assertEqual(adjacent.loads, 0)
        self.assertEqual(
            events, ["enter:corpus.local-root", "exit:corpus.local-root"]
        )

    async def test_selected_service_mapping_repr_is_redacted(self) -> None:
        class SecretService:
            def __repr__(self) -> str:
                return "<SECRET-SERVICE-VALUE>"

        @asynccontextmanager
        async def service(context):
            del context
            yield SecretService()

        entry = _EntryPoint(
            "service.selected",
            lambda: HostServiceFactoryBinding(
                capability_id="service.selected",
                option_names=(),
                factory=service,
            ),
        )

        async with HostServiceFactoryRegistry((entry,)).open(
            provider_id="provider",
            application_id="application",
            application_version="1.0.0",
            capability_ids=("service.selected",),
            options={},
        ) as services:
            self.assertNotIn("SECRET-SERVICE-VALUE", repr(services))

    async def test_missing_duplicate_unknown_and_mismatched_factories_fail_closed(
        self,
    ) -> None:
        valid = _EntryPoint(
            "service.selected", lambda: _binding("service.selected")
        )
        cases = (
            (),
            (valid, valid),
            (
                _EntryPoint(
                    "service.selected", lambda: _binding("service.mismatched")
                ),
            ),
        )
        for entries in cases:
            with self.subTest(entries=len(entries)):
                registry = HostServiceFactoryRegistry(entries)
                with self.assertRaises(HostServiceRegistryError):
                    async with registry.open(
                        provider_id="provider",
                        application_id="application",
                        application_version="1.0.0",
                        capability_ids=("service.selected",),
                        options={},
                    ):
                        self.fail("unreachable")

        registry = HostServiceFactoryRegistry((valid,))
        with self.assertRaises(HostServiceRegistryError):
            async with registry.open(
                provider_id="provider",
                application_id="application",
                application_version="1.0.0",
                capability_ids=("service.selected",),
                options={"service.undeclared": {}},
            ):
                self.fail("unreachable")
        self.assertEqual(valid.loads, 0)

    async def test_unknown_options_fail_before_service_entry(self) -> None:
        events: list[str] = []
        entry = _EntryPoint(
            "service.selected",
            lambda: _binding(
                "service.selected", option_names=("allowed",), events=events
            ),
        )
        registry = HostServiceFactoryRegistry((entry,))

        with self.assertRaises(HostServiceRegistryError):
            async with registry.open(
                provider_id="provider",
                application_id="application",
                application_version="1.0.0",
                capability_ids=("service.selected",),
                options={"service.selected": {"unknown": "SECRET"}},
            ):
                self.fail("unreachable")

        self.assertEqual(events, [])

        @asynccontextmanager
        async def managed():
            events.append("managed-enter")
            yield object()

        with self.assertRaises(HostServiceRegistryError):
            async with HostServiceFactoryRegistry(()).open(
                provider_id="provider",
                application_id="application",
                application_version="1.0.0",
                capability_ids=("executor.controlled",),
                options={"executor.controlled": {"unknown": "SECRET"}},
                managed={"executor.controlled": managed()},
            ):
                self.fail("unreachable")
        self.assertNotIn("managed-enter", events)

    async def test_one_stack_exits_managed_and_factory_services_on_all_paths(
        self,
    ) -> None:
        for outcome in ("success", "failure", "cancel"):
            with self.subTest(outcome=outcome):
                events: list[str] = []

                @asynccontextmanager
                async def managed():
                    events.append("enter:executor.controlled")
                    try:
                        yield object()
                    finally:
                        events.append("exit:executor.controlled")

                entry = _EntryPoint(
                    "service.selected",
                    lambda: _binding("service.selected", events=events),
                )
                registry = HostServiceFactoryRegistry((entry,))

                async def run() -> None:
                    async with registry.open(
                        provider_id="provider",
                        application_id="application",
                        application_version="1.0.0",
                        capability_ids=(
                            "executor.controlled",
                            "service.selected",
                        ),
                        options={},
                        managed={"executor.controlled": managed()},
                    ) as services:
                        self.assertEqual(set(services), {
                            "executor.controlled",
                            "service.selected",
                        })
                        if outcome == "failure":
                            raise RuntimeError("fixture")
                        if outcome == "cancel":
                            await asyncio.sleep(30)

                task = asyncio.create_task(run())
                await asyncio.sleep(0)
                if outcome == "cancel":
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                elif outcome == "failure":
                    with self.assertRaises(RuntimeError):
                        await task
                else:
                    await task
                self.assertEqual(
                    events,
                    [
                        "enter:executor.controlled",
                        "enter:service.selected",
                        "exit:service.selected",
                        "exit:executor.controlled",
                    ],
                )

    async def test_service_exit_failures_are_redacted(self) -> None:
        @asynccontextmanager
        async def service(context):
            del context
            yield object()
            raise RuntimeError("SECRET-SERVICE-EXIT")

        entry = _EntryPoint(
            "service.selected",
            lambda: HostServiceFactoryBinding(
                capability_id="service.selected",
                option_names=(),
                factory=service,
            ),
        )

        with self.assertRaises(HostServiceRegistryError) as raised:
            async with HostServiceFactoryRegistry((entry,)).open(
                provider_id="provider",
                application_id="application",
                application_version="1.0.0",
                capability_ids=("service.selected",),
                options={},
            ):
                pass

        self.assertNotIn("SECRET-SERVICE-EXIT", str(raised.exception))

    async def test_truthy_service_exit_cannot_suppress_body_failure(self) -> None:
        class SuppressingManager:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, exc_type, exc, traceback):
                del exc_type, exc, traceback
                return True

        entry = _EntryPoint(
            "service.selected",
            lambda: HostServiceFactoryBinding(
                capability_id="service.selected",
                option_names=(),
                factory=lambda context: SuppressingManager(),
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "body failure"):
            async with HostServiceFactoryRegistry((entry,)).open(
                provider_id="provider",
                application_id="application",
                application_version="1.0.0",
                capability_ids=("service.selected",),
                options={},
            ):
                raise RuntimeError("body failure")

    async def test_partial_enter_failure_exits_prior_services(self) -> None:
        events: list[str] = []

        @asynccontextmanager
        async def first(context):
            del context
            events.append("enter:first")
            try:
                yield object()
            finally:
                events.append("exit:first")

        @asynccontextmanager
        async def second(context):
            del context
            events.append("enter:second")
            raise RuntimeError("SECRET-ENTER")
            yield object()

        entries = (
            _EntryPoint(
                "service.first",
                lambda: HostServiceFactoryBinding(
                    "service.first", (), first
                ),
            ),
            _EntryPoint(
                "service.second",
                lambda: HostServiceFactoryBinding(
                    "service.second", (), second
                ),
            ),
        )

        with self.assertRaises(HostServiceRegistryError) as raised:
            async with HostServiceFactoryRegistry(entries).open(
                provider_id="provider",
                application_id="application",
                application_version="1.0.0",
                capability_ids=("service.first", "service.second"),
                options={},
            ):
                self.fail("unreachable")

        self.assertEqual(
            events, ["enter:first", "enter:second", "exit:first"]
        )
        self.assertNotIn("SECRET-ENTER", str(raised.exception))

    async def test_multiple_exit_failures_attempt_every_cleanup(self) -> None:
        events: list[str] = []

        def binding(capability_id: str) -> HostServiceFactoryBinding:
            @asynccontextmanager
            async def service(context):
                del context
                events.append(f"enter:{capability_id}")
                try:
                    yield object()
                finally:
                    events.append(f"exit:{capability_id}")
                    raise RuntimeError(f"SECRET-EXIT-{capability_id}")

            return HostServiceFactoryBinding(capability_id, (), service)

        entries = (
            _EntryPoint("service.first", lambda: binding("service.first")),
            _EntryPoint("service.second", lambda: binding("service.second")),
        )
        with self.assertRaises(HostServiceRegistryError) as raised:
            async with HostServiceFactoryRegistry(entries).open(
                provider_id="provider",
                application_id="application",
                application_version="1.0.0",
                capability_ids=("service.first", "service.second"),
                options={},
            ):
                pass

        self.assertEqual(
            events,
            [
                "enter:service.first",
                "enter:service.second",
                "exit:service.second",
                "exit:service.first",
            ],
        )
        self.assertNotIn("SECRET-EXIT", str(raised.exception))

    async def test_truthy_managed_and_factory_exits_preserve_cancellation(
        self,
    ) -> None:
        events: list[str] = []

        class TruthyManager:
            def __init__(self, name: str) -> None:
                self.name = name

            async def __aenter__(self):
                events.append(f"enter:{self.name}")
                return object()

            async def __aexit__(self, exc_type, exc, traceback):
                del exc_type, exc, traceback
                events.append(f"exit:{self.name}")
                return True

        entry = _EntryPoint(
            "service.selected",
            lambda: HostServiceFactoryBinding(
                "service.selected",
                (),
                lambda context: TruthyManager("service.selected"),
            ),
        )

        async def run() -> None:
            async with HostServiceFactoryRegistry((entry,)).open(
                provider_id="provider",
                application_id="application",
                application_version="1.0.0",
                capability_ids=("executor.controlled", "service.selected"),
                options={},
                managed={
                    "executor.controlled": TruthyManager(
                        "executor.controlled"
                    )
                },
            ):
                await asyncio.sleep(30)

        task = asyncio.create_task(run())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(
            events,
            [
                "enter:executor.controlled",
                "enter:service.selected",
                "exit:service.selected",
                "exit:executor.controlled",
            ],
        )


if __name__ == "__main__":
    unittest.main()
