import { createConnection, type Socket } from "node:net";

import {
  MAX_DAEMON_LINE_BYTES,
  PrimeDaemonCompatibilityError,
  PrimeDaemonProtocolError,
  assertPrimeDaemonCompatible,
  decodePrimeDaemonLine,
  encodePrimeDaemonCommand,
} from "./daemon-wire.js";
import type {
  PrimeDaemonCommand,
  PrimeDaemonHello,
  PrimeDaemonOutbound,
  PrimeDaemonResponse,
} from "./daemon-wire.js";

export { PrimeDaemonCompatibilityError, PrimeDaemonProtocolError };

export class PrimeDaemonTimeoutError extends Error {
  constructor(kind: "handshake" | "request") {
    super(
      kind === "handshake"
        ? "Prime daemon handshake timed out"
        : "Prime daemon request timed out",
    );
    this.name = "PrimeDaemonTimeoutError";
  }
}

export class PrimeDaemonUncertainError extends Error {
  constructor(readonly commandId: string) {
    super("Prime daemon mutation result is uncertain");
    this.name = "PrimeDaemonUncertainError";
  }
}

export class PrimeDaemonConnectionError extends Error {
  constructor(message = "Prime daemon connection failed") {
    super(message);
    this.name = "PrimeDaemonConnectionError";
  }
}

export class PrimeDaemonClosedError extends Error {
  constructor() {
    super("Prime daemon client is closed");
    this.name = "PrimeDaemonClosedError";
  }
}

export interface PrimeDaemonClientOptions {
  readonly clientId: string;
  readonly connectTimeoutMs?: number;
  readonly requestTimeoutMs?: number;
}

export type PrimeDaemonListener = (outbound: PrimeDaemonOutbound) => void;

interface PendingRequest {
  readonly commandId: string;
  readonly wireData: string;
  readonly promise: Promise<PrimeDaemonResponse>;
  readonly resolve: (response: PrimeDaemonResponse) => void;
  readonly reject: (error: Error) => void;
  readonly timeoutMs: number;
  readonly deferAcknowledgement: boolean;
  timeout: ReturnType<typeof setTimeout> | undefined;
  awaitingReconnect: boolean;
}

export interface PrimeDaemonDeferredResponse {
  readonly response: PrimeDaemonResponse;
  readonly acknowledge: () => void;
}

interface TransportState {
  readonly socket: Socket;
  buffer: Buffer;
  active: boolean;
  helloReceived: boolean;
  handshakeSettled: boolean;
  handshakeTimer: ReturnType<typeof setTimeout>;
  readonly resolveHandshake: () => void;
  readonly rejectHandshake: (error: Error) => void;
}

const DEFAULT_CONNECT_TIMEOUT_MS = 3_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;

