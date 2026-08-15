export const PRIME_DAEMON_PROTOCOL_NAME = "prime-agent.daemon";
export const PRIME_DAEMON_PROTOCOL_VERSION = 7;
export const PRIME_DAEMON_SCHEMA_REVISION = 14;
export const PRIME_DAEMON_SCHEMA_ID = "protocol-7-schema-14-816309b1cd50";
export const PRIME_DAEMON_APP_VERSION = "0.7.1";
export const MAX_DAEMON_LINE_BYTES = 1024 * 1024;
export const MAX_DAEMON_JSON_DEPTH = 32;

export const REQUIRED_SERVER_CAPABILITIES = Object.freeze([
  "attach_snapshot",
  "chunked_snapshot",
  "event_sequence",
  "prompt_admission_cancellation",
  "session_input_admission",
] as const);

const SERVER_CAPABILITIES = new Set([
  "attach_snapshot",
  "event_sequence",
  "extension_ui",
  "slim_attach",
  "chunked_snapshot",
  "client_owned_sessions",
  "delete_rlm_subagent",
  "heartbeat_catalog",
  "heartbeat_management",
  "model_catalog",
  "side_question_transcript",
  "transient_bash",
  "session_input_admission",
  "prompt_admission_cancellation",
]);

const CLIENT_CAPABILITIES = new Set([
  "attach_snapshot",
  "event_sequence",
  "extension_ui",
  "slim_attach",
  "chunked_snapshot",
  "client_owned_sessions",
]);

const COMMAND_FIELDS = Object.freeze({
  list: ["type", "all", "cwd", "sessionDir", "includeClientOwned"],
  create: [
    "type",
    "sessionPath",
    "continueRecent",
    "noSession",
    "name",
    "config",
    "runtimeMetadata",
    "lifecycle",
    "env",
    "launchEnv",
  ],
  attach: [
    "type",
    "activeSessionId",
    "supportsExtensionUi",
    "clientId",
    "capabilities",
    "resumeCursor",
    "telemetryDisabled",
    "env",
    "launchEnv",
  ],
  reattach: [
    "type",
    "activeSessionId",
    "targetActiveSessionId",
    "supportsExtensionUi",
    "clientId",
    "capabilities",
    "resumeCursor",
    "telemetryDisabled",
    "env",
    "launchEnv",
  ],
  detach: ["type", "activeSessionId"],
  complete_owned_session: ["type", "activeSessionId"],
  promote_owned_session: ["type", "activeSessionId"],
  kill: ["type", "activeSessionId"],
  prompt: [
    "type",
    "activeSessionId",
    "message",
    "content",
    "images",
    "streamingBehavior",
    "queueIfBusy",
    "expandPromptTemplates",
    "source",
    "agentMessageId",
    "customMessage",
    "admissionId",
  ],
  cancel_prompt_admission: ["type", "activeSessionId", "admissionId"],
  abort: ["type", "activeSessionId"],
  abort_and_clear_queue: ["type", "activeSessionId"],
  wait_for_idle: ["type", "activeSessionId"],
  wait_for_headless_completion: ["type", "activeSessionId"],
  get_session_header: ["type", "activeSessionId"],
  get_state: ["type", "activeSessionId"],
  get_session_stats: ["type", "activeSessionId"],
  get_session_tree: ["type", "activeSessionId"],
  set_auto_compaction: ["type", "activeSessionId", "enabled"],
  compact: ["type", "activeSessionId", "customInstructions"],
  abort_compaction: ["type", "activeSessionId"],
  abort_branch_summary: ["type", "activeSessionId"],
  switch_session: ["type", "activeSessionId", "sessionPath", "cwdOverride"],
  fork: ["type", "activeSessionId", "entryId", "position"],
  navigate_tree: [
    "type",
    "activeSessionId",
    "targetId",
    "summarize",
    "customInstructions",
    "replaceInstructions",
    "label",
  ],
  set_session_name: ["type", "activeSessionId", "name"],
  rename_saved_session: ["type", "activeSessionId", "sessionPath", "name"],
  delete_saved_session: ["type", "activeSessionId", "sessionPath"],
  set_session_entry_label: [
    "type",
    "activeSessionId",
    "entryId",
    "label",
  ],
  set_rlm_max_depth: ["type", "activeSessionId", "maxDepth", "global"],
  prepare_update_restart: ["type"],
  retry_worker: ["type", "activeSessionId"],
  shutdown: ["type", "force"],
  ack_result: ["type", "commandId"],
} satisfies Record<string, readonly string[]>);

