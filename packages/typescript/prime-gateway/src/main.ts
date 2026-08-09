import { readFileSync } from "node:fs";
import process from "node:process";
import readline from "node:readline/promises";
import { pathToFileURL } from "node:url";

import {
  validateControlCommand,
  validateControlEvent,
} from "@dci/agent-runtime";
import type {
  ControlCommand,
  ControlEvent,
} from "@dci/agent-runtime";

import {
  loadPrimeArtifactLock,
  verifyPrimeArtifact,
} from "./artifact-lock.js";
import {
  PrimeCheckpointManager,
} from "./checkpoint.js";
import {
  PrimeDaemonClient,
} from "./daemon-client.js";
import {
  GatewayDurableStore,
} from "./durable-store.js";
import {
  PrimeGateway,
  PrimeGatewayError,
} from "./gateway.js";
import type {
  PrimeGatewayPrivateInputs,
} from "./gateway.js";
import {
  PrimeSession,
} from "./prime-session.js";
import {
  PrivateValueStore,
} from "./private-store.js";

export const PRIME_GATEWAY_IPC_PROTOCOL = "asterion.prime-gateway-ipc/v1";

type SidecarEnvelopeType = "command.accept" | "events.stream";

export interface PrimeGatewaySidecarOptions {
  readonly gateway: {
    accept(command: ControlCommand): Promise<void>;
    eventsAfterCursor(cursor: { readonly generation: number; readonly sequence: number }): readonly ControlEvent[];
    close(): Promise<void>;
  };
  readonly privateValues: Pick<
    PrivateValueStore,
    "bindInputReference" | "readBoundInputReference"
  >;
}

interface PrimeSidecarDescriptor {
  readonly agentDir: string;
  readonly artifactLockPath: string;
  readonly authorityId: string;
  readonly expectedRuntimeBuildId: string;
  readonly gatewayRoot: string;
  readonly generation: number;
  readonly maxContinuations: number;
  readonly maxControllerTokens: number;
  readonly maxTurns: number;
  readonly model: string;
  readonly primeSocketPath: string;
  readonly primeSourceRoot: string;
  readonly provider: string;
  readonly sessionDir: string;
  readonly sessionId: string;
  readonly skillPath: string;
  readonly timeoutMs: number;
  readonly workspace: string;
}

interface SidecarEnvelope {
  readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
  readonly id: string;
  readonly type: SidecarEnvelopeType;
  readonly command?: unknown;
  readonly private?: unknown;
  readonly cursor?: unknown;
}

type SidecarResponse =
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "command.accepted";
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "events.batch";
    readonly events: readonly ControlEvent[];
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "error";
    readonly code: "prime-gateway-sidecar-failed";
  };

const REQUEST_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const MAX_PRIVATE_TEXT_BYTES = 1024 * 1024;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return (
    actual.length === sortedExpected.length &&
    actual.every((key, index) => key === sortedExpected[index])
  );
}

function validPrivateText(value: unknown): value is string {
  return (
    typeof value === "string" &&
    Buffer.byteLength(value, "utf8") <= MAX_PRIVATE_TEXT_BYTES
  );
}

function validText(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function validateDescriptor(value: unknown): PrimeSidecarDescriptor {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "agentDir",
      "artifactLockPath",
      "authorityId",
      "expectedRuntimeBuildId",
      "gatewayRoot",
      "generation",
      "maxContinuations",
      "maxControllerTokens",
      "maxTurns",
      "model",
      "primeSocketPath",
      "primeSourceRoot",
      "provider",
      "sessionDir",
      "sessionId",
      "skillPath",
      "timeoutMs",
      "workspace",
    ]) ||
    ![
      value.agentDir,
      value.artifactLockPath,
      value.authorityId,
      value.expectedRuntimeBuildId,
      value.gatewayRoot,
      value.model,
      value.primeSocketPath,
      value.primeSourceRoot,
      value.provider,
      value.sessionDir,
      value.sessionId,
      value.skillPath,
      value.workspace,
    ].every(validText) ||
    !positiveInteger(value.generation) ||
    !positiveInteger(value.maxContinuations) ||
    !positiveInteger(value.maxControllerTokens) ||
    !positiveInteger(value.maxTurns) ||
    !positiveInteger(value.timeoutMs)
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze(value as unknown as PrimeSidecarDescriptor);
}

