export const PROTOCOL_VERSION = "dci.agent-runtime/v1" as const;
export const PACKAGE_PROTOCOL_VERSION = "dci.package/v1" as const;
export const ASSEMBLY_PROTOCOL_VERSION = "dci.assembly/v1" as const;

export type ProtocolVersion = typeof PROTOCOL_VERSION;
export type PackageProtocolVersion = typeof PACKAGE_PROTOCOL_VERSION;
export type AssemblyProtocolVersion = typeof ASSEMBLY_PROTOCOL_VERSION;

export interface AssemblyManifest {
  readonly protocol: AssemblyProtocolVersion;
  readonly application_id: string;
  readonly version: string;
  readonly runtime_id: string;
  readonly packages: readonly {
    readonly package_id: string;
    readonly version: string;
  }[];
  readonly host_capabilities: readonly string[];
  readonly host_policies: readonly string[];
  readonly host_events: readonly string[];
  readonly host_artifacts: readonly string[];
}
export type PackageKind =
  | "capability"
  | "workflow"
  | "policy"
  | "memory"
  | "observability"
  | "evaluation";

export interface PackageManifest {
  readonly protocol: PackageProtocolVersion;
  readonly package_id: string;
  readonly version: string;
  readonly kind: PackageKind;
  readonly provides_capabilities: readonly string[];
  readonly requires_capabilities: readonly string[];
  readonly requires_policies: readonly string[];
  readonly emits_events: readonly string[];
  readonly consumes_events: readonly string[];
  readonly produces_artifacts: readonly string[];
  readonly consumes_artifacts: readonly string[];
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