const CREATE_CONFIG_FIELDS = Object.freeze([
  "cwd", "agentDir", "sessionDir", "provider", "model", "skills",
  "autonomous", "telemetryDisabled",
]);

const EVENT_FIELDS = Object.freeze({
  daemon_closing: ["type", "reason"],
  heartbeats_changed: ["type"],
  session_event: ["type", "activeSessionId", "event", "meta"],
  side_question_event: ["type", "activeSessionId", "event"],
  session_status: ["type", "activeSessionId", "recap", "meta"],
  session_replaced: [
    "type",
    "activeSessionId",
    "state",
    "messages",
    "snapshotFollows",
    "meta",
  ],
  session_resynced: ["type", "activeSessionId", "snapshot", "meta"],
  session_attached: [
    "type",
    "activeSessionId",
    "state",
    "messages",
    "snapshot",
    "replay",
    "lastEventSequence",
  ],
  session_snapshot_begin: [
    "type",
    "activeSessionId",
    "snapshotId",
    "snapshot",
    "messageCount",
    "targetChunkBytes",
    "purpose",
  ],
  session_snapshot_chunk: [
    "type",
    "activeSessionId",
    "snapshotId",
    "index",
    "messages",
  ],
  session_snapshot_end: [
    "type",
    "activeSessionId",
    "snapshotId",
    "chunkCount",
    "lastEventSequence",
    "lastEventCursor",
  ],
  session_snapshot_failed: [
    "type",
    "activeSessionId",
    "snapshotId",
    "error",
  ],
  session_detached: ["type", "activeSessionId"],
  session_closed: ["type", "activeSessionId", "reason", "meta"],
  extension_ui_request: [
    "type",
    "activeSessionId",
    "id",
    "method",
    "payload",
    "meta",
  ],
  extension_error: [
    "type",
    "activeSessionId",
    "extensionPath",
    "event",
    "error",
    "meta",
  ],
} satisfies Record<string, readonly string[]>);

const EVENT_REQUIRED_FIELDS = Object.freeze({
  daemon_closing: ["reason"],
  heartbeats_changed: [],
  session_event: ["activeSessionId", "event"],
  side_question_event: ["activeSessionId", "event"],
  session_status: ["activeSessionId"],
  session_replaced: ["activeSessionId", "state", "messages"],
  session_resynced: ["activeSessionId", "snapshot"],
  session_attached: ["activeSessionId", "state", "messages"],
  session_snapshot_begin: [
    "activeSessionId",
    "snapshotId",
    "snapshot",
    "messageCount",
    "targetChunkBytes",
  ],
  session_snapshot_chunk: [
    "activeSessionId",
    "snapshotId",
    "index",
    "messages",
  ],
  session_snapshot_end: [
    "activeSessionId",
    "snapshotId",
    "chunkCount",
    "lastEventSequence",
  ],
  session_snapshot_failed: ["activeSessionId", "snapshotId", "error"],
  session_detached: ["activeSessionId"],
  session_closed: ["activeSessionId", "reason"],
  extension_ui_request: [
    "activeSessionId",
    "id",
    "method",
    "payload",
  ],
  extension_error: [
    "activeSessionId",
    "extensionPath",
    "event",
    "error",
  ],
} satisfies Record<keyof typeof EVENT_FIELDS, readonly string[]>);