function validateEnvelope(value: unknown): SidecarEnvelope {
  if (
    !isRecord(value) ||
    value.protocol !== PRIME_GATEWAY_IPC_PROTOCOL ||
    typeof value.id !== "string" ||
    !REQUEST_ID.test(value.id) ||
    (value.type !== "command.accept" && value.type !== "events.stream")
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "command.accept" &&
    !hasExactKeys(value, ["protocol", "id", "type", "command", "private"])
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "events.stream" &&
    !hasExactKeys(value, ["protocol", "id", "type", "cursor"])
  ) {
    throw new PrimeGatewayError();
  }
  return value as unknown as SidecarEnvelope;
}

function validateCursor(value: unknown): Readonly<{ generation: number; sequence: number }> | null {
  if (value === null) {
    return null;
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["generation", "sequence"]) ||
    !Number.isSafeInteger(value.generation) ||
    Number(value.generation) < 1 ||
    !Number.isSafeInteger(value.sequence) ||
    Number(value.sequence) < 0
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({
    generation: Number(value.generation),
    sequence: Number(value.sequence),
  });
}

export class PrimeGatewaySidecar {
  constructor(private readonly options: PrimeGatewaySidecarOptions) {}

  async handleEnvelope(value: unknown): Promise<SidecarResponse> {
    let envelope: SidecarEnvelope;
    try {
      envelope = validateEnvelope(value);
      if (envelope.type === "command.accept") {
        await this.accept(envelope);
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "command.accepted",
        });
      }
      return Object.freeze({
        protocol: PRIME_GATEWAY_IPC_PROTOCOL,
        id: envelope.id,
        type: "events.batch",
        events: this.events(envelope),
      });
    } catch {
      const id = isRecord(value) && typeof value.id === "string" && REQUEST_ID.test(value.id)
        ? value.id
        : "request-invalid";
      return Object.freeze({
        protocol: PRIME_GATEWAY_IPC_PROTOCOL,
        id,
        type: "error",
        code: "prime-gateway-sidecar-failed",
      });
    }
  }

  async close(): Promise<void> {
    await this.options.gateway.close();
  }

  private async accept(envelope: SidecarEnvelope): Promise<void> {
    let command = validateControlCommand(envelope.command);
    const privateValues = envelope.private;
    if (!isRecord(privateValues)) {
      throw new PrimeGatewayError();
    }
    if (command.type === "session.create") {
      if (!hasExactKeys(privateValues, ["goal"]) || !validPrivateText(privateValues.goal)) {
        throw new PrimeGatewayError();
      }
      await this.options.privateValues.bindInputReference(
        command.command_id,
        command.payload.goal_ref,
        privateValues.goal,
      );
    } else if (command.type === "input.submit") {
      if (!hasExactKeys(privateValues, ["content"]) || !validPrivateText(privateValues.content)) {
        throw new PrimeGatewayError();
      }
      await this.options.privateValues.bindInputReference(
        command.command_id,
        command.payload.content_ref,
        privateValues.content,
      );
    } else if (!hasExactKeys(privateValues, [])) {
      throw new PrimeGatewayError();
    }
    await this.options.gateway.accept(command);
  }

  private events(envelope: SidecarEnvelope): readonly ControlEvent[] {
    const cursor = validateCursor(envelope.cursor);
    const events = this.options.gateway.eventsAfterCursor(
      cursor ?? { generation: 1, sequence: 0 },
    ).map((event) => {
      const validated = validateControlEvent(event);
      if (cursor !== null && validated.generation !== cursor.generation) {
        throw new PrimeGatewayError();
      }
      return validated;
    });
    return Object.freeze(events);
  }
}

class PrimeBoundPrivateInputs implements PrimeGatewayPrivateInputs {
  constructor(private readonly privateValues: PrivateValueStore) {}

  async readInput(reference: string): Promise<string> {
    if (reference.startsWith("private:")) {
      return this.privateValues.readInput(reference as `private:${string}`);
    }
    return this.privateValues.readBoundInputReference(reference);
  }
}

function encodeResponse(value: SidecarResponse): string {
  return `${JSON.stringify(value)}\n`;
}

function readPrivateDescriptor(): PrimeSidecarDescriptor {
  const fd = Number(process.env.ASTERION_PRIME_PRIVATE_FD);
  if (!Number.isSafeInteger(fd) || fd < 3) {
    throw new PrimeGatewayError();
  }
  try {
    return validateDescriptor(JSON.parse(readFileSync(fd, { encoding: "utf8" })));
  } catch {
    throw new PrimeGatewayError();
  }
}

