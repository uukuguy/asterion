"""Prime harness launch. The base Pi session owns the process."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .compaction_budget import PrimeCompactionPolicy

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


class PersistentLaunch:
    """One launch's acquired descriptors and transport, owned by Prime."""
    def __init__(self):
        self.binding = self.lease = self.bridge = self.rpc = self.session = None
        self.metrics = self.prefix_metrics = None
        self.witness = self.store = None
        self.command = self.environment = None

    def close_descriptors(self):
        if self.lease is not None:
            self.lease.close()
        for metrics in (self.metrics, self.prefix_metrics):
            if metrics is not None:
                metrics.close()


def persistent_command(operator, spec, lease):
    command = (*persistent_base_command(operator.executable, operator.entry, operator.effort,
                                        spec.tools.registry.tool_names),
               '--provider', operator.provider, '--model', operator.model)
    if spec.system_prompt is not None:
        command += ('--system-prompt', spec.system_prompt)
    return (*command, *lease.command_args())


def persistent_launch(operator, spec, services, limits, hooks, *, metrics_root=None, durable=False,
                      compaction_policy=PrimeCompactionPolicy(),
                      compaction_policy_source='framework-default'):
    """Acquire the explicit artifact and bridge without any application discovery."""
    import socket
    import json
    import secrets
    from dataclasses import asdict, fields
    from asterion.agents.prime._tool_bridge import (
        OUTPUT_BYTES_ENVIRONMENT, ToolBridgeServer, output_capacity,
    )
    from asterion.agents.prime.context_view_metrics import ContextViewMetricsFile, ProviderPrefixMetricsFile
    from asterion.agents.prime.session import AsterionPrimeSession
    from asterion.agents.prime.tool_registry import TOOL_REGISTRY_ENV
    from asterion.runtime.pinned_extension import ExtensionBinding
    from asterion.runtime.native_rpc import build_rpc_session

    from asterion.agents.prime.context import _validate_policy
    _validate_policy(compaction_policy, compaction_policy_source)
    policy_json = json.dumps({**asdict(compaction_policy),
        'config_source': compaction_policy_source}, sort_keys=True, separators=(',', ':'))
    if len(policy_json.encode('utf-8')) > 512:
        raise ValueError('Prime compaction policy is invalid')
    resource = PersistentLaunch()
    parent = child = witness_parent = witness_child = None
    try:
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        environment = {'ASTERION_PRIME_IPYTHON_FD': str(child.fileno()),
                       OUTPUT_BYTES_ENVIRONMENT: str(output_capacity(services)),
                       TOOL_REGISTRY_ENV: spec.tools.registry.environment_value()}
        descriptors = [child.fileno()]
        if durable:
            from asterion.agents.prime.context import PrimeContextWitnessSession
            witness_parent, witness_child = socket.socketpair()
            nonce = secrets.token_hex(32)
            descriptors.append(witness_child.fileno())
            environment.update({'ASTERION_PRIME_IPYTHON_CONTEXT_FD': str(witness_child.fileno()),
                                'ASTERION_PRIME_IPYTHON_CONTEXT_LAUNCH_NONCE': nonce,
                                'ASTERION_PRIME_IPYTHON_COMPACTION_POLICY': policy_json})
            resource.witness = PrimeContextWitnessSession(
                witness_parent, launch_nonce=nonce, timeout_seconds=60, mark_uncertain=lambda: None,
                policy=compaction_policy, config_source=compaction_policy_source)
            resource.witness._validate_arm_capacity()
            witness_parent = None
        if metrics_root is not None:
            resource.metrics = ContextViewMetricsFile(metrics_root / 'context-view-metrics.json')
            resource.prefix_metrics = ProviderPrefixMetricsFile(metrics_root / 'provider-prefix-metrics.json')
            for key, metrics in (('CONTEXT', resource.metrics), ('PREFIX', resource.prefix_metrics)):
                descriptors.append(metrics.descriptor)
                environment[f'ASTERION_PRIME_IPYTHON_{key}_METRICS_FD'] = str(metrics.descriptor)
        resource.binding = ExtensionBinding('prime.ipython', spec.tools.path, ('prime.tool.ipython',),
                                            tuple(sorted(descriptors)), environment)
        resource.lease = resource.binding.preflight()
        child.close()
        child = None
        if witness_child is not None:
            witness_child.close()
            witness_child = None
        if set(operator.environment).intersection(resource.lease.environment):
            raise ValueError('Prime launch environment is invalid')
        environment = {**operator.environment, **resource.lease.environment}
        command = persistent_command(operator, spec, resource.lease)
        resource.command, resource.environment = command, environment
        resource.rpc = build_rpc_session(
            command=command, cwd=operator.cwd, environment=environment,
            deadline_seconds=None if limits.deadline_ms is None else limits.deadline_ms / 1000,
            inherited_fds=resource.lease.inherited_fds, compact_events=True,
            diagnostics=operator.diagnostics, private_failure_sink=operator.private_failure_sink,
            expected_provider=operator.provider, expected_model=operator.model)
        if not durable:
            resource.session = AsterionPrimeSession(
                rpc_session=resource.rpc, extension_binding=resource.binding,
                extension_lease=resource.lease, approved_command=command,
                approved_environment=environment, limits=limits,
                allowed_tool_names=spec.tools.registry.allowed_tool_names,
                diagnostics=operator.diagnostics,
                **{field.name: getattr(hooks, field.name) for field in fields(hooks)})
        resource.bridge = ToolBridgeServer(parent, services)
        if not durable:
            resource.bridge.start()
        parent = None
        return resource
    except BaseException:
        if parent is not None:
            parent.close()
        if child is not None:
            child.close()
        for channel in (witness_parent, witness_child):
            if channel is not None:
                channel.close()
        if resource.witness is not None:
            resource.witness.close()
        if resource.bridge is not None:
            resource.bridge.close()
        resource.close_descriptors()
        raise


def persistent_base_command(executable, entry, effort, tool_names):
    prefix = (str(executable),) if entry is None else (str(executable), str(entry))
    return (*prefix, '--mode', 'rpc', '--print', '--no-builtin-tools',
            '--tools', ','.join(tool_names), '--approve', '--no-session', '--no-extensions',
            '--no-skills', '--no-prompt-templates', '--no-themes', '--no-context-files',
            '--thinking', effort)


async def force_close_rpc(rpc) -> None:
    """Ask the base session to reap its process without the command lock."""
    await rpc.force_close()