const HELLO_FIELDS = Object.freeze([
  "type",
  "socketPath",
  "protocol",
  "schemaId",
  "schemaRevision",
  "appVersion",
  "runtime",
  "supervisorGeneration",
  "supervisorPid",
  "supervisorOwnerToken",
  "supervisorProcessStartId",
  "supervisorSocketPath",
  "clientId",
  "serverCapabilities",
]);

const META_FIELDS = Object.freeze([
  "id",
  "protocol",
  "activeSessionId",
  "sequence",
  "cursor",
  "emittedAt",
  "replayed",
]);

export type PrimeDaemonCursor = Readonly<{
  generation: string;
  sequence: number;
}>;

export type PrimeDaemonCommand = Readonly<
  { type: keyof typeof COMMAND_FIELDS } & Record<string, unknown>
>;

export type PrimeDaemonCommandEnvelope = Readonly<{
  type: "command";
  id: string;
  protocol: Readonly<{
    name: typeof PRIME_DAEMON_PROTOCOL_NAME;
    version: typeof PRIME_DAEMON_PROTOCOL_VERSION;
  }>;
  clientId: string;
  command: Readonly<Record<string, unknown> & { id: string; type: string }>;
}>;

export type PrimeDaemonHello = Readonly<{
  type: "daemon_hello";
  protocolVersion: number;
  schemaId?: string;
  schemaRevision?: number;
  appVersion?: string;
  runtimeBuildId?: string;
  supervisorGeneration?: string;
  clientId: string;
  serverCapabilities: readonly string[];
}>;

export type PrimeDaemonResponse =
  | Readonly<{
      id: string;
      type: "response";
      command: string;
      success: true;
      data?: unknown;
    }>
  | Readonly<{
      id: string;
      type: "response";
      command: string;
      success: false;
      errorInfo?: Readonly<{
        code: "command_result_uncertain";
        clientId: string;
        commandId: string;
      }>;
    }>;

export type PrimeDaemonEvent = Readonly<
  { type: keyof typeof EVENT_FIELDS } & Record<string, unknown>
>;

export type PrimeDaemonOutbound =
  | PrimeDaemonHello
  | PrimeDaemonResponse
  | PrimeDaemonEvent;

export class PrimeDaemonProtocolError extends Error {
  constructor() {
    super("Prime daemon protocol violation");
    this.name = "PrimeDaemonProtocolError";
  }
}

export class PrimeDaemonCompatibilityError extends Error {
  constructor() {
    super("Prime daemon is incompatible");
    this.name = "PrimeDaemonCompatibilityError";
  }
}

function protocolViolation(): never {
  throw new PrimeDaemonProtocolError();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(
  value: Record<string, unknown>,
  allowed: readonly string[],
): boolean {
  const allowedKeys = new Set(allowed);
  return Object.keys(value).every((key) => allowedKeys.has(key));
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function hasBoundedDepth(value: unknown): boolean {
  const pending: Array<Readonly<{ value: unknown; depth: number }>> = [
    { value, depth: 1 },
  ];
  while (pending.length > 0) {
    const current = pending.pop();
    if (current === undefined) {
      continue;
    }
    if (current.depth > MAX_DAEMON_JSON_DEPTH) {
      return false;
    }
    if (Array.isArray(current.value)) {
      for (const child of current.value) {
        pending.push({ value: child, depth: current.depth + 1 });
      }
    } else if (isRecord(current.value)) {
      for (const child of Object.values(current.value)) {
        pending.push({ value: child, depth: current.depth + 1 });
      }
    }
  }
  return true;
}

const IMAGE_MEDIA_TYPES = new Set([
  "image/gif",
  "image/jpeg",
  "image/png",
  "image/webp",
]);
const CANONICAL_BASE64 =
  /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u;

function validCanonicalBase64(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length % 4 !== 0 ||
    !CANONICAL_BASE64.test(value)
  ) {
    return false;
  }
  try {
    return Buffer.from(value, "base64").toString("base64") === value;
  } catch {
    return false;
  }
}

function validImageContent(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["type", "data", "mimeType"]) &&
    Object.keys(value).length === 3 &&
    value.type === "image" &&
    validCanonicalBase64(value.data) &&
    typeof value.mimeType === "string" &&
    IMAGE_MEDIA_TYPES.has(value.mimeType)
  );
}