function positiveMilliseconds(value: number | undefined, fallback: number): number {
  return Number.isSafeInteger(value) && Number(value) > 0 ? Number(value) : fallback;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export class PrimeDaemonClient {
  private readonly clientId: string;
  private readonly connectTimeoutMs: number;
  private readonly requestTimeoutMs: number;
  private readonly listeners = new Set<PrimeDaemonListener>();
  private readonly pending = new Map<string, PendingRequest>();
  private readonly deferredAcknowledgements = new Set<string>();
  private transport: TransportState | undefined;
  private socketPath: string | undefined;
  private currentHello: PrimeDaemonHello | undefined;
  private reconnectPromise: Promise<void> | undefined;
  private closed = false;
  private acknowledgementSequence = 0;

  constructor(options: PrimeDaemonClientOptions) {
    if (typeof options.clientId !== "string" || options.clientId.length === 0) {
      throw new PrimeDaemonProtocolError();
    }
    this.clientId = options.clientId;
    this.connectTimeoutMs = positiveMilliseconds(
      options.connectTimeoutMs,
      DEFAULT_CONNECT_TIMEOUT_MS,
    );
    this.requestTimeoutMs = positiveMilliseconds(
      options.requestTimeoutMs,
      DEFAULT_REQUEST_TIMEOUT_MS,
    );
  }

  get hello(): PrimeDaemonHello | undefined {
    return this.currentHello;
  }

  get isConnected(): boolean {
    return (
      this.transport?.active === true &&
      this.transport.helloReceived &&
      !this.transport.socket.destroyed
    );
  }

  async connect(socketPath: string): Promise<void> {
    this.assertOpen();
    if (this.transport?.active || this.socketPath !== undefined) {
      throw new PrimeDaemonConnectionError("Prime daemon client is already bound");
    }
    if (socketPath.length === 0) {
      throw new PrimeDaemonConnectionError();
    }
    this.socketPath = socketPath;
    await this.openTransport();
  }

  async reconnect(): Promise<void> {
    this.assertOpen();
    if (this.socketPath === undefined) {
      throw new PrimeDaemonConnectionError();
    }
    if (this.reconnectPromise !== undefined) {
      return this.reconnectPromise;
    }
    this.reconnectPromise = (async () => {
      const current = this.transport;
      if (current !== undefined) {
        this.stopTransport(current, new PrimeDaemonConnectionError(), false);
      }
      await this.openTransport();
      this.replayPendingRequests();
    })();
    try {
      await this.reconnectPromise;
    } finally {
      this.reconnectPromise = undefined;
    }
  }

  request(
    command: PrimeDaemonCommand,
    stableCommandId: string,
    timeoutMs = this.requestTimeoutMs,
  ): Promise<PrimeDaemonResponse> {
    return this.startRequest(command, stableCommandId, timeoutMs, false);
  }

  async requestDeferred(
    command: PrimeDaemonCommand,
    stableCommandId: string,
    timeoutMs = this.requestTimeoutMs,
  ): Promise<PrimeDaemonDeferredResponse> {
    const response = await this.startRequest(
      command,
      stableCommandId,
      timeoutMs,
      true,
    );
    let acknowledged = false;
    return Object.freeze({
      response,
      acknowledge: () => {
        if (!acknowledged && this.acknowledgeDeferred(stableCommandId)) {
          acknowledged = true;
        }
      },
    });
  }

  private startRequest(
    command: PrimeDaemonCommand,
    stableCommandId: string,
    timeoutMs: number,
    deferAcknowledgement: boolean,
  ): Promise<PrimeDaemonResponse> {
    this.assertOpen();
    const transport = this.transport;
    if (
      transport === undefined ||
      !transport.active ||
      !transport.helloReceived ||
      transport.socket.destroyed
    ) {
      throw new PrimeDaemonConnectionError("Prime daemon is not connected");
    }
    const wireData = encodePrimeDaemonCommand(
      command,
      stableCommandId,
      this.clientId,
    );
    const existing = this.pending.get(stableCommandId);
    if (existing !== undefined) {
      if (
        existing.wireData !== wireData ||
        existing.deferAcknowledgement !== deferAcknowledgement
      ) {
        throw new PrimeDaemonProtocolError();
      }
      return existing.promise;
    }
    const actualTimeoutMs = positiveMilliseconds(timeoutMs, this.requestTimeoutMs);
    let resolveRequest!: (response: PrimeDaemonResponse) => void;
    let rejectRequest!: (error: Error) => void;
    const promise = new Promise<PrimeDaemonResponse>((resolve, reject) => {
      resolveRequest = resolve;
      rejectRequest = reject;
    });
    const pending: PendingRequest = {
      commandId: stableCommandId,
      wireData,
      promise,
      resolve: resolveRequest,
      reject: rejectRequest,
      timeoutMs: actualTimeoutMs,
      deferAcknowledgement,
      timeout: undefined,
      awaitingReconnect: false,
    };
    this.pending.set(stableCommandId, pending);
    this.armRequestTimeout(pending);
    transport.socket.write(wireData);
    return promise;
  }

  subscribe(listener: PrimeDaemonListener): () => void {
    this.assertOpen();
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  close(): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    const current = this.transport;
    if (current !== undefined) {
      this.stopTransport(current, new PrimeDaemonClosedError(), true);
    }
    this.rejectAll(new PrimeDaemonClosedError());
    this.listeners.clear();
    this.currentHello = undefined;
  }

  private assertOpen(): void {
    if (this.closed) {
      throw new PrimeDaemonClosedError();
    }
  }

  private openTransport(): Promise<void> {
    const socketPath = this.socketPath;
    if (socketPath === undefined) {
      return Promise.reject(new PrimeDaemonConnectionError());
    }
    return new Promise<void>((resolve, reject) => {
      const socket = createConnection(socketPath);
      const state: TransportState = {
        socket,
        buffer: Buffer.alloc(0),
        active: true,
        helloReceived: false,
        handshakeSettled: false,
        handshakeTimer: setTimeout(() => {
          this.stopTransport(
            state,
            new PrimeDaemonTimeoutError("handshake"),
            false,
          );
        }, this.connectTimeoutMs),
        resolveHandshake: resolve,
        rejectHandshake: reject,
      };
      this.transport = state;
      this.currentHello = undefined;
      socket.on("data", (chunk: Buffer) => this.handleData(state, chunk));
      socket.once("error", () => {
        this.stopTransport(state, new PrimeDaemonConnectionError(), false);
      });
      socket.once("close", () => {
        this.stopTransport(state, new PrimeDaemonConnectionError(), false);
      });
    });
  }

  private handleData(state: TransportState, chunk: Buffer): void {
    if (!state.active) {
      return;
    }
    state.buffer = Buffer.concat([state.buffer, chunk]);
    let newline = state.buffer.indexOf(0x0a);
    while (newline !== -1) {
      if (newline > MAX_DAEMON_LINE_BYTES) {
        this.stopTransport(state, new PrimeDaemonProtocolError(), true);
        return;
      }
      const line = state.buffer.subarray(0, newline).toString("utf8");
      state.buffer = state.buffer.subarray(newline + 1);
      let outbound: PrimeDaemonOutbound;
      try {
        outbound = decodePrimeDaemonLine(line);
      } catch {
        this.stopTransport(state, new PrimeDaemonProtocolError(), true);
        return;
      }
      this.handleOutbound(state, outbound);
      if (!state.active) {
        return;
      }
      newline = state.buffer.indexOf(0x0a);
    }
    if (state.buffer.length > MAX_DAEMON_LINE_BYTES) {
      this.stopTransport(state, new PrimeDaemonProtocolError(), true);
    }
  }

  private handleOutbound(
    state: TransportState,
    outbound: PrimeDaemonOutbound,
  ): void {
    if (!state.helloReceived) {
      if (outbound.type !== "daemon_hello") {
        this.stopTransport(state, new PrimeDaemonProtocolError(), true);
        return;
      }
      try {
        assertPrimeDaemonCompatible(outbound);
      } catch {
        this.stopTransport(state, new PrimeDaemonCompatibilityError(), true);
        return;
      }
      state.helloReceived = true;
      this.currentHello = outbound;
      this.settleHandshake(state);
      return;
    }
    if (outbound.type === "daemon_hello") {
      this.stopTransport(state, new PrimeDaemonProtocolError(), true);
      return;
    }
    if (outbound.type === "response") {
      const pending = this.pending.get(outbound.id);
      if (pending !== undefined) {
        this.pending.delete(outbound.id);
        this.clearRequestTimeout(pending);
        const uncertain = this.isUncertainResult(outbound, outbound.id);
        if (uncertain || !pending.deferAcknowledgement) {
          this.acknowledgeResult(state, outbound.id);
        } else {
          this.deferredAcknowledgements.add(outbound.id);
        }
        if (uncertain) {
          pending.reject(new PrimeDaemonUncertainError(outbound.id));
        } else {
          pending.resolve(outbound);
        }
        return;
      }
    }
    for (const listener of this.listeners) {
      try {
        listener(outbound);
      } catch {
        // Listener isolation is part of the transport boundary.
      }
    }
  }

  private settleHandshake(state: TransportState): void {
    if (state.handshakeSettled) {
      return;
    }
    state.handshakeSettled = true;
    clearTimeout(state.handshakeTimer);
    state.resolveHandshake();
  }

  private stopTransport(
    state: TransportState,
    error: Error,
    rejectPending: boolean,
  ): void {
    if (!state.active) {
      return;
    }
    state.active = false;
    clearTimeout(state.handshakeTimer);
    state.socket.removeAllListeners();
    state.socket.destroy();
    if (this.transport === state) {
      this.transport = undefined;
      this.currentHello = undefined;
    }
    if (!state.handshakeSettled) {
      state.handshakeSettled = true;
      state.rejectHandshake(error);
    }
    if (rejectPending) {
      this.rejectAll(error);
    } else {
      this.suspendPendingRequests();
    }
  }

  private suspendPendingRequests(): void {
    for (const pending of this.pending.values()) {
      this.clearRequestTimeout(pending);
      pending.awaitingReconnect = true;
    }
  }

  private replayPendingRequests(): void {
    const state = this.transport;
    if (
      state === undefined ||
      !state.active ||
      !state.helloReceived ||
      state.socket.destroyed
    ) {
      throw new PrimeDaemonConnectionError();
    }
    for (const pending of this.pending.values()) {
      if (!pending.awaitingReconnect) {
        continue;
      }
      pending.awaitingReconnect = false;
      this.armRequestTimeout(pending);
      state.socket.write(pending.wireData);
    }
  }

  private armRequestTimeout(pending: PendingRequest): void {
    this.clearRequestTimeout(pending);
    pending.timeout = setTimeout(() => {
      if (this.pending.delete(pending.commandId)) {
        pending.reject(new PrimeDaemonTimeoutError("request"));
      }
    }, pending.timeoutMs);
  }

  private clearRequestTimeout(pending: PendingRequest): void {
    if (pending.timeout !== undefined) {
      clearTimeout(pending.timeout);
      pending.timeout = undefined;
    }
  }

  private rejectAll(error: Error): void {
    for (const pending of this.pending.values()) {
      this.clearRequestTimeout(pending);
      pending.reject(error);
    }
    this.pending.clear();
  }

  private acknowledgeResult(state: TransportState, commandId: string): void {
    if (!state.active || state.socket.destroyed) {
      return;
    }
    const acknowledgementId = `asterion-ack-${++this.acknowledgementSequence}`;
    const wireData = encodePrimeDaemonCommand(
      { type: "ack_result", commandId },
      acknowledgementId,
      this.clientId,
    );
    state.socket.write(wireData);
  }

  private acknowledgeDeferred(commandId: string): boolean {
    if (!this.deferredAcknowledgements.has(commandId)) {
      return false;
    }
    const state = this.transport;
    if (
      state === undefined ||
      !state.active ||
      !state.helloReceived ||
      state.socket.destroyed
    ) {
      return false;
    }
    this.acknowledgeResult(state, commandId);
    this.deferredAcknowledgements.delete(commandId);
    return true;
  }

  private isUncertainResult(
    response: PrimeDaemonResponse,
    commandId: string,
  ): boolean {
    if (response.success || !isRecord(response.errorInfo)) {
      return false;
    }
    return (
      response.errorInfo.code === "command_result_uncertain" &&
      response.errorInfo.clientId === this.clientId &&
      response.errorInfo.commandId === commandId
    );
  }
}
