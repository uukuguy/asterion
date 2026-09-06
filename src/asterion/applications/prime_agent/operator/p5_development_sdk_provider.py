"""P5's closed four-call provider profile over the killable P1-B transport."""

from __future__ import annotations

from collections.abc import Mapping

from .model_broker import PrimeModelBrokerTokenUsage
from .p1b_development_sdk_provider import (
    PrimeP1BDevelopmentSdkProvider,
    create_prime_p1b_development_sdk_provider,
)

P5_PROVIDER_CALLBACK_LIMIT = 4
P5_PROVIDER_INPUT_LIMIT = 32_768
P5_PROVIDER_OUTPUT_LIMIT = 2_304
P5_PROVIDER_COST_LIMIT = 20_000
P5_PROVIDER_DEADLINE_SECONDS = 180


class PrimeP5DevelopmentSdkProviderError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P5 development SDK provider is unavailable")


class PrimeP5DevelopmentSdkProvider:
    """Fence the inherited killable transport at P5's four callbacks."""

    __slots__ = ("_inner", "_calls", "_closed")

    def __init__(self, inner: PrimeP1BDevelopmentSdkProvider) -> None:
        if type(inner) is not PrimeP1BDevelopmentSdkProvider:
            raise PrimeP5DevelopmentSdkProviderError()
        self._inner, self._calls, self._closed = inner, 0, False

    def __repr__(self) -> str:
        return "PrimeP5DevelopmentSdkProvider(redacted)"

    async def __call__(self, body: bytes) -> bytes:
        if (
            self._closed
            or type(body) is not bytes
            or not body
            or self._calls >= P5_PROVIDER_CALLBACK_LIMIT
        ):
            raise PrimeP5DevelopmentSdkProviderError()
        try:
            reply = await self._inner(body)
            self._calls += 1
            return reply
        except BaseException:
            raise PrimeP5DevelopmentSdkProviderError() from None

    def terminal_usage(self) -> PrimeModelBrokerTokenUsage:
        if self._calls != P5_PROVIDER_CALLBACK_LIMIT:
            raise PrimeP5DevelopmentSdkProviderError()
        usage = self._inner._provisional  # noqa: SLF001
        if (
            usage.input_tokens > P5_PROVIDER_INPUT_LIMIT
            or usage.output_tokens > P5_PROVIDER_OUTPUT_LIMIT
            or usage.cost_microunits > P5_PROVIDER_COST_LIMIT
        ):
            raise PrimeP5DevelopmentSdkProviderError()
        return usage

    async def close(self) -> None:
        self._closed = True
        await self._inner.close()


def create_prime_p5_development_sdk_provider(
    operator_config: Mapping[str, object],
) -> PrimeP5DevelopmentSdkProvider:
    try:
        return PrimeP5DevelopmentSdkProvider(
            create_prime_p1b_development_sdk_provider(operator_config)
        )
    except BaseException:
        raise PrimeP5DevelopmentSdkProviderError() from None