function validPromptContent(value: unknown): boolean {
  if (!Array.isArray(value) || value.length === 0) {
    return false;
  }
  return value.every((item) => {
    if (!isRecord(item)) {
      return false;
    }
    if (item.type === "image") {
      return validImageContent(item);
    }
    return (
      item.type === "text" &&
      hasOnlyKeys(item, ["type", "text"]) &&
      Object.keys(item).length === 2 &&
      typeof item.text === "string"
    );
  });
}

function validPromptImages(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((item) => validImageContent(item))
  );
}

function validProtocol(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["name", "version"]) &&
    value.name === PRIME_DAEMON_PROTOCOL_NAME &&
    Number.isSafeInteger(value.version)
  );
}

function validCursor(value: unknown): value is PrimeDaemonCursor {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["generation", "sequence"]) &&
    nonEmptyString(value.generation) &&
    nonNegativeInteger(value.sequence)
  );
}

function validMeta(value: unknown): boolean {
  if (!isRecord(value) || !hasOnlyKeys(value, META_FIELDS)) {
    return false;
  }
  return (
    nonEmptyString(value.id) &&
    validProtocol(value.protocol) &&
    (value.activeSessionId === undefined || nonEmptyString(value.activeSessionId)) &&
    (value.sequence === undefined || nonNegativeInteger(value.sequence)) &&
    (value.cursor === undefined || validCursor(value.cursor)) &&
    nonEmptyString(value.emittedAt) &&
    (value.replayed === undefined || typeof value.replayed === "boolean")
  );
}

function deepFreeze<T>(value: T): T {
  if (
    (Array.isArray(value) || isRecord(value)) &&
    !Object.isFrozen(value)
  ) {
    for (const child of Object.values(value)) {
      deepFreeze(child);
    }
    Object.freeze(value);
  }
  return value;
}

function decodeHello(value: Record<string, unknown>): PrimeDaemonHello {
  if (
    !hasOnlyKeys(value, HELLO_FIELDS) ||
    !nonEmptyString(value.socketPath) ||
    !validProtocol(value.protocol) ||
    !nonEmptyString(value.clientId) ||
    !Array.isArray(value.serverCapabilities) ||
    value.serverCapabilities.some((item) => !nonEmptyString(item)) ||
    new Set(value.serverCapabilities).size !== value.serverCapabilities.length ||
    value.serverCapabilities.some((item) => !SERVER_CAPABILITIES.has(String(item))) ||
    (value.schemaId !== undefined && !nonEmptyString(value.schemaId)) ||
    (value.schemaRevision !== undefined && !nonNegativeInteger(value.schemaRevision)) ||
    (value.appVersion !== undefined && !nonEmptyString(value.appVersion)) ||
    (value.supervisorGeneration !== undefined &&
      !nonEmptyString(value.supervisorGeneration)) ||
    (value.supervisorPid !== undefined && !nonNegativeInteger(value.supervisorPid)) ||
    (value.supervisorOwnerToken !== undefined &&
      !nonEmptyString(value.supervisorOwnerToken)) ||
    (value.supervisorProcessStartId !== undefined &&
      !nonEmptyString(value.supervisorProcessStartId)) ||
    (value.supervisorSocketPath !== undefined &&
      !nonEmptyString(value.supervisorSocketPath))
  ) {
    protocolViolation();
  }
  const protocol = value.protocol as Record<string, unknown>;
  let runtimeBuildId: string | undefined;
  if (value.runtime !== undefined) {
    if (
      !isRecord(value.runtime) ||
      !hasOnlyKeys(value.runtime, [
        "buildId",
        "executablePath",
        "entrypointPath",
        "launcherPath",
      ]) ||
      !nonEmptyString(value.runtime.executablePath) ||
      (value.runtime.buildId !== undefined && !nonEmptyString(value.runtime.buildId)) ||
      (value.runtime.entrypointPath !== undefined &&
        !nonEmptyString(value.runtime.entrypointPath)) ||
      (value.runtime.launcherPath !== undefined &&
        !nonEmptyString(value.runtime.launcherPath))
    ) {
      protocolViolation();
    }
    runtimeBuildId = value.runtime.buildId as string | undefined;
  }
  const serverCapabilities = Object.freeze(
    [...value.serverCapabilities] as string[],
  );
  return Object.freeze({
    type: "daemon_hello",
    protocolVersion: Number(protocol.version),
    ...(typeof value.schemaId === "string" ? { schemaId: value.schemaId } : {}),
    ...(typeof value.schemaRevision === "number"
      ? { schemaRevision: value.schemaRevision }
      : {}),
    ...(typeof value.appVersion === "string"
      ? { appVersion: value.appVersion }
      : {}),
    ...(runtimeBuildId === undefined ? {} : { runtimeBuildId }),
    ...(typeof value.supervisorGeneration === "string"
      ? { supervisorGeneration: value.supervisorGeneration }
      : {}),
    clientId: value.clientId,
    serverCapabilities,
  });
}

