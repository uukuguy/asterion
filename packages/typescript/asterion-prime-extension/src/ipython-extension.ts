import { closeSync } from "node:fs";
import { createIpythonBridge, createIpythonTool, descriptorFromEnvironment, unavailable,
  type IpythonBridge, type MethodTool } from "./tool-bridge.js";
export { PROTOCOL, IPYTHON_PARAMETERS, createIpythonBridge, createIpythonTool, IpythonBridge } from "./tool-bridge.js";
export type { IpythonToolResult, ToolExecutionMode } from "./tool-bridge.js";
import { memoryRecord } from "./context-memory.js";
import { discardContextWitnessEnvironment, registerContextWitnessFromEnvironment, type ContextWitness } from "./context-witness.js";
export {nativeContextArchive,createContextCheckpoint,contextArchiveOperation} from './context-archive.js';
import { contextViewMetricsFromEnvironment, type ContextViewMetricsSink } from "./context-metrics.js";
export { ContextViewTelemetry, contextViewMetricsFromEnvironment } from "./context-metrics.js";
import {providerPrefixMetricsFromEnvironment, registerProviderPrefixMetrics, type ProviderPrefixMetricsSink} from "./provider-prefix-metrics.js";
export {ProviderPrefixTelemetry, providerPrefixMetricsFromEnvironment, registerProviderPrefixMetrics} from "./provider-prefix-metrics.js";
export { TOOL_STATE_VIEW_VERSION, admitToolStateView, projectToolStateViews, projectToolStateViewContext } from "./tool-state-view.js";
export { CONTEXT_MEMORY_VERSION, PRIMARY_CONTEXT_MEMORY_VERSION, MemoryContextController, projectMemoryContext } from "./context-memory.js";
export { registerContextWitness, ContextWitness, composeSummarizationRequest, summarizeInstruction } from "./context-witness.js";
export { canonicalJson, projectPrimeContext, countRebuiltContext } from "./context-counter.js";
export { normalizeFunctionParameters } from "./tool-schema.js";

export interface ExtensionApi {
  registerTool(tool: ReturnType<typeof createIpythonTool>): void;
}

export interface PrimeToolModule {
  readonly registry: {
    readonly module_id: string;
    readonly capability_id: string;
    readonly tool_names: readonly string[];
  };
  createTools(bridge: IpythonBridge): readonly MethodTool[];
  registerContextHooks?(pi: ExtensionApi, dependencies: unknown): void;
}

export interface PrimeToolModuleDependencies {
  readonly contextMetrics?: ContextViewMetricsSink;
  readonly nativeDependencies?: unknown;
}

export const coreOnlyModule: PrimeToolModule = Object.freeze({
  registry: Object.freeze({module_id: "prime.ipython", capability_id: "prime.tool.ipython",
    tool_names: Object.freeze(["ipython"])}),
  createTools: () => [],
});

const REGISTRY_ENVIRONMENT = "ASTERION_PRIME_IPYTHON_TOOL_REGISTRY";
const MODULE_IDENTIFIER = /^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$(?![\s\S])/;
const TOOL_IDENTIFIER = /^[a-z][a-z0-9_.:-]{0,255}$(?![\s\S])/;

function validateRegistry(value: unknown): PrimeToolModule["registry"] {
  const record = memoryRecord(value);
  if (!record || Object.keys(record).sort().join(",") !== "capability_id,module_id,tool_names"
    || typeof record.module_id !== "string" || !MODULE_IDENTIFIER.test(record.module_id)
    || typeof record.capability_id !== "string" || !MODULE_IDENTIFIER.test(record.capability_id)
    || !Array.isArray(record.tool_names) || record.tool_names.length === 0
    || record.tool_names.some(name => typeof name !== "string" || !TOOL_IDENTIFIER.test(name))
    || JSON.stringify(record.tool_names) !== JSON.stringify([...new Set(record.tool_names)].sort())) throw unavailable();
  return Object.freeze({
    module_id: record.module_id,
    capability_id: record.capability_id,
    tool_names: Object.freeze([...record.tool_names] as string[]),
  });
}

function expectedRegistryFromEnvironment(): PrimeToolModule["registry"] {
  const raw = process.env[REGISTRY_ENVIRONMENT];
  delete process.env[REGISTRY_ENVIRONMENT];
  if (raw === undefined) throw unavailable();
  return validateRegistry(JSON.parse(raw));
}

export function registerPrime(pi: ExtensionApi, dependencies: unknown, module: PrimeToolModule): void {
  let descriptor: number | undefined;
  let witness: ContextWitness | undefined;
  let metrics: ContextViewMetricsSink | undefined;
  let prefixMetrics: ProviderPrefixMetricsSink | undefined;
  try {
    metrics = contextViewMetricsFromEnvironment();
    prefixMetrics = providerPrefixMetricsFromEnvironment();
    descriptor = descriptorFromEnvironment();
    const expected = expectedRegistryFromEnvironment();
    const declared = validateRegistry(module.registry);
    if (expected.module_id !== declared.module_id || expected.capability_id !== declared.capability_id
      || JSON.stringify(expected.tool_names) !== JSON.stringify(declared.tool_names)) throw unavailable();
    if (typeof pi !== "object" || pi === null || typeof pi.registerTool !== "function") throw unavailable();
    const bridge = createIpythonBridge(descriptor);
    const tools = [createIpythonTool(bridge), ...module.createTools(bridge)];
    if (JSON.stringify(tools.map(tool => tool.name).sort()) !== JSON.stringify(declared.tool_names)) throw unavailable();
    witness = registerContextWitnessFromEnvironment(pi, dependencies);
    if (module.registerContextHooks) module.registerContextHooks(pi, {contextMetrics: metrics, nativeDependencies: dependencies});
    else metrics?.close();
    if (prefixMetrics && !registerProviderPrefixMetrics(pi,prefixMetrics)) prefixMetrics.close();
    if (metrics && typeof memoryRecord(pi)?.on === "function") {
      try {
        (pi as ExtensionApi & {on(event: string, handler: () => void): unknown})
          .on("session_shutdown", () => metrics?.close());
      } catch {metrics.close();}
    }
    for (const tool of tools) pi.registerTool(tool as unknown as ReturnType<typeof createIpythonTool>);
  } catch {
    delete process.env[REGISTRY_ENVIRONMENT];
    witness?.close();
    metrics?.close();
    prefixMetrics?.close();
    discardContextWitnessEnvironment();
    try { if (descriptor !== undefined) closeSync(descriptor); } catch {}
    throw unavailable();
  }
}

export function toolNames(): string[] { return [...coreOnlyModule.registry.tool_names]; }
export function register(pi: ExtensionApi, dependencies?: unknown): void {
  registerPrime(pi, dependencies, coreOnlyModule);
}
export default register;