async function createSidecarFromDescriptor(
  descriptor: PrimeSidecarDescriptor,
): Promise<PrimeGatewaySidecar> {
  const transport = new PrimeDaemonClient({
    clientId: `asterion-${descriptor.sessionId}`,
    connectTimeoutMs: descriptor.timeoutMs,
    requestTimeoutMs: descriptor.timeoutMs,
  });
  await transport.connect(descriptor.primeSocketPath);
  const store = await GatewayDurableStore.open(
    descriptor.gatewayRoot,
    descriptor.sessionId,
  );
  const privateValues = await PrivateValueStore.open(descriptor.gatewayRoot);
  const boundPrivateInputs = new PrimeBoundPrivateInputs(privateValues);
  const lock = await loadPrimeArtifactLock(pathToFileURL(descriptor.artifactLockPath));
  const artifactEvidence = await verifyPrimeArtifact(descriptor.primeSourceRoot, lock);
  let checkpointManager: PrimeCheckpointManager | undefined;

  const gateway = await PrimeGateway.open({
    sessionId: descriptor.sessionId,
    generation: descriptor.generation,
    authorityId: descriptor.authorityId,
    store,
    privateValues: boundPrivateInputs,
    async createSession(goal, bindIdentity) {
      return PrimeSession.create({
        transport,
        sessionId: descriptor.sessionId,
        privateConfig: {
          workspace: descriptor.workspace,
          agentDir: descriptor.agentDir,
          sessionDir: descriptor.sessionDir,
          provider: descriptor.provider,
          model: descriptor.model,
          skillPath: descriptor.skillPath,
          goal,
          maxContinuations: descriptor.maxContinuations,
          maxTurns: descriptor.maxTurns,
          maxControllerTokens: descriptor.maxControllerTokens,
          timeoutMs: descriptor.timeoutMs,
        },
        bindIdentity,
      });
    },
    restoreSession(identity, onRecovered) {
      const session = PrimeSession.restore({
        transport,
        sessionId: descriptor.sessionId,
        activeSessionId: identity.activeSessionId,
        transcriptSessionId: identity.transcriptSessionId,
      });
      return (async () => {
        await onRecovered({
          transport,
          primeCursor: store.snapshot().primeCursor ?? {
            generation: transport.hello?.supervisorGeneration ?? identity.supervisorGeneration,
            sequence: 0,
          },
          transcriptSessionId: identity.transcriptSessionId,
          supervisorGeneration: transport.hello?.supervisorGeneration ?? identity.supervisorGeneration,
          sessionStatus: "running",
        });
        return session;
      })();
    },
    async createCheckpoint(checkpointId, coveredSequence, onRecovered) {
      const identity = store.snapshot().primeIdentity;
      const cursor = store.snapshot().primeCursor;
      if (identity === undefined || cursor === undefined) {
        throw new PrimeGatewayError();
      }
      checkpointManager ??= await PrimeCheckpointManager.open({
        sessionId: descriptor.sessionId,
        asterionGeneration: descriptor.generation,
        activeSessionId: identity.activeSessionId,
        transcriptSessionId: identity.transcriptSessionId,
        artifactEvidence,
        expectedRuntimeBuildId: descriptor.expectedRuntimeBuildId,
        privateValues,
        transport,
        runtime: {
          async stop() {
            transport.close();
          },
          async relaunch() {
            const relaunched = new PrimeDaemonClient({
              clientId: `asterion-${descriptor.sessionId}-checkpoint`,
              connectTimeoutMs: descriptor.timeoutMs,
              requestTimeoutMs: descriptor.timeoutMs,
            });
            await relaunched.connect(descriptor.primeSocketPath);
            return relaunched;
          },
        },
        primeCursor: cursor,
      });
      return checkpointManager.create(checkpointId, coveredSequence, onRecovered);
    },
  });

  return new PrimeGatewaySidecar({
    privateValues,
    gateway: {
      accept: (command) => gateway.accept(command),
      eventsAfterCursor: (cursor) =>
        store.eventsAfterCursor(cursor).map((receipt) => receipt.event),
      close: async () => {
        await gateway.close();
        transport.close();
      },
    },
  });
}

async function run(): Promise<void> {
  const descriptor = readPrivateDescriptor();
  const sidecar = await createSidecarFromDescriptor(descriptor);
  const rl = readline.createInterface({
    input: process.stdin,
    crlfDelay: Infinity,
  });
  try {
    for await (const line of rl) {
      let parsed: unknown;
      try {
        parsed = JSON.parse(line);
      } catch {
        parsed = {};
      }
      process.stdout.write(encodeResponse(await sidecar.handleEnvelope(parsed)));
    }
  } finally {
    await sidecar.close();
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  run()
    .catch(() => {
      process.exitCode = 1;
    });
}