function safeUncertainErrorInfo(
  value: unknown,
): Readonly<{
  code: "command_result_uncertain";
  clientId: string;
  commandId: string;
}> | undefined {
  if (
    !isRecord(value) ||
    value.code !== "command_result_uncertain" ||
    !hasOnlyKeys(value, ["code", "clientId", "commandId"]) ||
    Object.keys(value).length !== 3 ||
    !nonEmptyString(value.clientId) ||
    !nonEmptyString(value.commandId)
  ) {
    return undefined;
  }
  return Object.freeze({
    code: "command_result_uncertain",
    clientId: value.clientId,
    commandId: value.commandId,
  });
}

function validPrivateErrorInfo(value: unknown): boolean {
  if (!isRecord(value) || typeof value.code !== "string") {
    return false;
  }
  if (value.code === "missing_session_cwd") {
    const issue = value.issue;
    return (
      hasOnlyKeys(value, ["code", "issue"]) &&
      Object.keys(value).length === 2 &&
      isRecord(issue) &&
      hasOnlyKeys(issue, ["sessionFile", "sessionCwd", "fallbackCwd"]) &&
      nonEmptyString(issue.sessionCwd) &&
      nonEmptyString(issue.fallbackCwd) &&
      (issue.sessionFile === undefined || nonEmptyString(issue.sessionFile))
    );
  }
  if (value.code === "session_import_file_not_found") {
    return (
      hasOnlyKeys(value, ["code", "filePath"]) &&
      Object.keys(value).length === 2 &&
      nonEmptyString(value.filePath)
    );
  }
  if (value.code === "session_already_active") {
    return (
      hasOnlyKeys(value, ["code", "sessionPath", "activeSessionId"]) &&
      nonEmptyString(value.sessionPath) &&
      (value.activeSessionId === undefined ||
        nonEmptyString(value.activeSessionId))
    );
  }
  return false;
}

function decodeResponse(value: Record<string, unknown>): PrimeDaemonResponse {
  if (
    !hasOnlyKeys(value, [
      "id",
      "type",
      "command",
      "success",
      "data",
      "error",
      "errorInfo",
    ]) ||
    !nonEmptyString(value.id) ||
    !nonEmptyString(value.command) ||
    !Object.hasOwn(COMMAND_FIELDS, value.command) ||
    typeof value.success !== "boolean"
  ) {
    protocolViolation();
  }
  if (value.success) {
    if (value.error !== undefined || value.errorInfo !== undefined) {
      protocolViolation();
    }
    return deepFreeze(value) as PrimeDaemonResponse;
  }
  if (!nonEmptyString(value.error) || value.data !== undefined) {
    protocolViolation();
  }
  const uncertain = safeUncertainErrorInfo(value.errorInfo);
  if (
    value.errorInfo !== undefined &&
    uncertain === undefined &&
    !validPrivateErrorInfo(value.errorInfo)
  ) {
    protocolViolation();
  }
  return Object.freeze({
    id: value.id,
    type: "response",
    command: value.command,
    success: false,
    ...(uncertain === undefined ? {} : { errorInfo: uncertain }),
  });
}

