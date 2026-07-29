export const RUNTIME_PROTOCOL_VERSION = "asterion.agent-runtime/v1" as const;
export const PROTOCOL_VERSION = RUNTIME_PROTOCOL_VERSION;
export const CAPABILITY_PROTOCOL_VERSION = "asterion.capability/v1" as const;
export const APPLICATION_ASSEMBLY_PROTOCOL_VERSION =
  "asterion.application-assembly/v1" as const;
export const CAPABILITY_PACKAGE_PROTOCOL_VERSION =
  "asterion.capability-package/v1" as const;
export const BENCHMARK_SUITE_PROTOCOL_VERSION =
  "asterion.benchmark-suite/v1" as const;
export const CAPABILITY_SOURCE_PROTOCOL_VERSION =
  "asterion.capability-source/v1" as const;
export const CAPABILITY_LOCK_PROTOCOL_VERSION =
  "asterion.capability-lock/v1" as const;

export type ProtocolVersion = typeof RUNTIME_PROTOCOL_VERSION;
export type CapabilityProtocolVersion = typeof CAPABILITY_PROTOCOL_VERSION;
export type ApplicationAssemblyProtocolVersion =
  typeof APPLICATION_ASSEMBLY_PROTOCOL_VERSION;
export type CapabilityPackageProtocolVersion =
  typeof CAPABILITY_PACKAGE_PROTOCOL_VERSION;
export type BenchmarkSuiteProtocolVersion =
  typeof BENCHMARK_SUITE_PROTOCOL_VERSION;
export type CapabilitySourceProtocolVersion =
  typeof CAPABILITY_SOURCE_PROTOCOL_VERSION;
export type CapabilityLockProtocolVersion =
  typeof CAPABILITY_LOCK_PROTOCOL_VERSION;

export interface CapabilityPackageRef {
  readonly package_id: string;
  readonly version: string;
}

export interface CapabilityRef {
  readonly capability_id: string;
  readonly version: string;
}

export interface BenchmarkSuiteRef {
  readonly suite_id: string;
  readonly version: string;
}

export interface AssemblyManifest {
  readonly protocol: ApplicationAssemblyProtocolVersion;
  readonly application_id: string;
  readonly version: string;
  readonly runtime_id: string;
  readonly capability_packages: readonly CapabilityPackageRef[];
  readonly capabilities: readonly CapabilityRef[];
  readonly host_capabilities: readonly string[];
  readonly host_policies: readonly string[];
  readonly host_events: readonly string[];
  readonly host_artifacts: readonly string[];
}
export type CapabilityKind =
  | "capability"
  | "workflow"
  | "policy"
  | "memory"
  | "observability"
  | "evaluation"
  | "research";

export interface CapabilityManifest {
  readonly protocol: CapabilityProtocolVersion;
  readonly capability_id: string;
  readonly version: string;
  readonly kind: CapabilityKind;
  readonly provides_capabilities: readonly string[];
  readonly requires_capabilities: readonly string[];
  readonly requires_policies: readonly string[];
  readonly emits_events: readonly string[];
  readonly consumes_events: readonly string[];
  readonly produces_artifacts: readonly string[];
  readonly consumes_artifacts: readonly string[];
}

export interface CapabilityPackageManifest {
  readonly protocol: CapabilityPackageProtocolVersion;
  readonly package_id: string;
  readonly version: string;
  readonly capabilities: readonly CapabilityRef[];
  readonly benchmark_suites: readonly BenchmarkSuiteRef[];
  readonly resources: readonly {
    readonly resource_id: string;
    readonly media_type: string;
    readonly sha256: string;
  }[];
}

export interface BenchmarkTaskManifest {
  readonly task_id: string;
  readonly capability: CapabilityRef;
  readonly binding_id: string;
  readonly metric_contract_id: string;
  readonly result_contract_id: string;
  readonly note: string;
}

export interface BenchmarkSuiteManifest {
  readonly protocol: BenchmarkSuiteProtocolVersion;
  readonly suite_id: string;
  readonly version: string;
  readonly owner_package: CapabilityPackageRef;
  readonly tasks: readonly BenchmarkTaskManifest[];
  readonly artifact_media_types: readonly string[];
  readonly default_case_limit: number;
  readonly default_concurrency: number;
}

export type CapabilitySourceKind =
  | "archive"
  | "builtin"
  | "local-directory"
  | "python-distribution";

export interface CapabilitySourceDeclaration {
  readonly protocol: CapabilitySourceProtocolVersion;
  readonly source_id: string;
  readonly kind: CapabilitySourceKind;
  readonly package_ref: CapabilityPackageRef;
  readonly payload_sha256: string | null;
}

export interface CapabilitySourceLockEntry {
  readonly package_ref: CapabilityPackageRef;
  readonly payload_sha256: string;
  readonly source_id: string;
}

export interface CapabilitySourceLock {
  readonly protocol: CapabilityLockProtocolVersion;
  readonly entries: readonly CapabilitySourceLockEntry[];
}

export interface RuntimeManifest {
  readonly protocol: ProtocolVersion;
  readonly runtime_id: string;
  readonly capabilities: readonly string[];
}

export interface RunRequest {
  readonly protocol: ProtocolVersion;
  readonly run_id: string;
  readonly input: { readonly text: string };
  readonly requested_capabilities?: readonly string[];
  readonly deadline_ms?: number;
}

interface EventBase<T extends string, P> {
  readonly protocol: ProtocolVersion;
  readonly run_id: string;
  readonly sequence: number;
  readonly type: T;
  readonly payload: P;
}

export type RunEvent =
  | EventBase<"run.started", { readonly capabilities: readonly string[] }>
  | EventBase<"text.delta", { readonly text: string }>
  | EventBase<
      "tool.call",
      {
        readonly call_id: string;
        readonly name: string;
        readonly arguments: Readonly<Record<string, unknown>>;
      }
    >
  | EventBase<
      "tool.result",
      { readonly call_id: string; readonly output: unknown; readonly is_error: boolean }
    >
  | EventBase<
      "usage.reported",
      { readonly input_tokens: number; readonly output_tokens: number }
    >
  | EventBase<
      "artifact.created",
      {
        readonly artifact: {
          readonly artifact_id: string;
          readonly kind: string;
          readonly media_type: string;
          readonly uri?: string;
          readonly sha256?: string;
        };
      }
    >
  | EventBase<"run.completed", { readonly status: "completed" | "cancelled" }>
  | EventBase<"run.failed", { readonly code: string; readonly message: string }>;

export interface AgentRuntimeClient {
  readonly manifest: RuntimeManifest;
  run(
    request: RunRequest,
    options?: { readonly signal?: AbortSignal },
  ): AsyncIterable<RunEvent>;
}
