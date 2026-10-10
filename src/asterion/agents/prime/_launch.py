"""Prime-owned process construction from preflighted operator data."""
from __future__ import annotations

from typing import TYPE_CHECKING

from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcSession

if TYPE_CHECKING:
    from asterion.agents.prime.application import PrimeApplicationSpec, PrimeOperatorContext


def text_command(operator: PrimeOperatorContext, spec: PrimeApplicationSpec) -> tuple[str, ...]:
    """Use a fixed text-only profile; applications cannot supply launch flags."""
    if spec.profile != 'text-only':
        raise ValueError('Prime text profile is unavailable')
    executable = (str(operator.executable),)
    if operator.entry is not None:
        executable += (str(operator.entry),)
    prompt = spec.system_prompt or 'Follow the user task exactly. Return only the requested JSON.'
    return (*executable, '--mode', 'rpc', '--print', '--no-tools', '--no-session',
            '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-themes',
            '--no-context-files', '--system-prompt', prompt, '--thinking', operator.effort,
            '--provider', operator.provider, '--model', operator.model)


def text_rpc(config: PiRpcConfig) -> PiRpcSession:
    """Single private seam for the existing RPC engine."""
    return PiRpcSession(config)