function decodeEvent(value: Record<string, unknown>): PrimeDaemonEvent {
  const type = value.type;
  if (
    typeof type !== "string" ||
    !Object.hasOwn(EVENT_FIELDS, type) ||
    !hasOnlyKeys(value, EVENT_FIELDS[type as keyof typeof EVENT_FIELDS])
  ) {
    protocolViolation();
  }
  const eventType = type as keyof typeof EVENT_FIELDS;
  if (
    EVENT_REQUIRED_FIELDS[eventType].some(
      (field) => !Object.hasOwn(value, field) || value[field] === undefined,
    )
  ) {
    protocolViolation();
  }
  if (
    type !== "heartbeats_changed" &&
    type !== "daemon_closing" &&
    !nonEmptyString(value.activeSessionId)
  ) {
    protocolViolation();
  }
  if (value.meta !== undefined && !validMeta(value.meta)) {
    protocolViolation();
  }
  if (
    type === "daemon_closing" &&
    value.reason !== "shutdown" &&
    value.reason !== "update"
  ) {
    protocolViolation();
  }
  return deepFreeze(value) as PrimeDaemonEvent;
}

export function decodePrimeDaemonLine(line: string): PrimeDaemonOutbound {
  if (
    Buffer.byteLength(line, "utf8") > MAX_DAEMON_LINE_BYTES ||
    line.includes("\n") ||
    line.includes("\r")
  ) {
    protocolViolation();
  }
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    protocolViolation();
  }
  if (
    !hasBoundedDepth(value) ||
    !isRecord(value) ||
    !nonEmptyString(value.type)
  ) {
    protocolViolation();
  }
  if (value.type === "daemon_hello") {
    return decodeHello(value);
  }
  if (value.type === "response") {
    return decodeResponse(value);
  }
  return decodeEvent(value);
}

export function assertPrimeDaemonCompatible(hello: PrimeDaemonHello): void {
  if (
    hello.protocolVersion !== PRIME_DAEMON_PROTOCOL_VERSION ||
    hello.schemaId !== PRIME_DAEMON_SCHEMA_ID ||
    hello.schemaRevision !== PRIME_DAEMON_SCHEMA_REVISION ||
    hello.appVersion !== PRIME_DAEMON_APP_VERSION ||
    hello.runtimeBuildId === undefined ||
    hello.supervisorGeneration === undefined ||
    REQUIRED_SERVER_CAPABILITIES.some(
      (capability) => !hello.serverCapabilities.includes(capability),
    )
  ) {
    throw new PrimeDaemonCompatibilityError();
  }
}

function validCapabilities(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.every(
      (capability) =>
        typeof capability === "string" && CLIENT_CAPABILITIES.has(capability),
    ) &&
    new Set(value).size === value.length
  );
}

function validateCommand(command: PrimeDaemonCommand): void {
  if (
    !isRecord(command) ||
    !nonEmptyString(command.type) ||
    !Object.hasOwn(COMMAND_FIELDS, command.type) ||
    !hasOnlyKeys(command, COMMAND_FIELDS[command.type as keyof typeof COMMAND_FIELDS]) ||
    "id" in command
  ) {
    protocolViolation();
  }
  const needsActiveSession = ![
    "list",
    "create",
    "detach",
    "rename_saved_session",
    "delete_saved_session",
    "prepare_update_restart",
    "shutdown",
    "ack_result",
  ].includes(command.type);
  if (
    (needsActiveSession && !nonEmptyString(command.activeSessionId)) ||
    (command.activeSessionId !== undefined && !nonEmptyString(command.activeSessionId)) ||
    (command.type === "reattach" && !nonEmptyString(command.targetActiveSessionId)) ||
    (command.type === "prompt" && !nonEmptyString(command.message)) ||
    (command.type === "prompt" &&
      command.content !== undefined &&
      !validPromptContent(command.content)) ||
    (command.type === "prompt" &&
      command.images !== undefined &&
      !validPromptImages(command.images)) ||
    (command.type === "create" &&
      command.config !== undefined &&
      !isRecord(command.config)) ||
    (command.type === "create" &&
      isRecord(command.config) &&
      !hasOnlyKeys(command.config, CREATE_CONFIG_FIELDS)) ||
    (command.type === "create" &&
      command.runtimeMetadata !== undefined &&
      !isRecord(command.runtimeMetadata)) ||
    (command.type === "cancel_prompt_admission" &&
      !nonEmptyString(command.admissionId)) ||
    (command.type === "set_rlm_max_depth" &&
      !nonNegativeInteger(command.maxDepth)) ||
    (command.type === "set_auto_compaction" && command.enabled !== false) ||
    (command.type === "ack_result" && !nonEmptyString(command.commandId)) ||
    (command.capabilities !== undefined && !validCapabilities(command.capabilities)) ||
    (command.type === "compact" &&
      command.customInstructions !== undefined &&
      typeof command.customInstructions !== "string") ||
    (command.type === "fork" &&
      (!nonEmptyString(command.entryId) ||
        (command.position !== undefined &&
          command.position !== "before" &&
          command.position !== "at"))) ||
    (command.type === "navigate_tree" &&
      (!nonEmptyString(command.targetId) ||
        (command.summarize !== undefined &&
          typeof command.summarize !== "boolean") ||
        (command.customInstructions !== undefined &&
          typeof command.customInstructions !== "string") ||
        (command.replaceInstructions !== undefined &&
          typeof command.replaceInstructions !== "boolean") ||
        (command.label !== undefined && typeof command.label !== "string"))) ||
    (["switch_session", "rename_saved_session", "delete_saved_session"].includes(
      command.type,
    ) && !nonEmptyString(command.sessionPath)) ||
    (command.type === "switch_session" &&
      command.cwdOverride !== undefined &&
      !nonEmptyString(command.cwdOverride)) ||
    (["set_session_name", "rename_saved_session"].includes(command.type) &&
      (typeof command.name !== "string" || command.name.trim().length === 0)) ||
    (command.type === "set_session_entry_label" &&
      (!nonEmptyString(command.entryId) ||
        (command.label !== undefined && typeof command.label !== "string")))
  ) {
    protocolViolation();
  }
}

export function encodePrimeDaemonCommand(
  command: PrimeDaemonCommand,
  stableCommandId: string,
  clientId: string,
): string {
  if (!nonEmptyString(stableCommandId) || !nonEmptyString(clientId)) {
    protocolViolation();
  }
  validateCommand(command);
  let line: string;
  try {
    line = `${JSON.stringify({
      type: "command",
      id: stableCommandId,
      protocol: {
        name: PRIME_DAEMON_PROTOCOL_NAME,
        version: PRIME_DAEMON_PROTOCOL_VERSION,
      },
      clientId,
      command: { id: stableCommandId, ...command },
    })}\n`;
  } catch {
    protocolViolation();
  }
  if (Buffer.byteLength(line, "utf8") > MAX_DAEMON_LINE_BYTES) {
    protocolViolation();
  }
  return line;
}

export function cursorFromPrimeDaemonOutbound(
  outbound: PrimeDaemonOutbound,
): PrimeDaemonCursor | undefined {
  if (outbound.type === "daemon_hello" || outbound.type === "response") {
    return undefined;
  }
  const meta = outbound.meta;
  const candidates = [
    isRecord(meta) ? meta.cursor : undefined,
    outbound.lastEventCursor,
  ];
  for (const candidate of candidates) {
    if (validCursor(candidate)) {
      return Object.freeze({
        generation: candidate.generation,
        sequence: candidate.sequence,
      });
    }
  }
  return undefined;
}
