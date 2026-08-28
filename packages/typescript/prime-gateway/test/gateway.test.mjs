import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, rename, rm, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";

import {
  validateControlEvent,
  validateControlEventStream,
} from "@dci/agent-runtime";
import {
  GatewayDurableStore,
  PrimeGateway,
  PrimePromptAdmissionUncertainError,
  PrivateValueStore,
} from "../dist/src/index.js";
import { canonicalJsonBytes } from "../dist/src/durable-store.js";

async function downgradeContinuationBinding(root, binding) {
  const valuePath = join(
    root,
    "private",
    "values",
    `${binding.privateRef.slice("private:".length)}.value`,
  );
  const storedBytes = await readFile(valuePath);
  const newline = storedBytes.indexOf(0x0a);
  const header = JSON.parse(storedBytes.subarray(0, newline).toString("utf8"));
  const body = JSON.parse(storedBytes.subarray(newline + 1).toString("utf8"));
  delete body.transcriptDevice;
  delete body.transcriptInode;
  body.format = "asterion.prime-private-continuation/v1";
  const legacyBody = canonicalJsonBytes(body);
  header.size = legacyBody.byteLength;
  header.digest = createHash("sha256").update(legacyBody).digest("hex");
  await writeFile(valuePath, Buffer.concat([
    canonicalJsonBytes(header),
    Buffer.from("\n"),
    legacyBody,
  ]), { mode: 0o600 });
  return {
    ...binding,
    bindingDigest: header.digest,
  };
}

function recoveryTransport(supervisorGeneration, name) {
  return {
    hello: { supervisorGeneration, name },
    async request() {
      throw new Error("not used by fake session");
    },
    async requestDeferred() {
      throw new Error("not used by fake session");
    },
    subscribe() {
      return () => undefined;
    },
    acknowledgeResult() {
      return true;
    },
  };
}

class FakePrimeSession {
  constructor(
    sessionPath = "/private/sessions/transcript-1.jsonl",
    contextBackend = undefined,
    identity = undefined,
  ) {
    this.activeSessionId = identity?.activeSessionId ?? "prime-root-1";
    this.transcriptSessionId = identity?.transcriptSessionId ?? "transcript-1";
    this.continuationId = identity?.continuationId ?? "continuation-1";
    this.sessionPath = sessionPath;
    this.supervisorGeneration = identity?.supervisorGeneration ??
      "supervisor-generation-1";
    this.calls = [];
    this.inputAcknowledgements = [];
    this.recoveries = [];
    this.checkpointAcknowledgements = [];
    this.checkpointAcknowledger = () => true;
    this.listener = undefined;
    this.pauseError = undefined;
    this.contextCalls = [];
    this.contextBackend = contextBackend ?? {
      acknowledgements: [],
      continuationResults: new Map(),
      labelResults: new Map(),
      modelResults: new Map(),
      nameResults: new Map(),
      sideEffects: [],
      treeResults: new Map(),
      forkResults: new Map(),
    };
    this.contextAcknowledgements = this.contextBackend.acknowledgements;
    this.contextSideEffects = this.contextBackend.sideEffects;
    this.contextDescription = {
      continuationId: this.continuationId,
      status: "idle",
      contextTokens: 90,
      turns: 2,
      usage: {
        controller_tokens: 135,
        application_tokens: 0,
        child_tokens: 0,
        aggregate_tokens: 135,
        cost_micros: 1234,
      },
      nameSha256: createHash("sha256").update("session-1").digest("hex"),
    };
    this.contextTree = {
      nodes: [
        { entry_id: "entry-1", parent_id: null, kind: "input", label_sha256: null, token_count: 0 },
        { entry_id: "entry-2", parent_id: "entry-1", kind: "output", label_sha256: null, token_count: 3 },
      ],
      leafId: "entry-2",
    };
    this.afterContextResult = undefined;
    this.afterInputResult = undefined;
    this.contextErrorBeforeResult = undefined;
    this.mutateSourceOnResume = false;
    this.modelOutcomeStatus = "succeeded";
    this.holdModelOperations = false;
    this.modelResolvers = [];
  }

  subscribe(listener) {
    this.listener = listener;
    return () => {
      this.listener = undefined;
    };
  }

  async submitInput(inputId, delivery, body, attachments = []) {
    this.calls.push(attachments.length === 0
      ? ["input", inputId, delivery, body]
      : ["input", inputId, delivery, body, attachments]);
    this.afterInputResult?.();
    return {
      acknowledge: () => {
        this.inputAcknowledgements.push(inputId);
        return true;
      },
    };
  }

  acknowledgeInput(inputId) {
    this.inputAcknowledgements.push(inputId);
    return true;
  }

  async pause(commandId) {
    this.calls.push(["pause", commandId]);
    if (this.pauseError !== undefined) {
      throw this.pauseError;
    }
  }

  async resume(commandId) {
    this.calls.push(["resume", commandId]);
  }

  async attach(commandId, cursor) {
    this.calls.push(["attach", commandId, cursor]);
  }

  async detach(commandId) {
    this.calls.push(["detach", commandId]);
  }

  async cancel(commandId) {
    this.calls.push(["cancel", commandId]);
  }

  async describeContext(commandId, status) {
    this.contextCalls.push(["describe", commandId, status]);
    return structuredClone(this.contextDescription);
  }

  async setContextName(commandId, name) {
    this.contextCalls.push(["name", commandId, name]);
    const stableCommandId = `session-1-context-${commandId}-set-name`;
    let result = this.contextBackend.nameResults.get(stableCommandId);
    if (result === undefined) {
      result = {
        continuationId: this.continuationId,
        nameSha256: createHash("sha256").update(name.trim()).digest("hex"),
      };
      this.contextBackend.nameResults.set(stableCommandId, result);
      this.contextBackend.sideEffects.push([stableCommandId, name]);
    }
    this.afterContextResult?.();
    return {
      result,
      acknowledge: () => {
        this.contextAcknowledgements.push(stableCommandId);
        return true;
      },
    };
  }

  acknowledgeContext(commandId) {
    this.contextAcknowledgements.push(
      `session-1-context-${commandId}-set-name`,
    );
    return true;
  }

  async setContextLabel(commandId, continuationId, entryId, label) {
    this.contextCalls.push(["label", commandId, continuationId, entryId, label]);
    if (continuationId !== this.continuationId) {
      throw new Error("wrong continuation");
    }
    const target = this.contextTree.nodes.find((node) => node.entry_id === entryId);
    if (target === undefined) {
      throw new Error("missing entry");
    }
    const stableCommandId = `session-1-context-${commandId}-label`;
    let result = this.contextBackend.labelResults.get(stableCommandId);
    if (result === undefined) {
      result = {
        continuationId,
        entryId,
        labelSha256: label === null
          ? null
          : createHash("sha256").update(label).digest("hex"),
      };
      target.label_sha256 = result.labelSha256;
      this.contextBackend.labelResults.set(stableCommandId, result);
      this.contextBackend.sideEffects.push([stableCommandId, label]);
    }
    this.afterContextResult?.();
    return {
      result,
      acknowledge: () => {
        this.contextAcknowledgements.push(stableCommandId);
        return true;
      },
    };
  }

  acknowledgeLabel(commandId) {
    this.contextAcknowledgements.push(`session-1-context-${commandId}-label`);
    return true;
  }

  async measureContextModelBaseline(commandId, continuationId, selectedEntryId) {
    this.contextCalls.push([
      "model.baseline",
      commandId,
      continuationId,
      selectedEntryId,
    ]);
    if (
      continuationId !== this.continuationId ||
      (selectedEntryId !== undefined &&
        !this.contextTree.nodes.some((node) => node.entry_id === selectedEntryId))
    ) {
      throw new Error("wrong model target");
    }
    return {
      commandId,
      continuationId,
      leafId: this.contextTree.leafId,
      contextTokens: this.contextDescription.contextTokens,
      controllerTokens: this.contextDescription.usage.controller_tokens,
      costMicros: this.contextDescription.usage.cost_micros,
    };
  }

  async compactContext(commandId, continuationId, instructions, budget, baseline) {
    return this.runFakeModelOperation(
      "session.compact",
      commandId,
      continuationId,
      instructions,
      budget,
      baseline,
    );
  }

  async summarizeContextBranch(
    commandId,
    continuationId,
    entryId,
    instructions,
    budget,
    baseline,
  ) {
    return this.runFakeModelOperation(
      "session.branch.summarize",
      commandId,
      continuationId,
      instructions,
      budget,
      baseline,
      entryId,
    );
  }

  async runFakeModelOperation(
    operation,
    commandId,
    continuationId,
    instructions,
    budget,
    baseline,
    entryId = undefined,
  ) {
    this.contextCalls.push([
      operation,
      commandId,
      continuationId,
      entryId,
      instructions,
      budget,
      baseline,
    ]);
    const purpose = operation === "session.compact" ? "compact" : "branch-summary";
    const stableCommandId = `session-1-context-${commandId}-${purpose}`;
    if (this.holdModelOperations) {
      await new Promise((resolve) => this.modelResolvers.push(resolve));
    }
    if (this.modelOutcomeStatus !== "succeeded") {
      return {
        status: this.modelOutcomeStatus,
        result: null,
        acknowledge: () => {
          this.contextAcknowledgements.push(stableCommandId);
          return true;
        },
      };
    }
    let result = this.contextBackend.modelResults.get(stableCommandId);
    if (result === undefined) {
      const usage = {
        controller_tokens: 20,
        application_tokens: 0,
        child_tokens: 0,
        aggregate_tokens: 20,
        cost_micros: 500,
      };
      if (operation === "session.compact") {
        result = {
          continuationId,
          coveredLeafId: baseline.leafId,
          beforeContextTokens: baseline.contextTokens,
          afterContextTokens: 40,
          summarySha256: createHash("sha256")
            .update("SENTINEL_PRIVATE_COMPACT_SUMMARY")
            .digest("hex"),
          usage,
        };
        this.contextTree.nodes.push({
          entry_id: "compaction-entry-1",
          parent_id: baseline.leafId,
          kind: "compaction",
          label_sha256: null,
          token_count: baseline.contextTokens,
        });
        this.contextTree.leafId = "compaction-entry-1";
        this.contextDescription.contextTokens = 40;
      } else {
        result = {
          continuationId,
          previousLeafId: baseline.leafId,
          currentLeafId: "summary-entry-1",
          summarySha256: createHash("sha256")
            .update("SENTINEL_PRIVATE_BRANCH_SUMMARY")
            .digest("hex"),
          usage,
        };
        this.contextTree.nodes.push({
          entry_id: "summary-entry-1",
          parent_id: entryId,
          kind: "summary",
          label_sha256: null,
          token_count: 0,
        });
        this.contextTree.leafId = "summary-entry-1";
        this.contextDescription.contextTokens += 20;
      }
      this.contextDescription.usage.controller_tokens += 20;
      this.contextDescription.usage.aggregate_tokens += 20;
      this.contextDescription.usage.cost_micros += 500;
      this.contextBackend.modelResults.set(stableCommandId, result);
      this.contextBackend.sideEffects.push([stableCommandId, instructions]);
    }
    this.afterContextResult?.();
    return {
      status: "succeeded",
      result,
      acknowledge: () => {
        this.contextAcknowledgements.push(stableCommandId);
        return true;
      },
    };
  }

  async abortContextModelOperation(commandId, operation) {
    this.contextCalls.push(["model.abort", commandId, operation]);
    this.modelOutcomeStatus = "cancelled";
    for (const resolve of this.modelResolvers.splice(0)) {
      resolve();
    }
  }

  acknowledgeContextModelOperation(commandId, operation) {
    const purpose = operation === "session.compact" ? "compact" : "branch-summary";
    this.contextAcknowledgements.push(`session-1-context-${commandId}-${purpose}`);
    return true;
  }

  async readContextTree(commandId, continuationId) {
    this.contextCalls.push(["tree.read", commandId, continuationId]);
    if (continuationId !== this.continuationId) {
      throw new Error("wrong continuation");
    }
    return structuredClone(this.contextTree);
  }

  async navigateContextTree(commandId, continuationId, entryId, previousLeafId) {
    this.contextCalls.push(["tree.navigate", commandId, continuationId, entryId]);
    if (continuationId !== this.continuationId) {
      throw new Error("wrong continuation");
    }
    const stableCommandId = `session-1-context-${commandId}-tree-navigate`;
    let result = this.contextBackend.treeResults.get(stableCommandId);
    if (result === undefined) {
      await writeFile(this.sessionPath, "tree navigation mutation\n", {
        flag: "a",
        mode: 0o600,
      });
      const target = this.contextTree.nodes.find((node) => node.entry_id === entryId);
      if (target === undefined) {
        throw new Error("missing entry");
      }
      this.contextTree.leafId = target.kind === "input"
        ? target.parent_id
        : target.entry_id;
      result = {
        continuationId,
        previousLeafId,
        currentLeafId: this.contextTree.leafId,
        transitionSha256: createHash("sha256")
          .update(`${continuationId}:${previousLeafId}:${this.contextTree.leafId}:${entryId}`)
          .digest("hex"),
      };
      this.contextBackend.treeResults.set(stableCommandId, result);
      this.contextBackend.sideEffects.push([stableCommandId, entryId]);
    }
    this.afterContextResult?.();
    return {
      result,
      acknowledge: () => {
        this.contextAcknowledgements.push(stableCommandId);
        return true;
      },
    };
  }

  acknowledgeTreeMutation(commandId) {
    this.contextAcknowledgements.push(
      `session-1-context-${commandId}-tree-navigate`,
    );
    return true;
  }

  async forkContext(commandId, continuationId, entryId, position) {
    return this.replaceContextByFork(
      "session.fork",
      commandId,
      continuationId,
      entryId,
      position,
    );
  }

  async cloneContext(commandId, continuationId, selectedLeafId) {
    return this.replaceContextByFork(
      "session.clone",
      commandId,
      continuationId,
      selectedLeafId,
      "at",
    );
  }

  async replaceContextByFork(
    operation,
    commandId,
    continuationId,
    entryId,
    position,
  ) {
    this.contextCalls.push([operation, commandId, continuationId, entryId, position]);
    const purpose = operation === "session.fork" ? "fork" : "clone";
    const stableCommandId = `session-1-context-${commandId}-${purpose}`;
    let replaced = this.contextBackend.forkResults.get(stableCommandId);
    if (replaced === undefined) {
      if (this.contextErrorBeforeResult !== undefined) {
        const error = this.contextErrorBeforeResult;
        this.contextErrorBeforeResult = undefined;
        throw error;
      }
      if (continuationId !== this.continuationId) {
        throw new Error("wrong continuation");
      }
      const target = this.contextTree.nodes.find((node) => node.entry_id === entryId);
      if (target === undefined) {
        throw new Error("missing entry");
      }
      if (position === "before" && target.kind !== "input") {
        throw new Error("invalid before entry");
      }
      await writeFile(this.sessionPath, "source fork shutdown mutation\n", {
        flag: "a",
        mode: 0o600,
      });
      const identityDigest = createHash("sha256")
        .update(`${operation}:${commandId}`)
        .digest("hex")
        .slice(0, 16);
      const transcriptSessionId = `transcript-${identityDigest}`;
      const sessionPath = join(dirname(this.sessionPath), `${transcriptSessionId}.jsonl`);
      await writeFile(sessionPath, "private fork transcript\n", { mode: 0o600 });
      const newContinuationId = `continuation-${identityDigest}`;
      replaced = {
        locator: {
          continuationId: newContinuationId,
          activeSessionId: this.activeSessionId,
          transcriptSessionId,
          supervisorGeneration: this.supervisorGeneration,
          sessionPath,
        },
        result: {
          sourceContinuationId: continuationId,
          newContinuationId,
          activeLeafId: position === "before" ? target.parent_id : entryId,
          transitionSha256: createHash("sha256")
            .update(`${operation}:${continuationId}:${newContinuationId}:${entryId}:${position}`)
            .digest("hex"),
        },
      };
      this.contextBackend.forkResults.set(stableCommandId, replaced);
      this.contextBackend.sideEffects.push([stableCommandId, entryId]);
    }
    this.afterContextResult?.();
    return {
      ...structuredClone(replaced),
      acknowledge: () => {
        this.contextAcknowledgements.push(stableCommandId);
        return true;
      },
    };
  }

  acknowledgeForkClone(commandId, operation) {
    const purpose = operation === "session.fork" ? "fork" : "clone";
    this.contextAcknowledgements.push(
      `session-1-context-${commandId}-${purpose}`,
    );
    return true;
  }

  async resumeContinuation(commandId, target) {
    this.contextCalls.push(["continuation.resume", commandId, target.continuationId]);
    if (this.contextErrorBeforeResult !== undefined) {
      const error = this.contextErrorBeforeResult;
      this.contextErrorBeforeResult = undefined;
      throw error;
    }
    const stableCommandId = `session-1-context-${commandId}-resume`;
    let resumed = this.contextBackend.continuationResults.get(stableCommandId);
    if (resumed === undefined) {
      if (this.mutateSourceOnResume) {
        await writeFile(this.sessionPath, "source shutdown mutation\n", {
          flag: "a",
          mode: 0o600,
        });
      }
      resumed = {
        locator: structuredClone(target),
        result: {
          previousContinuationId: this.continuationId,
          currentContinuationId: target.continuationId,
          transitionSha256: createHash("sha256")
            .update(`${this.continuationId}:${target.continuationId}:${commandId}`)
            .digest("hex"),
        },
      };
      this.contextBackend.continuationResults.set(stableCommandId, resumed);
      this.contextBackend.sideEffects.push([stableCommandId, target.continuationId]);
    }
    this.afterContextResult?.();
    return {
      ...resumed,
      acknowledge: () => {
        this.contextAcknowledgements.push(stableCommandId);
        return true;
      },
    };
  }

  async deleteContinuation(commandId, target) {
    this.contextCalls.push(["continuation.delete", commandId, target.continuationId]);
    if (this.contextErrorBeforeResult !== undefined) {
      const error = this.contextErrorBeforeResult;
      this.contextErrorBeforeResult = undefined;
      throw error;
    }
    if (target.continuationId === this.continuationId) {
      throw new Error("active continuation");
    }
    const stableCommandId = `session-1-context-${commandId}-delete`;
    let deleted = this.contextBackend.continuationResults.get(stableCommandId);
    if (deleted === undefined) {
      await unlink(target.sessionPath);
      deleted = {
        result: {
          continuationId: target.continuationId,
          deletionSha256: createHash("sha256")
            .update(`${target.continuationId}:${commandId}`)
            .digest("hex"),
        },
      };
      this.contextBackend.continuationResults.set(stableCommandId, deleted);
      this.contextBackend.sideEffects.push([stableCommandId, target.continuationId]);
    }
    this.afterContextResult?.();
    return {
      ...deleted,
      acknowledge: () => {
        this.contextAcknowledgements.push(stableCommandId);
        return true;
      },
    };
  }

  adoptContinuation(target) {
    this.continuationId = target.continuationId;
    this.transcriptSessionId = target.transcriptSessionId;
    this.sessionPath = target.sessionPath;
    this.contextDescription.continuationId = target.continuationId;
  }

  acknowledgeContinuation(commandId, operation) {
    const purpose = operation === "session.continuation.resume"
      ? "resume"
      : "delete";
    this.contextAcknowledgements.push(
      `session-1-context-${commandId}-${purpose}`,
    );
    return true;
  }

  adoptRecovery(recovery) {
    this.recoveries.push(recovery);
    this.supervisorGeneration = recovery.supervisorGeneration;
  }

  acknowledgeCheckpoint(checkpointId) {
    this.checkpointAcknowledgements.push(checkpointId);
    return this.checkpointAcknowledger(checkpointId);
  }

  emit(outbound) {
    this.listener?.(outbound);
  }
}

async function fixture({
  checkpointAckFailures = 0,
  clientObservations = false,
  ecosystemAdapter = undefined,
  failCheckpointEvent = false,
} = {}) {
  const parent = await mkdtemp(join(tmpdir(), "asterion-prime-gateway-"));
  const root = join(parent, "gateway");
  const sessionRoot = join(parent, "sessions");
  const sessionPath = join(sessionRoot, "transcript-1.jsonl");
  await mkdir(sessionRoot, { mode: 0o700 });
  await writeFile(sessionPath, "private transcript\n", { mode: 0o600 });
  let failNextWrite = false;
  const store = await GatewayDurableStore.open(root, "session-1", {
    faultInjector(stage) {
      if (failNextWrite && stage === "before_write") {
        failNextWrite = false;
        throw new Error("SENTINEL_CHECKPOINT_EVENT_WRITE");
      }
    },
  });
  const privateValues = await PrivateValueStore.open(root, {
    continuationRoot: sessionRoot,
  });
  const resultLookups = [];
  let failAfterResultLookup = false;
  const privateResults = {
    async readBoundResultReference(commandId, actionId, sourceRef) {
      resultLookups.push([commandId, actionId, sourceRef]);
      const result = await privateValues.readBoundResultReference(
        commandId,
        actionId,
        sourceRef,
      );
      if (failAfterResultLookup) {
        failAfterResultLookup = false;
        failNextWrite = true;
      }
      return result;
    },
  };
  const session = new FakePrimeSession(sessionPath);
  const createdGoals = [];
  const checkpointAcknowledgements = [];
  const checkpointAcknowledgementAttempts = [];
  const attemptCheckpointAcknowledgement = (checkpointId) => {
    checkpointAcknowledgementAttempts.push(checkpointId);
    if (checkpointAcknowledgementAttempts.length <= checkpointAckFailures) {
      return false;
    }
    checkpointAcknowledgements.push(checkpointId);
    return true;
  };
  session.checkpointAcknowledger = attemptCheckpointAcknowledgement;
  let tick = 0;
  const gateway = await PrimeGateway.open({
    sessionId: "session-1",
    generation: 1,
    authorityId: "authority-1",
    store,
    privateValues,
    privateResults,
    ...(clientObservations ? { clientObservationValues: privateValues } : {}),
    ...(ecosystemAdapter === undefined ? {} : { ecosystem: ecosystemAdapter }),
    async createSession(goal, bindIdentity) {
      createdGoals.push(goal);
      await bindIdentity({
        activeSessionId: session.activeSessionId,
        transcriptSessionId: session.transcriptSessionId,
        supervisorGeneration: session.supervisorGeneration,
        continuationId: session.continuationId,
        sessionPath: session.sessionPath,
      });
      return session;
    },
    async createCheckpoint(checkpointId, coveredSequence, onRecovered) {
      await onRecovered({
        transport: recoveryTransport(
          "supervisor-generation-2",
          "relaunched-transport",
        ),
        primeCursor: { generation: "prime-events-2", sequence: 11 },
        transcriptSessionId: "transcript-1",
        supervisorGeneration: "supervisor-generation-2",
        sessionStatus: "running",
      });
      failNextWrite = failCheckpointEvent;
      return {
        checkpointId,
        capsuleId: "capsule-1",
        capsuleDigest: "a".repeat(64),
        controlPlaneId: "prime.gateway",
        controlPlaneVersion: "0.1.0",
        checkpointVersion: "1.0.0",
        coveredSequence,
        storageRef: "private:capsule-1",
        primeCursor: { generation: "prime-events-2", sequence: 11 },
        supervisorGeneration: "supervisor-generation-2",
        acknowledge() {
          return attemptCheckpointAcknowledgement(checkpointId);
        },
      };
    },
    now() {
      tick += 1;
      return `2026-08-10T03:00:${String(tick).padStart(2, "0")}Z`;
    },
  });
  return {
    parent,
    root,
    sessionRoot,
    store,
    privateValues,
    resultLookups,
    session,
    gateway,
    createdGoals,
    checkpointAcknowledgements,
    checkpointAcknowledgementAttempts,
    failNextGoalEventWrite() {
      failAfterResultLookup = true;
    },
    failNextDurableWrite() {
      failNextWrite = true;
    },
    failContextCommitAfterResult() {
      session.afterContextResult = () => {
        session.afterContextResult = undefined;
        failNextWrite = true;
      };
    },
    failNextContinuationBeforeResult() {
      session.contextErrorBeforeResult = new Error("SENTINEL_BEFORE_RESULT");
    },
    async forkToContinuation2() {
      const sourceBinding = store.activeContextBinding();
      assert.ok(sourceBinding);
      const sourceLocator = await privateValues.readContinuationLocator(
        sourceBinding,
      );
      const nextPath = join(sessionRoot, "transcript-2.jsonl");
      await writeFile(nextPath, "private transcript 2\n", { mode: 0o600 });
      const nextLocator = {
        continuationId: "continuation-2",
        activeSessionId: session.activeSessionId,
        transcriptSessionId: "transcript-2",
        supervisorGeneration: session.supervisorGeneration,
        sessionPath: nextPath,
      };
      const nextBinding = await privateValues.putContinuationLocator(nextLocator);
      const fork = contextCommand(
        "session.fork",
        {
          continuation_id: sourceLocator.continuationId,
          entry_id: "entry-1",
          position: "at",
        },
        "context-seed-fork",
      );
      await store.acceptContextCommand(fork);
      await store.prepareContextOperation(fork.command_id, sourceBinding, {
        previousLeafId: "entry-1",
        selectedEntryId: "entry-1",
      });
      await store.commitContextOperation({
        protocol: "asterion.session-context/v1",
        receipt_id: "context-seed-fork-receipt",
        command_id: fork.command_id,
        session_id: fork.session_id,
        generation: fork.generation,
        operation: fork.operation,
        status: "succeeded",
        reason_code: "session-context-succeeded",
        payload: {
          evidence_ref: null,
          result: {
            source_continuation_id: sourceLocator.continuationId,
            new_continuation_id: nextLocator.continuationId,
            active_leaf_id: null,
            transition_sha256: "a".repeat(64),
          },
        },
      }, nextBinding, sourceBinding);
      session.adoptContinuation(nextLocator);
      await store.bindPrimeIdentity({
        activeSessionId: nextLocator.activeSessionId,
        transcriptSessionId: nextLocator.transcriptSessionId,
        supervisorGeneration: nextLocator.supervisorGeneration,
      });
      return { sourceLocator, nextLocator };
    },
    async cleanup({ allowCloseFailure = false } = {}) {
      if (allowCloseFailure) {
        await gateway.close().catch(() => undefined);
      } else {
        await gateway.close();
      }
      await rm(parent, { force: true, recursive: true });
    },
  };
}

function command(type, payload, commandId) {
  return {
    protocol: "asterion.agent-control/v1",
    command_id: commandId,
    session_id: "session-1",
    authority_revision: 1,
    type,
    payload,
  };
}

function contextCommand(operation, payload, commandId) {
  return {
    protocol: "asterion.session-context/v1",
    command_id: commandId,
    session_id: "session-1",
    generation: 1,
    authority_revision: 1,
    idempotency_key: `${commandId}-once`,
    operation,
    payload,
  };
}

const MODEL_CONTEXT_BUDGET = Object.freeze({
  controller_tokens: 50,
  application_tokens: 0,
  child_tokens: 0,
  aggregate_tokens: 50,
  cost_micros: 5_000,
  deadline_ms: 30_000,
});

function eventTypes(store) {
  return store.eventsAfter(0).map(({ event }) => event.type);
}

function proposal(identity, actionId, inputRef) {
  return {
    protocol: "asterion.agent-control/v1",
    event_id: identity.eventId,
    session_id: "session-1",
    generation: 1,
    sequence: identity.sequence,
    emitted_at: identity.emittedAt,
    type: "action.proposed",
    payload: {
      action_id: actionId,
      authority_revision: 1,
      idempotency_key: `${actionId}-once`,
      kind: "application.invoke",
      target: {
        kind: "application",
        provider_id: "example.provider",
        application_id: "alpha",
        version: "1.0.0",
        runtime_id: "fake.runtime",
      },
      input_ref: inputRef,
      expected_artifacts: [],
      budget: {
        controller_tokens: 0,
        application_tokens: 10,
        child_tokens: 0,
        aggregate_tokens: 10,
        cost_micros: 100,
        deadline_ms: 1_000,
      },
      causal_parent_ids: ["goal-1"],
    },
  };
}

function goalProposal(identity, actionId, inputRef, kind) {
  return {
    ...proposal(identity, actionId, inputRef),
    payload: {
      ...proposal(identity, actionId, inputRef).payload,
      kind,
      target: { kind: "goal", goal_id: "goal-1" },
      budget: {
        controller_tokens: 0,
        application_tokens: 0,
        child_tokens: 0,
        aggregate_tokens: 0,
        cost_micros: 0,
        deadline_ms: 1_000,
      },
    },
  };
}

test("gateway persists create before one safe running prefix", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("SENTINEL_PRIVATE_GOAL");
    const create = command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create");
    await state.gateway.accept(create);
    await state.gateway.accept(structuredClone(create));

    assert.deepEqual(state.createdGoals, ["SENTINEL_PRIVATE_GOAL"]);
    assert.deepEqual(eventTypes(state.store), ["session.created", "session.running"]);
    assert.equal(state.store.snapshot().commandCount, 1);
    assert.deepEqual(state.store.snapshot().primeIdentity, {
      activeSessionId: "prime-root-1",
      transcriptSessionId: "transcript-1",
      supervisorGeneration: "supervisor-generation-1",
    });
    const initialBinding = state.store.currentContextBinding(
      state.session.continuationId,
    );
    assert.ok(initialBinding);
    assert.deepEqual(
      await state.privateValues.readContinuationLocator(initialBinding),
      {
        continuationId: "continuation-1",
        activeSessionId: "prime-root-1",
        transcriptSessionId: "transcript-1",
        supervisorGeneration: "supervisor-generation-1",
        sessionPath: state.session.sessionPath,
      },
    );
    assert.equal(JSON.stringify(state.store.snapshot()).includes("SENTINEL"), false);
    const publicGateway = JSON.stringify(state.gateway);
    assert.equal(publicGateway.includes("SENTINEL"), false);
    assert.equal(publicGateway.includes(state.root), false);
    assert.deepEqual(JSON.parse(publicGateway), {
      kind: "asterion-prime-gateway",
      session_id: "session-1",
      generation: 1,
      status: "running",
    });
  } finally {
    await state.cleanup();
  }
});

test("gateway executes native describe and name operations with closed durable replay", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));

    const describe = contextCommand("session.describe", {}, "context-describe-1");
    const described = await state.gateway.executeSessionContext(
      describe,
      async () => undefined,
    );
    assert.deepEqual(described.payload.result, {
      continuation_id: "continuation-1",
      status: "idle",
      context_tokens: 90,
      turns: 2,
      usage: {
        controller_tokens: 135,
        application_tokens: 0,
        child_tokens: 0,
        aggregate_tokens: 135,
        cost_micros: 1234,
      },
      name_sha256: createHash("sha256").update("session-1").digest("hex"),
    });
    assert.equal(described.status, "succeeded");

    state.session.contextDescription.turns = 99;
    assert.deepEqual(
      await state.gateway.executeSessionContext(
        structuredClone(describe),
        async () => undefined,
      ),
      described,
    );
    assert.deepEqual(state.session.contextCalls, [
      ["describe", "context-describe-1", "running"],
    ]);

    const nameRef = await state.privateValues.putInput(
      "SENTINEL_PRIVATE_SESSION_NAME",
    );
    const name = contextCommand(
      "session.name.set",
      { name_ref: nameRef },
      "context-name-1",
    );
    const named = await state.gateway.executeSessionContext(
      name,
      async () => undefined,
    );
    assert.deepEqual(named.payload.result, {
      continuation_id: "continuation-1",
      name_sha256: createHash("sha256")
        .update("SENTINEL_PRIVATE_SESSION_NAME")
        .digest("hex"),
    });
    assert.deepEqual(state.session.contextAcknowledgements, [
      "session-1-context-context-name-1-set-name",
    ]);
    assert.equal(
      JSON.stringify(state.store.contextOperations()).includes("SENTINEL"),
      false,
    );
    assert.equal(
      JSON.stringify(state.store.contextOperations()).includes(state.session.sessionPath),
      false,
    );
  } finally {
    await state.cleanup();
  }
});

test("gateway sets and clears exact private labels without persisting label text", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const labelRef = await state.privateValues.putInput(
      "SENTINEL_PRIVATE_CONTEXT_LABEL",
    );
    const set = await state.gateway.executeSessionContext(contextCommand(
      "session.label.set",
      {
        continuation_id: "continuation-1",
        entry_id: "entry-2",
        label_ref: labelRef,
      },
      "context-label-set",
    ), async () => undefined);
    assert.equal(
      set.payload.result.label_sha256,
      createHash("sha256").update("SENTINEL_PRIVATE_CONTEXT_LABEL").digest("hex"),
    );
    const cleared = await state.gateway.executeSessionContext(contextCommand(
      "session.label.set",
      {
        continuation_id: "continuation-1",
        entry_id: "entry-2",
        label_ref: null,
      },
      "context-label-clear",
    ), async () => undefined);
    assert.equal(cleared.payload.result.label_sha256, null);
    assert.equal(
      JSON.stringify(state.store.contextOperations()).includes("SENTINEL"),
      false,
    );
    assert.deepEqual(state.session.contextAcknowledgements, [
      "session-1-context-context-label-set-label",
      "session-1-context-context-label-clear-label",
    ]);
  } finally {
    await state.cleanup();
  }
});

test("gateway durably budgets manual compaction and branch summary with safe usage", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const compactInstructions = await state.privateValues.putInput(
      "SENTINEL_PRIVATE_COMPACT_INSTRUCTIONS",
    );
    const compact = contextCommand("session.compact", {
      continuation_id: "continuation-1",
      instructions_ref: compactInstructions,
      budget: MODEL_CONTEXT_BUDGET,
    }, "context-compact-1");
    const compacted = await state.gateway.executeSessionContext(
      compact,
      async () => undefined,
    );
    assert.deepEqual(compacted.payload.result, {
      continuation_id: "continuation-1",
      covered_leaf_id: "entry-2",
      before_context_tokens: 90,
      after_context_tokens: 40,
      summary_sha256: createHash("sha256")
        .update("SENTINEL_PRIVATE_COMPACT_SUMMARY")
        .digest("hex"),
      usage: {
        controller_tokens: 20,
        application_tokens: 0,
        child_tokens: 0,
        aggregate_tokens: 20,
        cost_micros: 500,
      },
    });
    assert.equal(
      state.store.preparedContextModelOperation(compact.command_id),
      undefined,
    );

    const summaryInstructions = await state.privateValues.putInput(
      "SENTINEL_PRIVATE_BRANCH_INSTRUCTIONS",
    );
    const summarized = await state.gateway.executeSessionContext(contextCommand(
      "session.branch.summarize",
      {
        continuation_id: "continuation-1",
        entry_id: "entry-1",
        instructions_ref: summaryInstructions,
        budget: MODEL_CONTEXT_BUDGET,
      },
      "context-summary-1",
    ), async () => undefined);
    assert.equal(summarized.payload.result.previous_leaf_id, "compaction-entry-1");
    assert.equal(summarized.payload.result.current_leaf_id, "summary-entry-1");
    assert.equal(
      summarized.payload.result.summary_sha256,
      createHash("sha256").update("SENTINEL_PRIVATE_BRANCH_SUMMARY").digest("hex"),
    );
    assert.equal(
      JSON.stringify(state.store.contextOperations()).includes("SENTINEL"),
      false,
    );
    assert.equal(
      JSON.stringify(state.store.snapshot()).includes("SENTINEL"),
      false,
    );
    assert.deepEqual(state.session.contextAcknowledgements, [
      "session-1-context-context-compact-1-compact",
      "session-1-context-context-summary-1-branch-summary",
    ]);
  } finally {
    await state.cleanup();
  }
});

test("gateway reuses the durable model baseline and stable Prime result after commit crash", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const instructionsRef = await state.privateValues.putInput(
      "SENTINEL_PRIVATE_RESTART_INSTRUCTIONS",
    );
    const compact = contextCommand("session.compact", {
      continuation_id: "continuation-1",
      instructions_ref: instructionsRef,
      budget: MODEL_CONTEXT_BUDGET,
    }, "context-compact-restart");
    state.failContextCommitAfterResult();
    await assert.rejects(
      state.gateway.executeSessionContext(compact, async () => undefined),
    );
    assert.equal(state.session.contextSideEffects.length, 1);
    assert.deepEqual(state.session.contextAcknowledgements, []);
    assert.deepEqual(
      state.store.preparedContextModelOperation(compact.command_id),
      {
        commandId: compact.command_id,
        continuationId: "continuation-1",
        leafId: "entry-2",
        contextTokens: 90,
        controllerTokens: 135,
        costMicros: 1234,
      },
    );
    await state.gateway.close().catch(() => undefined);

    const store = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession(
      state.session.sessionPath,
      state.session.contextBackend,
    );
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must restore");
      },
      async restoreSession(_identity, onRecovered) {
        await onRecovered({
          transport: recoveryTransport("supervisor-generation-1", "model-recovery"),
          primeCursor: { generation: "prime-events-1", sequence: 0 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-1",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("not used");
      },
    });
    const receipt = await reopened.executeSessionContext(
      structuredClone(compact),
      async () => undefined,
    );
    assert.equal(receipt.status, "succeeded");
    assert.equal(state.session.contextSideEffects.length, 1);
    assert.equal(
      restoredSession.contextCalls.some(([kind]) => kind === "model.baseline"),
      false,
    );
    assert.deepEqual(state.session.contextAcknowledgements, [
      "session-1-context-context-compact-restart-compact",
    ]);
  } finally {
    await reopened?.close().catch(() => undefined);
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway commits provider rejection as a definitive body-free receipt", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.modelOutcomeStatus = "rejected";
    const rejected = await state.gateway.executeSessionContext(contextCommand(
      "session.compact",
      {
        continuation_id: "continuation-1",
        instructions_ref: null,
        budget: MODEL_CONTEXT_BUDGET,
      },
      "context-compact-rejected",
    ), async () => undefined);
    assert.equal(rejected.status, "rejected");
    assert.equal(rejected.reason_code, "provider-rejected");
    assert.equal(
      JSON.stringify(state.store.contextOperations()).includes("SENTINEL"),
      false,
    );
  } finally {
    await state.cleanup();
  }
});

test("gateway rejects an unusable model budget before baseline or provider dispatch", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const rejected = await state.gateway.executeSessionContext(contextCommand(
      "session.compact",
      {
        continuation_id: "continuation-1",
        instructions_ref: null,
        budget: {
          ...MODEL_CONTEXT_BUDGET,
          controller_tokens: 0,
          aggregate_tokens: 0,
        },
      },
      "context-compact-zero-budget",
    ), async () => undefined);
    assert.equal(rejected.status, "rejected");
    assert.equal(rejected.reason_code, "provider-budget-unsupported");
    assert.equal(
      state.session.contextCalls.some(([kind]) => kind === "model.baseline"),
      false,
    );
    assert.equal(
      state.session.contextCalls.some(([kind]) => kind === "session.compact"),
      false,
    );
  } finally {
    await state.cleanup();
  }
});

test("gateway durably commits an uncertain provider outcome before acknowledgement", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.modelOutcomeStatus = "uncertain";
    const commandValue = contextCommand("session.compact", {
      continuation_id: "continuation-1",
      instructions_ref: null,
      budget: MODEL_CONTEXT_BUDGET,
    }, "context-compact-uncertain");
    const uncertain = await state.gateway.executeSessionContext(
      commandValue,
      async () => undefined,
    );
    assert.equal(uncertain.status, "uncertain");
    assert.equal(uncertain.reason_code, "provider-outcome-uncertain");
    assert.equal(uncertain.payload.result, null);
    assert.equal(
      state.store.preparedContextModelOperation(commandValue.command_id),
      undefined,
    );
    assert.deepEqual(state.session.contextAcknowledgements, [
      "session-1-context-context-compact-uncertain-compact",
    ]);
  } finally {
    await state.cleanup();
  }
});

test("gateway routes exact model cancellation and commits its terminal receipt", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.holdModelOperations = true;
    const commandValue = contextCommand("session.branch.summarize", {
      continuation_id: "continuation-1",
      entry_id: "entry-1",
      instructions_ref: null,
      budget: MODEL_CONTEXT_BUDGET,
    }, "context-summary-cancelled");
    const pending = state.gateway.executeSessionContext(
      commandValue,
      async () => undefined,
    );
    const observed = pending.then(
      (value) => ({ value }),
      (error) => ({ error }),
    );
    const waitDeadline = Date.now() + 2_000;
    while (
      state.session.modelResolvers.length === 0 &&
      Date.now() < waitDeadline
    ) {
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
    assert.equal(state.session.modelResolvers.length, 1);
    await state.gateway.cancelSessionContext(commandValue.command_id);
    const outcome = await observed;
    assert.equal("error" in outcome, false);
    if (!("value" in outcome)) throw outcome.error;
    const cancelled = outcome.value;
    assert.equal(cancelled.status, "cancelled");
    assert.equal(cancelled.reason_code, "provider-cancelled");
    assert.deepEqual(
      state.session.contextCalls.filter(([kind]) => kind === "model.abort"),
      [["model.abort", "context-summary-cancelled", "session.branch.summarize"]],
    );
    await state.gateway.settle();
    assert.equal(
      (await readdir(join(state.root, "public", "records")))
        .some((name) => name.startsWith(".asterion-")),
      false,
    );
  } finally {
    await state.cleanup();
  }
});

test("gateway admits only one transcript model operation at a time", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.holdModelOperations = true;
    const compact = contextCommand("session.compact", {
      continuation_id: "continuation-1",
      instructions_ref: null,
      budget: MODEL_CONTEXT_BUDGET,
    }, "context-compact-held");
    const pending = state.gateway.executeSessionContext(
      compact,
      async () => undefined,
    );
    const waitDeadline = Date.now() + 2_000;
    while (
      state.session.modelResolvers.length === 0 &&
      Date.now() < waitDeadline
    ) {
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
    assert.equal(state.session.modelResolvers.length, 1);

    await assert.rejects(state.gateway.executeSessionContext(contextCommand(
      "session.branch.summarize",
      {
        continuation_id: "continuation-1",
        entry_id: "entry-1",
        instructions_ref: null,
        budget: MODEL_CONTEXT_BUDGET,
      },
      "context-summary-conflict",
    ), async () => undefined));
    assert.equal(
      state.session.contextCalls.some(
        ([kind, commandId]) =>
          kind === "model.baseline" && commandId === "context-summary-conflict",
      ),
      false,
    );

    await state.gateway.cancelSessionContext(compact.command_id);
    const cancelled = await pending;
    assert.equal(cancelled.status, "cancelled");
  } finally {
    await state.cleanup();
  }
});

test("gateway rejects persisted session usage rollback before committing a second receipt", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    await state.gateway.executeSessionContext(
      contextCommand("session.describe", {}, "context-describe-first"),
      async () => undefined,
    );
    state.session.contextDescription = {
      ...state.session.contextDescription,
      turns: 1,
      usage: {
        ...state.session.contextDescription.usage,
        controller_tokens: 134,
        aggregate_tokens: 134,
      },
    };
    await assert.rejects(
      state.gateway.executeSessionContext(
        contextCommand("session.describe", {}, "context-describe-rollback"),
        async () => undefined,
      ),
    );
    assert.equal(state.store.contextOperations().length, 1);
  } finally {
    await state.cleanup();
  }
});

test("gateway replays one stable name mutation after restart between Prime result and durable receipt", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const nameRef = await state.privateValues.putInput("SENTINEL_RESTART_NAME");
    const name = contextCommand(
      "session.name.set",
      { name_ref: nameRef },
      "context-name-restart",
    );
    state.failContextCommitAfterResult();
    await assert.rejects(
      state.gateway.executeSessionContext(name, async () => undefined),
    );
    assert.equal(state.session.contextSideEffects.length, 1);
    assert.deepEqual(state.session.contextAcknowledgements, []);
    assert.equal(state.store.snapshot().contextCommandCount, 1);
    assert.equal(state.store.snapshot().contextCommitCount, undefined);
    await state.gateway.close().catch(() => undefined);

    const store = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession(
      state.session.sessionPath,
      state.session.contextBackend,
    );
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must restore existing Prime session");
      },
      async restoreSession(_identity, onRecovered) {
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-1",
            "context-result-recovery",
          ),
          primeCursor: { generation: "prime-events-1", sequence: 0 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-1",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("not used");
      },
    });

    const receipt = await reopened.executeSessionContext(
      structuredClone(name),
      async () => undefined,
    );
    assert.equal(receipt.status, "succeeded");
    assert.equal(state.session.contextSideEffects.length, 1);
    assert.deepEqual(restoredSession.contextCalls, [[
      "name",
      "context-name-restart",
      "SENTINEL_RESTART_NAME",
    ]]);
    assert.deepEqual(state.session.contextAcknowledgements, [
      "session-1-context-context-name-restart-set-name",
    ]);
    assert.deepEqual(
      await reopened.executeSessionContext(
        structuredClone(name),
        async () => undefined,
      ),
      receipt,
    );
    assert.equal(restoredSession.contextCalls.length, 1);
  } finally {
    await reopened?.close().catch(() => undefined);
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway reads a closed tree and durably navigates to a nullable root leaf", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const continuationId = state.session.continuationId;
    const beforeBinding = state.store.activeContextBinding();
    const tree = await state.gateway.executeSessionContext(contextCommand(
      "session.tree.read",
      { continuation_id: continuationId },
      "context-tree-read-1",
    ), async () => undefined);
    assert.deepEqual(tree.payload.result, {
      continuation_id: continuationId,
      nodes: state.session.contextTree.nodes,
      leaf_id: "entry-2",
    });

    const navigated = await state.gateway.executeSessionContext(contextCommand(
      "session.tree.navigate",
      { continuation_id: continuationId, entry_id: "entry-1" },
      "context-tree-navigate-1",
    ), async () => undefined);
    assert.deepEqual(navigated.payload.result, {
      continuation_id: continuationId,
      previous_leaf_id: "entry-2",
      current_leaf_id: null,
      transition_sha256: navigated.payload.result.transition_sha256,
    });
    assert.match(navigated.payload.result.transition_sha256, /^[0-9a-f]{64}$/);
    const afterBinding = state.store.activeContextBinding();
    assert.notEqual(afterBinding.privateRef, beforeBinding.privateRef);
    assert.equal(afterBinding.continuationId, continuationId);
    await state.privateValues.readContinuationLocator(afterBinding);
    assert.deepEqual(state.session.contextAcknowledgements, [
      "session-1-context-context-tree-navigate-1-tree-navigate",
    ]);
    assert.equal(JSON.stringify(tree).includes("SENTINEL"), false);
    assert.equal(JSON.stringify(navigated).includes(state.sessionRoot), false);
  } finally {
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway atomically forks and clones exact active continuations", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const sourceId = state.session.continuationId;
    const sourceBindingBefore = state.store.activeContextBinding();
    const fork = contextCommand("session.fork", {
      continuation_id: sourceId,
      entry_id: "entry-1",
      position: "before",
    }, "context-fork-1");

    const forkReceipt = await state.gateway.executeSessionContext(
      fork,
      async () => undefined,
    );

    assert.equal(forkReceipt.payload.result.source_continuation_id, sourceId);
    assert.equal(forkReceipt.payload.result.active_leaf_id, null);
    assert.match(forkReceipt.payload.result.transition_sha256, /^[0-9a-f]{64}$/);
    const forkId = forkReceipt.payload.result.new_continuation_id;
    assert.notEqual(forkId, sourceId);
    assert.equal(state.store.activeContextBinding().continuationId, forkId);
    assert.equal(state.session.continuationId, forkId);
    const sourceBindingAfter = state.store.currentContextBinding(sourceId);
    assert.ok(sourceBindingAfter);
    assert.notEqual(sourceBindingAfter.privateRef, sourceBindingBefore.privateRef);
    await state.privateValues.readContinuationLocator(sourceBindingAfter);
    await state.privateValues.readContinuationLocator(
      state.store.activeContextBinding(),
    );

    const clone = contextCommand("session.clone", {
      continuation_id: forkId,
    }, "context-clone-1");
    const cloneReceipt = await state.gateway.executeSessionContext(
      clone,
      async () => undefined,
    );
    assert.equal(cloneReceipt.payload.result.source_continuation_id, forkId);
    assert.equal(cloneReceipt.payload.result.active_leaf_id, "entry-2");
    assert.notEqual(cloneReceipt.payload.result.new_continuation_id, forkId);
    assert.equal(
      state.store.activeContextBinding().continuationId,
      cloneReceipt.payload.result.new_continuation_id,
    );
    assert.equal(
      state.store.snapshot().primeIdentity.transcriptSessionId,
      state.session.transcriptSessionId,
    );
    assert.deepEqual(state.session.contextAcknowledgements, [
      "session-1-context-context-fork-1-fork",
      "session-1-context-context-clone-1-clone",
    ]);
    assert.equal(JSON.stringify(forkReceipt).includes(state.sessionRoot), false);
    assert.equal(JSON.stringify(cloneReceipt).includes(state.sessionRoot), false);
  } finally {
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway pins fork and clone selectors across failed and conflicting replay", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const continuationId = state.session.continuationId;
    const clone = contextCommand("session.clone", {
      continuation_id: continuationId,
    }, "context-clone-selector");
    state.failNextContinuationBeforeResult();
    await assert.rejects(
      state.gateway.executeSessionContext(clone, async () => undefined),
    );
    assert.deepEqual(state.store.preparedContextState(clone.command_id), {
      previousLeafId: "entry-2",
      selectedEntryId: "entry-2",
    });
    state.session.contextTree.leafId = "entry-1";
    const cloned = await state.gateway.executeSessionContext(
      structuredClone(clone),
      async () => undefined,
    );
    assert.equal(cloned.payload.result.active_leaf_id, "entry-2");

    const conflicting = structuredClone(clone);
    conflicting.payload.continuation_id = "continuation-other";
    await assert.rejects(
      state.gateway.executeSessionContext(conflicting, async () => undefined),
    );
    assert.equal(
      state.session.contextSideEffects.filter(
        ([stableId]) => stableId.endsWith("-clone"),
      ).length,
      1,
    );
  } finally {
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway recovers tree navigation after Prime mutation but before durable commit", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const navigation = contextCommand("session.tree.navigate", {
      continuation_id: state.session.continuationId,
      entry_id: "entry-1",
    }, "context-tree-crash-after-result");
    state.failContextCommitAfterResult();
    await assert.rejects(
      state.gateway.executeSessionContext(navigation, async () => undefined),
    );
    assert.ok(state.store.preparedContextBinding(navigation.command_id));
    assert.equal(
      state.session.contextSideEffects.filter(
        ([stableId]) => stableId.endsWith("-tree-navigate"),
      ).length,
      1,
    );
    await state.gateway.close().catch(() => undefined);

    const store = await GatewayDurableStore.open(state.root, "session-1");
    let restoredSession;
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must restore prepared tree navigation");
      },
      async restoreSession(identity, onRecovered) {
        assert.equal(identity.pendingResume, undefined);
        assert.equal(identity.pendingForkClone, undefined);
        restoredSession = new FakePrimeSession(
          identity.sessionPath,
          state.session.contextBackend,
          identity,
        );
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-1",
            "tree-navigation-recovery",
          ),
          primeCursor: { generation: "prime-events-1", sequence: 0 },
          transcriptSessionId: identity.transcriptSessionId,
          supervisorGeneration: "supervisor-generation-1",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("not used");
      },
    });

    assert.equal(store.preparedContextOperations().length, 0);
    assert.equal(store.activeContextBinding().continuationId, "continuation-1");
    await state.privateValues.readContinuationLocator(
      store.activeContextBinding(),
    );
    const [committed] = store.contextOperations().filter(
      ({ command: candidate }) => candidate.command_id === navigation.command_id,
    );
    assert.equal(committed.receipt.payload.result.current_leaf_id, null);
    assert.equal(
      state.session.contextSideEffects.filter(
        ([stableId]) => stableId.endsWith("-tree-navigate"),
      ).length,
      1,
    );
    assert.deepEqual(state.session.contextAcknowledgements, [
      "session-1-context-context-tree-crash-after-result-tree-navigate",
    ]);
  } finally {
    await reopened?.close().catch(() => undefined);
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway recovers fork and clone across both replacement crash windows", async () => {
  for (const operation of ["session.fork", "session.clone"]) {
    for (const crashWindow of ["before-result", "after-result"]) {
      const state = await fixture();
      let reopened;
      try {
        const goalRef = await state.privateValues.putInput("goal");
        await state.gateway.accept(command("session.create", {
          system_id: "research.system",
          system_version: "1.0.0",
          goal_id: "goal-1",
          goal_ref: goalRef,
        }, "command-create"));
        const commandId = `context-${operation.slice("session.".length)}-${crashWindow}`;
        const replacement = contextCommand(
          operation,
          operation === "session.fork"
            ? {
                continuation_id: state.session.continuationId,
                entry_id: "entry-1",
                position: "before",
              }
            : { continuation_id: state.session.continuationId },
          commandId,
        );
        if (crashWindow === "before-result") {
          state.failNextContinuationBeforeResult();
        } else {
          state.failContextCommitAfterResult();
        }
        await assert.rejects(
          state.gateway.executeSessionContext(replacement, async () => undefined),
        );
        assert.ok(state.store.preparedContextBinding(replacement.command_id));
        await state.gateway.close().catch(() => undefined);

        const store = await GatewayDurableStore.open(state.root, "session-1");
        let restoredSession;
        reopened = await PrimeGateway.open({
          sessionId: "session-1",
          generation: 1,
          authorityId: "authority-1",
          store,
          privateValues: state.privateValues,
          async createSession() {
            throw new Error("must restore prepared fork or clone");
          },
          async restoreSession(identity, onRecovered) {
            assert.equal(identity.pendingForkClone.commandId, commandId);
            assert.equal(identity.pendingForkClone.operation, operation);
            assert.equal(
              identity.pendingForkClone.selectedEntryId,
              operation === "session.fork" ? "entry-1" : "entry-2",
            );
            restoredSession = new FakePrimeSession(
              identity.sessionPath,
              state.session.contextBackend,
              identity,
            );
            const result = operation === "session.fork"
              ? await restoredSession.forkContext(
                  commandId,
                  identity.continuationId,
                  identity.pendingForkClone.selectedEntryId,
                  identity.pendingForkClone.position,
                )
              : await restoredSession.cloneContext(
                  commandId,
                  identity.continuationId,
                  identity.pendingForkClone.selectedEntryId,
                );
            restoredSession.adoptContinuation(result.locator);
            await onRecovered({
              transport: recoveryTransport(
                "supervisor-generation-1",
                `${operation}-${crashWindow}-recovery`,
              ),
              primeCursor: { generation: "prime-events-1", sequence: 0 },
              transcriptSessionId: result.locator.transcriptSessionId,
              supervisorGeneration: "supervisor-generation-1",
              sessionStatus: "running",
            });
            return restoredSession;
          },
          async createCheckpoint() {
            throw new Error("not used");
          },
        });

        assert.equal(store.preparedContextOperations().length, 0);
        assert.equal(
          store.activeContextBinding().continuationId,
          restoredSession.continuationId,
        );
        assert.notEqual(restoredSession.continuationId, "continuation-1");
        assert.equal(
          store.snapshot().primeIdentity.transcriptSessionId,
          restoredSession.transcriptSessionId,
        );
        assert.ok(store.currentContextBinding("continuation-1"));
        await state.privateValues.readContinuationLocator(
          store.currentContextBinding("continuation-1"),
        );
        await state.privateValues.readContinuationLocator(
          store.activeContextBinding(),
        );
        const purpose = operation === "session.fork" ? "fork" : "clone";
        assert.equal(
          state.session.contextSideEffects.filter(
            ([stableId]) => stableId.endsWith(`-${purpose}`),
          ).length,
          1,
        );
        assert.deepEqual(state.session.contextAcknowledgements, [
          `session-1-context-${commandId}-${purpose}`,
        ]);
      } finally {
        await reopened?.close().catch(() => undefined);
        await state.cleanup({ allowCloseFailure: true });
      }
    }
  }
});

test("gateway upgrades a legacy active locator before restored execution", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const current = state.store.activeContextBinding();
    assert.ok(current);
    const legacy = await downgradeContinuationBinding(state.root, current);
    await state.store.rebindContextBinding(legacy);
    await state.gateway.close();

    const store = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession(state.session.sessionPath);
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must restore active continuation");
      },
      async restoreSession(identity, onRecovered) {
        assert.equal(identity.continuationId, state.session.continuationId);
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-1",
            "legacy-locator-recovery",
          ),
          primeCursor: { generation: "prime-events-1", sequence: 0 },
          transcriptSessionId: state.session.transcriptSessionId,
          supervisorGeneration: "supervisor-generation-1",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("not used");
      },
    });

    const upgraded = store.activeContextBinding();
    assert.ok(upgraded);
    assert.notEqual(upgraded.privateRef, legacy.privateRef);
    const originalBody = await readFile(state.session.sessionPath);
    await rename(state.session.sessionPath, `${state.session.sessionPath}.old`);
    await writeFile(state.session.sessionPath, originalBody, { mode: 0o600 });
    await assert.rejects(
      state.privateValues.readContinuationLocator(upgraded),
    );
  } finally {
    await reopened?.close().catch(() => undefined);
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway resumes one exact private continuation and deletes only the inactive target", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const { sourceLocator, nextLocator } = await state.forkToContinuation2();
    state.session.mutateSourceOnResume = true;

    const resume = contextCommand(
      "session.continuation.resume",
      { continuation_id: sourceLocator.continuationId },
      "context-resume-1",
    );
    const resumed = await state.gateway.executeSessionContext(
      resume,
      async () => undefined,
    );
    assert.deepEqual(resumed.payload.result, {
      previous_continuation_id: nextLocator.continuationId,
      current_continuation_id: sourceLocator.continuationId,
      transition_sha256: resumed.payload.result.transition_sha256,
    });
    assert.match(resumed.payload.result.transition_sha256, /^[0-9a-f]{64}$/);
    assert.equal(state.session.continuationId, sourceLocator.continuationId);
    assert.equal(
      state.store.activeContextBinding().continuationId,
      sourceLocator.continuationId,
    );
    assert.equal(JSON.stringify(resumed).includes(state.sessionRoot), false);

    const activeDelete = contextCommand(
      "session.continuation.delete",
      { continuation_id: sourceLocator.continuationId },
      "context-delete-active",
    );
    const sideEffectsBefore = state.session.contextSideEffects.length;
    await assert.rejects(
      state.gateway.executeSessionContext(activeDelete, async () => undefined),
    );
    assert.equal(state.session.contextSideEffects.length, sideEffectsBefore);

    const remove = contextCommand(
      "session.continuation.delete",
      { continuation_id: nextLocator.continuationId },
      "context-delete-1",
    );
    const deleted = await state.gateway.executeSessionContext(
      remove,
      async () => undefined,
    );
    assert.equal(deleted.payload.result.continuation_id, nextLocator.continuationId);
    assert.match(deleted.payload.result.deletion_sha256, /^[0-9a-f]{64}$/);
    assert.equal(
      state.store.currentContextBinding(nextLocator.continuationId),
      undefined,
    );
    assert.deepEqual(state.session.contextAcknowledgements, [
      "session-1-context-context-resume-1-resume",
      "session-1-context-context-delete-1-delete",
    ]);
    assert.deepEqual(
      await state.gateway.executeSessionContext(
        structuredClone(remove),
        async () => undefined,
      ),
      deleted,
    );
  } finally {
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway replays a prepared resume after a crash before the Prime result", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const { sourceLocator } = await state.forkToContinuation2();
    const resume = contextCommand(
      "session.continuation.resume",
      { continuation_id: sourceLocator.continuationId },
      "context-resume-before-result",
    );
    const effectsBefore = state.session.contextSideEffects.length;
    state.failNextContinuationBeforeResult();

    await assert.rejects(
      state.gateway.executeSessionContext(resume, async () => undefined),
    );
    assert.ok(state.store.preparedContextBinding(resume.command_id));
    assert.equal(state.session.contextSideEffects.length, effectsBefore);

    const receipt = await state.gateway.executeSessionContext(
      structuredClone(resume),
      async () => undefined,
    );
    assert.equal(receipt.status, "succeeded");
    assert.equal(state.session.contextSideEffects.length, effectsBefore + 1);
    assert.equal(state.session.continuationId, sourceLocator.continuationId);
  } finally {
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway completes a prepared resume after restart between Prime result and durable commit", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const { sourceLocator, nextLocator } = await state.forkToContinuation2();
    state.session.mutateSourceOnResume = true;
    const resume = contextCommand(
      "session.continuation.resume",
      { continuation_id: sourceLocator.continuationId },
      "context-resume-after-result",
    );
    state.failContextCommitAfterResult();

    await assert.rejects(
      state.gateway.executeSessionContext(resume, async () => undefined),
    );
    const resumeEffects = state.session.contextSideEffects.filter(
      ([stableId]) => stableId.endsWith("-resume"),
    );
    assert.equal(resumeEffects.length, 1);
    assert.equal(state.session.continuationId, nextLocator.continuationId);
    await state.gateway.close().catch(() => undefined);

    const store = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession(
      nextLocator.sessionPath,
      state.session.contextBackend,
      nextLocator,
    );
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must recover prepared continuation resume");
      },
      async restoreSession(identity, onRecovered) {
        assert.equal(identity.continuationId, nextLocator.continuationId);
        assert.equal(identity.pendingResume.commandId, resume.command_id);
        const resumed = await restoredSession.resumeContinuation(
          identity.pendingResume.commandId,
          identity.pendingResume.target,
        );
        restoredSession.adoptContinuation(resumed.locator);
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-1",
            "continuation-resume-recovery",
          ),
          primeCursor: { generation: "prime-events-1", sequence: 0 },
          transcriptSessionId: sourceLocator.transcriptSessionId,
          supervisorGeneration: "supervisor-generation-1",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("not used");
      },
    });

    assert.equal(restoredSession.continuationId, sourceLocator.continuationId);
    assert.equal(
      store.activeContextBinding().continuationId,
      sourceLocator.continuationId,
    );
    assert.equal(
      store.snapshot().primeIdentity.transcriptSessionId,
      sourceLocator.transcriptSessionId,
    );
    assert.equal(
      state.session.contextSideEffects.filter(
        ([stableId]) => stableId.endsWith("-resume"),
      ).length,
      1,
    );
    const replay = await reopened.executeSessionContext(
      structuredClone(resume),
      async () => undefined,
    );
    assert.equal(replay.status, "succeeded");
  } finally {
    await reopened?.close().catch(() => undefined);
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway recovers delete after side effect without resolving a missing path broadly", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const { sourceLocator, nextLocator } = await state.forkToContinuation2();
    await state.gateway.executeSessionContext(contextCommand(
      "session.continuation.resume",
      { continuation_id: sourceLocator.continuationId },
      "context-resume-for-delete",
    ), async () => undefined);
    const remove = contextCommand(
      "session.continuation.delete",
      { continuation_id: nextLocator.continuationId },
      "context-delete-after-side-effect",
    );
    state.failContextCommitAfterResult();

    await assert.rejects(
      state.gateway.executeSessionContext(remove, async () => undefined),
    );
    const deleteEffects = state.session.contextSideEffects.filter(
      ([stableId]) => stableId.endsWith("-delete"),
    );
    assert.equal(deleteEffects.length, 1);
    assert.ok(state.store.preparedContextBinding(remove.command_id));
    assert.equal(state.store.snapshot().contextCommitCount, 2);
    await state.gateway.close().catch(() => undefined);

    const store = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession(
      sourceLocator.sessionPath,
      state.session.contextBackend,
    );
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must restore exact active continuation");
      },
      async restoreSession(identity, onRecovered) {
        assert.equal(identity.continuationId, sourceLocator.continuationId);
        assert.equal(identity.sessionPath, sourceLocator.sessionPath);
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-1",
            "continuation-delete-recovery",
          ),
          primeCursor: { generation: "prime-events-1", sequence: 0 },
          transcriptSessionId: sourceLocator.transcriptSessionId,
          supervisorGeneration: "supervisor-generation-1",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("not used");
      },
    });

    const receipt = await reopened.executeSessionContext(
      structuredClone(remove),
      async () => undefined,
    );
    assert.equal(receipt.status, "succeeded");
    assert.equal(
      store.currentContextBinding(nextLocator.continuationId),
      undefined,
    );
    assert.equal(
      state.session.contextSideEffects.filter(
        ([stableId]) => stableId.endsWith("-delete"),
      ).length,
      1,
    );
    assert.deepEqual(restoredSession.contextAcknowledgements.slice(-1), [
      "session-1-context-context-delete-after-side-effect-delete",
    ]);
  } finally {
    await reopened?.close().catch(() => undefined);
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway handles input pause resume attach checkpoint and detach", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const inputRef = await state.privateValues.putInput("SENTINEL_PRIVATE_INPUT");
    await state.gateway.accept(command("input.submit", {
      input_id: "input-1",
      delivery: "steer",
      content_ref: inputRef,
    }, "command-input"));
    await state.gateway.accept(command("session.pause", {
      reason_code: "operator-request",
    }, "command-pause"));
    await state.gateway.accept(command("session.resume", {
      reason_code: "operator-request",
    }, "command-resume"));
    await state.gateway.accept(command("session.attach", {
      cursor: { generation: 1, sequence: 2 },
    }, "command-attach"));
    await state.gateway.accept(command("checkpoint.request", {
      checkpoint_id: "checkpoint-1",
    }, "command-checkpoint"));
    await state.gateway.detach();

    assert.deepEqual(state.session.calls, [
      ["input", "input-1", "steer", "SENTINEL_PRIVATE_INPUT"],
      ["pause", "command-pause"],
      ["resume", "command-resume"],
      ["attach", "command-attach", undefined],
      ["detach", "asterion-detach"],
    ]);
    assert.deepEqual(eventTypes(state.store), [
      "session.created",
      "session.running",
      "session.paused",
      "session.running",
      "session.recovery-required",
      "session.running",
      "checkpoint.created",
    ]);
    const checkpoint = state.store.eventsAfter(0).at(-1).event;
    assert.equal(checkpoint.payload.covered_sequence, 6);
    assert.deepEqual(state.store.snapshot().primeIdentity, {
      activeSessionId: "prime-root-1",
      transcriptSessionId: "transcript-1",
      supervisorGeneration: "supervisor-generation-2",
    });
    assert.deepEqual(state.store.snapshot().primeCursor, {
      generation: "prime-events-2",
      sequence: 11,
    });
    assert.deepEqual(state.checkpointAcknowledgements, ["checkpoint-1"]);
    assert.equal(JSON.stringify(state.store.eventsAfter(0)).includes("SENTINEL"), false);
    const events = state.store.eventsAfter(0).map(({ event }) => event);
    assert.deepEqual(events.map(validateControlEvent), events);
    assert.deepEqual(events.map(({ sequence }) => sequence), [1, 2, 3, 4, 5, 6, 7]);
  } finally {
    await state.cleanup();
  }
});

test("gateway delivers only committed attachments causal to one exact input", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const bodies = [Buffer.from("SENTINEL_IMAGE_ONE"), Buffer.from("SENTINEL_IMAGE_TWO")];
    const metadata = bodies.map((body, index) => ({
      sessionId: "session-1",
      inputId: "input-rich",
      attachmentId: `attachment-${index + 1}`,
      mediaType: index === 0 ? "image/png" : "image/jpeg",
      sha256: createHash("sha256").update(body).digest("hex"),
      size: body.byteLength,
    }));
    for (let index = 0; index < metadata.length; index += 1) {
      const item = metadata[index];
      const bind = contextCommand("session.attachment.bind", {
        input_id: item.inputId,
        attachment_id: item.attachmentId,
        body_ref: `body-${index + 1}`,
        media_type: item.mediaType,
        sha256: item.sha256,
        size: item.size,
      }, `context-attachment-${index + 1}`);
      const receipt = await state.gateway.executeSessionContext(
        bind,
        () => state.privateValues.bindAttachment(item, bodies[index]),
      );
      assert.equal(receipt.status, "succeeded");
      assert.equal(JSON.stringify(receipt).includes("SENTINEL_IMAGE"), false);
    }
    const contentRef = await state.privateValues.putInput("private rich input");
    await state.gateway.accept(command("input.submit", {
      input_id: "input-rich",
      delivery: "direct",
      content_ref: contentRef,
    }, "command-rich-input"));

    const delivered = state.session.calls.at(-1);
    assert.deepEqual(delivered.slice(0, 4), [
      "input", "input-rich", "direct", "private rich input",
    ]);
    assert.deepEqual(delivered[4].map(({ body, ...item }) => ({
      ...item,
      body: Buffer.from(body),
    })), metadata.map((item, index) => ({
      attachmentId: item.attachmentId,
      mediaType: item.mediaType,
      sha256: item.sha256,
      size: item.size,
      body: bodies[index],
    })));

    await assert.rejects(state.gateway.accept(command("input.submit", {
      input_id: "input-rich",
      delivery: "direct",
      content_ref: contentRef,
    }, "command-rich-input-duplicate")));
    await assert.rejects(state.gateway.executeSessionContext(
      contextCommand("session.attachment.bind", {
        input_id: "input-rich",
        attachment_id: "attachment-3",
        body_ref: "body-3",
        media_type: "image/png",
        sha256: "a".repeat(64),
        size: 1,
      }, "context-attachment-late"),
      async () => undefined,
    ));
  } finally {
    await state.cleanup();
  }
});

test("gateway replays all delivery modes after restart without resending attachments", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const image = Buffer.from("SENTINEL_RESTART_PRIVATE_IMAGE");
    const metadata = {
      sessionId: "session-1",
      inputId: "input-direct",
      attachmentId: "attachment-1",
      mediaType: "image/png",
      sha256: createHash("sha256").update(image).digest("hex"),
      size: image.byteLength,
    };
    await state.gateway.executeSessionContext(
      contextCommand("session.attachment.bind", {
        input_id: metadata.inputId,
        attachment_id: metadata.attachmentId,
        body_ref: "body-restart",
        media_type: metadata.mediaType,
        sha256: metadata.sha256,
        size: metadata.size,
      }, "context-attachment-restart"),
      () => state.privateValues.bindAttachment(metadata, image),
    );
    const inputs = [];
    for (const [inputId, delivery] of [
      ["input-direct", "direct"],
      ["input-steer", "steer"],
      ["input-follow-up", "follow_up"],
    ]) {
      const contentRef = await state.privateValues.putInput(`private-${delivery}`);
      const input = command("input.submit", {
        input_id: inputId,
        delivery,
        content_ref: contentRef,
      }, `command-${inputId}`);
      inputs.push(input);
      await state.gateway.accept(input);
    }
    assert.equal(state.store.inputDeliveries().length, 3);
    const publicRecords = await Promise.all(
      (await readdir(join(state.root, "public", "records")))
        .filter((name) => name.endsWith(".json"))
        .map((name) => readFile(join(state.root, "public", "records", name), "utf8")),
    );
    assert.equal(publicRecords.join("").includes("SENTINEL_RESTART_PRIVATE_IMAGE"), false);
    await state.gateway.close();

    const reopenedStore = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession(state.session.sessionPath);
    restoredSession.supervisorGeneration = "supervisor-generation-2";
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store: reopenedStore,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must not create a second Prime root");
      },
      async restoreSession(_identity, onRecovered) {
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-2",
            "delivery-replay-transport",
          ),
          primeCursor: { generation: "prime-events-2", sequence: 0 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-2",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("checkpoint not expected");
      },
    });
    for (const input of inputs) {
      await reopened.accept(structuredClone(input));
    }

    assert.deepEqual(restoredSession.calls, []);
    assert.deepEqual(restoredSession.inputAcknowledgements.sort(), [
      "input-direct",
      "input-follow-up",
      "input-steer",
    ]);
    assert.equal(reopenedStore.inputDeliveries().length, 3);
  } finally {
    await reopened?.close().catch(() => undefined);
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway load-only compatibility never resends a pre-delivery-ledger input", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const legacyRef = await state.privateValues.putInput("private legacy input");
    const legacyInput = command("input.submit", {
      input_id: "input-legacy",
      delivery: "direct",
      content_ref: legacyRef,
    }, "command-input-legacy");
    await state.store.acceptCommand(legacyInput);
    assert.equal(state.store.inputDeliveryProtocolPosition(), undefined);
    await state.gateway.close();

    const reopenedStore = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession(state.session.sessionPath);
    restoredSession.supervisorGeneration = "supervisor-generation-2";
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store: reopenedStore,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must not create a second Prime root");
      },
      async restoreSession(_identity, onRecovered) {
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-2",
            "legacy-delivery-transport",
          ),
          primeCursor: { generation: "prime-events-2", sequence: 0 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-2",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("checkpoint not expected");
      },
    });
    await reopened.accept(structuredClone(legacyInput));
    assert.deepEqual(restoredSession.calls, []);

    const currentRef = await state.privateValues.putInput("private current input");
    await reopened.accept(command("input.submit", {
      input_id: "input-current",
      delivery: "direct",
      content_ref: currentRef,
    }, "command-input-current"));
    assert.equal(reopenedStore.inputDeliveryProtocolPosition() !== undefined, true);
    assert.deepEqual(restoredSession.calls, [[
      "input",
      "input-current",
      "direct",
      "private current input",
    ]]);
  } finally {
    await reopened?.close().catch(() => undefined);
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway rejects missing extra reordered conflicting and unsupported attachments", async () => {
  for (const fault of [
    "missing",
    "extra",
    "reordered",
    "conflicting",
    "unsupported",
  ]) {
    const state = await fixture();
    try {
      const goalRef = await state.privateValues.putInput("goal");
      await state.gateway.accept(command("session.create", {
        system_id: "research.system",
        system_version: "1.0.0",
        goal_id: "goal-1",
        goal_ref: goalRef,
      }, "command-create"));
      let bindingSequence = 0;
      const bind = async (attachmentId, mediaType = "image/png") => {
        bindingSequence += 1;
        const body = Buffer.from(`SENTINEL_${fault}_${attachmentId}`);
        const metadata = {
          sessionId: "session-1",
          inputId: `input-${fault}`,
          attachmentId,
          mediaType,
          sha256: createHash("sha256").update(body).digest("hex"),
          size: body.byteLength,
        };
        let privateRef;
        const receipt = await state.gateway.executeSessionContext(
          contextCommand("session.attachment.bind", {
            input_id: metadata.inputId,
            attachment_id: metadata.attachmentId,
            body_ref: `body-${fault}-${attachmentId}`,
            media_type: metadata.mediaType,
            sha256: metadata.sha256,
            size: metadata.size,
          }, `context-${fault}-${attachmentId}-${bindingSequence}`),
          async () => {
            privateRef = await state.privateValues.bindAttachment(metadata, body);
          },
        );
        return { body, metadata, privateRef, receipt };
      };

      if (fault === "extra") {
        const body = Buffer.from("SENTINEL_EXTRA_UNCOMMITTED");
        await state.privateValues.bindAttachment({
          sessionId: "session-1",
          inputId: "input-extra",
          attachmentId: "attachment-1",
          mediaType: "image/png",
          sha256: createHash("sha256").update(body).digest("hex"),
          size: body.byteLength,
        }, body);
      } else if (fault === "reordered") {
        await bind("attachment-2");
        await bind("attachment-1");
      } else if (fault === "unsupported") {
        await assert.rejects(bind("attachment-1", "application/pdf"));
      } else {
        const first = await bind("attachment-1");
        if (fault === "missing") {
          assert.ok(first.privateRef);
          await unlink(join(
            state.root,
            "private",
            "values",
            `${first.privateRef.slice("private:".length)}.value`,
          ));
        } else {
          await assert.rejects(bind("attachment-1"));
        }
      }

      if (fault !== "conflicting" && fault !== "unsupported") {
        const contentRef = await state.privateValues.putInput(`private-${fault}`);
        await assert.rejects(state.gateway.accept(command("input.submit", {
          input_id: `input-${fault}`,
          delivery: "direct",
          content_ref: contentRef,
        }, `command-input-${fault}`)), (error) => {
          assert.equal(String(error).includes("SENTINEL"), false);
          return true;
        });
      }
      assert.deepEqual(state.session.calls, []);
    } finally {
      await state.cleanup({ allowCloseFailure: true });
    }
  }
});

test("gateway replays one stable input after the Prime result beats delivery commit", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const contentRef = await state.privateValues.putInput(
      "SENTINEL_PRIVATE_DELIVERY_REPLAY",
    );
    const input = command("input.submit", {
      input_id: "input-replay",
      delivery: "follow_up",
      content_ref: contentRef,
    }, "command-input-replay");
    state.session.afterInputResult = () => {
      state.session.afterInputResult = undefined;
      state.failNextDurableWrite();
    };

    await assert.rejects(state.gateway.accept(input));
    assert.equal(state.store.inputDeliveries().length, 0);
    assert.deepEqual(state.session.inputAcknowledgements, []);
    await state.gateway.close().catch(() => undefined);

    const reopenedStore = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession(state.session.sessionPath);
    restoredSession.supervisorGeneration = "supervisor-generation-2";
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store: reopenedStore,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must not create a second Prime root");
      },
      async restoreSession(_identity, onRecovered) {
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-2",
            "input-result-replay-transport",
          ),
          primeCursor: { generation: "prime-events-2", sequence: 0 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-2",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("checkpoint not expected");
      },
    });
    await reopened.accept(structuredClone(input));

    assert.deepEqual(restoredSession.calls, [[
      "input",
      "input-replay",
      "follow_up",
      "SENTINEL_PRIVATE_DELIVERY_REPLAY",
    ]]);
    assert.deepEqual(restoredSession.inputAcknowledgements, ["input-replay"]);
    assert.equal(reopenedStore.inputDeliveries().length, 1);
    const records = await Promise.all(
      (await readdir(join(state.root, "public", "records")))
        .filter((name) => name.endsWith(".json"))
        .map((name) => readFile(join(state.root, "public", "records", name), "utf8")),
    );
    assert.equal(records.join("").includes("SENTINEL_PRIVATE_DELIVERY_REPLAY"), false);
  } finally {
    await reopened?.close().catch(() => undefined);
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway fences input while its attachment binding is still uncommitted", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const body = Buffer.from("SENTINEL_PENDING_ATTACHMENT");
    const metadata = {
      sessionId: "session-1",
      inputId: "input-pending-attachment",
      attachmentId: "attachment-1",
      mediaType: "image/png",
      sha256: createHash("sha256").update(body).digest("hex"),
      size: body.byteLength,
    };
    let releaseBinding;
    const bindingGate = new Promise((resolve) => {
      releaseBinding = resolve;
    });
    let noteBindingStarted;
    const bindingStarted = new Promise((resolve) => {
      noteBindingStarted = resolve;
    });
    const binding = state.gateway.executeSessionContext(
      contextCommand("session.attachment.bind", {
        input_id: metadata.inputId,
        attachment_id: metadata.attachmentId,
        body_ref: "body-pending-attachment",
        media_type: metadata.mediaType,
        sha256: metadata.sha256,
        size: metadata.size,
      }, "context-pending-attachment"),
      async () => {
        noteBindingStarted();
        await bindingGate;
        await state.privateValues.bindAttachment(metadata, body);
      },
    );
    await bindingStarted;
    const contentRef = await state.privateValues.putInput("private pending input");
    const input = command("input.submit", {
      input_id: metadata.inputId,
      delivery: "steer",
      content_ref: contentRef,
    }, "command-pending-input");

    await assert.rejects(state.gateway.accept(input));
    assert.equal(
      state.store.commands().some(
        ({ command: accepted }) => accepted.command_id === input.command_id,
      ),
      false,
    );
    releaseBinding();
    await binding;
    await state.gateway.accept(input);

    assert.equal(state.store.inputDeliveries().length, 1);
    assert.equal(state.session.calls.at(-1)[4][0].attachmentId, "attachment-1");
  } finally {
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway acknowledges Prime only after checkpoint event is durable", async () => {
  const state = await fixture({ failCheckpointEvent: true });
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    await assert.rejects(state.gateway.accept(command("checkpoint.request", {
      checkpoint_id: "checkpoint-write-failure",
    }, "command-checkpoint-write-failure")));

    assert.deepEqual(state.checkpointAcknowledgements, []);
    assert.equal(eventTypes(state.store).includes("checkpoint.created"), false);
  } finally {
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway retries a failed checkpoint acknowledgement on command replay", async () => {
  const state = await fixture({ checkpointAckFailures: 1 });
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const checkpointCommand = command("checkpoint.request", {
      checkpoint_id: "checkpoint-ack-retry",
    }, "command-checkpoint-ack-retry");
    await state.gateway.accept(checkpointCommand);
    assert.deepEqual(state.checkpointAcknowledgementAttempts, [
      "checkpoint-ack-retry",
    ]);
    assert.deepEqual(state.checkpointAcknowledgements, []);

    await state.gateway.accept(structuredClone(checkpointCommand));
    assert.deepEqual(state.checkpointAcknowledgementAttempts, [
      "checkpoint-ack-retry",
      "checkpoint-ack-retry",
    ]);
    assert.deepEqual(state.checkpointAcknowledgements, [
      "checkpoint-ack-retry",
    ]);
  } finally {
    await state.cleanup();
  }
});

test("gateway retries a failed checkpoint acknowledgement after reopen", async () => {
  const state = await fixture({ checkpointAckFailures: 1 });
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    await state.gateway.accept(command("checkpoint.request", {
      checkpoint_id: "checkpoint-ack-reopen",
    }, "command-checkpoint-ack-reopen"));
    assert.deepEqual(state.checkpointAcknowledgements, []);
    await state.gateway.close();

    const reopenedStore = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession();
    restoredSession.supervisorGeneration = "supervisor-generation-3";
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store: reopenedStore,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must not create a second Prime root");
      },
      async restoreSession(_identity, onRecovered) {
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-3",
            "ack-reopen-transport",
          ),
          primeCursor: { generation: "prime-events-3", sequence: 12 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-3",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("completed checkpoint must not be recreated");
      },
    });

    assert.deepEqual(restoredSession.checkpointAcknowledgements, [
      "checkpoint-ack-reopen",
    ]);
  } finally {
    await reopened?.close();
    await state.cleanup();
  }
});

test("gateway rejects checkpoint when the live supervisor identity drifted", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.supervisorGeneration = "supervisor-generation-drift";
    await assert.rejects(state.gateway.accept(command("checkpoint.request", {
      checkpoint_id: "checkpoint-identity-drift",
    }, "command-checkpoint-identity-drift")));

    assert.deepEqual(state.checkpointAcknowledgements, []);
    assert.equal(eventTypes(state.store).includes("checkpoint.created"), false);
  } finally {
    await state.cleanup();
  }
});

test("gateway persists body-free client observations across reopen and resumes their native sequence", async () => {
  const state = await fixture({ clientObservations: true });
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    for (const [sequence, content] of [[1, "first private body"], [2, "second private body"]]) {
      state.session.emit({
        type: "session_event",
        activeSessionId: "prime-root-1",
        event: { type: "message_end", role: "assistant", content },
        meta: {
          id: `prime-client-event-${sequence}`,
          protocol: { name: "prime-agent.daemon", version: 7 },
          sequence,
          cursor: { generation: "worker-generation-1", sequence },
          emittedAt: `2026-08-10T03:30:0${sequence}Z`,
        },
      });
    }
    await state.gateway.settle();
    const original = state.gateway.clientObservationsAfterCursor({
      generation: 1,
      sequence: 0,
    });
    assert.deepEqual(eventTypes(state.store), ["session.created", "session.running"]);
    assert.equal(original.length, 2);
    assert.equal(JSON.stringify(original).includes("private body"), false);
    await state.gateway.close();

    const store = await GatewayDurableStore.open(state.root, "session-1");
    const privateValues = await PrivateValueStore.open(state.root, {
      continuationRoot: state.sessionRoot,
    });
    const restoredSession = new FakePrimeSession(state.session.sessionPath);
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store,
      privateValues,
      clientObservationValues: privateValues,
      async createSession() {
        throw new Error("must restore");
      },
      async restoreSession(_identity, onRecovered) {
        await onRecovered({
          transport: recoveryTransport("supervisor-generation-1", "client-observation-recovery"),
          primeCursor: { generation: "worker-generation-1", sequence: 2 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-1",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("not used");
      },
    });
    assert.deepEqual(
      reopened.clientObservationsAfterCursor({ generation: 1, sequence: 1 }),
      original.slice(1),
    );
    restoredSession.emit({
      type: "session_event",
      activeSessionId: "prime-root-1",
      event: { type: "message_end", role: "assistant", content: "third private body" },
      meta: {
        id: "prime-client-event-3",
        protocol: { name: "prime-agent.daemon", version: 7 },
        sequence: 3,
        cursor: { generation: "worker-generation-1", sequence: 3 },
        emittedAt: "2026-08-10T03:30:03Z",
      },
    });
    await reopened.settle();
    const all = reopened.clientObservationsAfterCursor({ generation: 1, sequence: 0 });
    assert.deepEqual(all.slice(0, 2), original);
    assert.equal(all[2].source_sequence, 3);
    assert.equal(all[2].observation_id, "prime-client-1-3");
  } finally {
    await reopened?.close().catch(() => undefined);
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway cleans a staged-only client body before reopen can replay it", async () => {
  const state = await fixture({ clientObservations: true });
  let reopened;
  const reference = "private:00000000-0000-4000-8000-000000000099";
  const body = Buffer.from("SENTINEL_STAGED_ONLY_BODY");
  try {
    await state.store.stageClientObservationValue({
      generation: 1, nativeSequence: 1, reference, kind: "message", mediaType: "text/plain",
      size: body.byteLength, sha256: createHash("sha256").update(body).digest("hex"),
    });
    await state.privateValues.putClientValue("session-1", "message", "text/plain", body, reference);
    await state.gateway.close();
    const store = await GatewayDurableStore.open(state.root, "session-1");
    reopened = await PrimeGateway.open({
      sessionId: "session-1", generation: 1, authorityId: "authority-1", store,
      privateValues: state.privateValues, clientObservationValues: state.privateValues,
      restoreExistingSession: false,
      async createSession() { throw new Error("not used"); },
      async createCheckpoint() { throw new Error("not used"); },
    });
    await assert.rejects(state.privateValues.describeClientValue(reference, "session-1"));
    assert.deepEqual(store.clientObservations(1), []);
  } finally {
    await reopened?.close().catch(() => undefined);
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway preserves daemon control mapping with client observations enabled or disabled", async () => {
  for (const clientObservations of [false, true]) {
    const state = await fixture({ clientObservations });
    try {
      const goalRef = await state.privateValues.putInput("goal");
      await state.gateway.accept(command("session.create", {
        system_id: "research.system", system_version: "1.0.0", goal_id: "goal-1", goal_ref: goalRef,
      }, `command-create-daemon-${clientObservations}`));
      state.session.emit({ type: "heartbeats_changed" });
      state.session.emit({ type: "daemon_closing", reason: "shutdown" });
      await state.gateway.settle();
      assert.deepEqual(
        eventTypes(state.store).slice(-2),
        ["fault.raised", "session.recovery-required"],
      );
      assert.deepEqual(state.gateway.clientObservationsAfterCursor({ generation: 1, sequence: 0 }), []);
    } finally {
      await state.cleanup();
    }
  }
});

test("gateway drains an already queued Prime event before checkpoint recovery", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.emit({
      type: "session_event",
      activeSessionId: "prime-root-1",
      event: {
        type: "goal_update",
        goal: {
          active: true,
          status: "active",
          tokensUsed: 5,
          timeUsedSeconds: 1,
          continuationsUsed: 0,
        },
      },
      meta: {
        id: "prime-event-1",
        protocol: { name: "prime-agent.daemon", version: 7 },
        sequence: 1,
        cursor: { generation: "worker-generation-1", sequence: 1 },
        emittedAt: "2026-08-10T03:20:00Z",
      },
    });
    await state.gateway.accept(command("checkpoint.request", {
      checkpoint_id: "checkpoint-race",
    }, "command-checkpoint-race"));

    const events = state.store.eventsAfter(0).map(({ event }) => event);
    assert.deepEqual(events.map(({ type }) => type), [
      "session.created",
      "session.running",
      "budget.reported",
      "session.recovery-required",
      "session.running",
      "checkpoint.created",
    ]);
    assert.equal(events.at(-1).payload.covered_sequence, 5);
    assert.deepEqual(events.map(({ sequence }) => sequence), [1, 2, 3, 4, 5, 6]);
  } finally {
    await state.cleanup();
  }
});

test("gateway resubscribes when a queued pause rejects checkpoint", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.emit({
      type: "session_event",
      activeSessionId: "prime-root-1",
      event: {
        type: "goal_update",
        goal: {
          active: false,
          status: "paused",
          tokensUsed: 0,
          timeUsedSeconds: 1,
          continuationsUsed: 0,
        },
      },
      meta: {
        id: "prime-event-pause",
        protocol: { name: "prime-agent.daemon", version: 7 },
        sequence: 1,
        cursor: { generation: "worker-generation-1", sequence: 1 },
        emittedAt: "2026-08-10T03:21:00Z",
      },
    });
    await assert.rejects(state.gateway.accept(command("checkpoint.request", {
      checkpoint_id: "checkpoint-paused-race",
    }, "command-checkpoint-paused-race")));
    state.session.emit({
      type: "session_event",
      activeSessionId: "prime-root-1",
      event: {
        type: "goal_update",
        goal: {
          active: true,
          status: "active",
          tokensUsed: 0,
          timeUsedSeconds: 2,
          continuationsUsed: 0,
        },
      },
      meta: {
        id: "prime-event-resume",
        protocol: { name: "prime-agent.daemon", version: 7 },
        sequence: 2,
        cursor: { generation: "worker-generation-1", sequence: 2 },
        emittedAt: "2026-08-10T03:22:00Z",
      },
    });
    await state.gateway.settle();

    assert.deepEqual(eventTypes(state.store).slice(-3), [
      "session.paused",
      "session.running",
      "goal.updated",
    ]);
  } finally {
    await state.cleanup();
  }
});

test("gateway reopens a checkpointed resident without creating a second Prime root", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const checkpointCommand = command("checkpoint.request", {
      checkpoint_id: "checkpoint-1",
    }, "command-checkpoint");
    await state.gateway.accept(checkpointCommand);
    await state.gateway.close();

    const reopenedStore = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession();
    restoredSession.supervisorGeneration = "supervisor-generation-3";
    const restoredIdentities = [];
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store: reopenedStore,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must not create a second Prime root");
      },
      async restoreSession(identity, onRecovered) {
        restoredIdentities.push(identity);
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-3",
            "reopened-transport",
          ),
          primeCursor: { generation: "prime-events-3", sequence: 12 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-3",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("completed checkpoint must replay without side effects");
      },
    });

    await reopened.accept(structuredClone(checkpointCommand));
    const inputRef = await state.privateValues.putInput("private resumed input");
    await reopened.accept(command("input.submit", {
      input_id: "input-after-reopen",
      delivery: "direct",
      content_ref: inputRef,
    }, "command-after-reopen"));

    assert.deepEqual(restoredIdentities, [{
      activeSessionId: "prime-root-1",
      transcriptSessionId: "transcript-1",
      supervisorGeneration: "supervisor-generation-2",
      continuationId: "continuation-1",
      sessionPath: state.session.sessionPath,
    }]);
    assert.deepEqual(restoredSession.calls, [[
      "input",
      "input-after-reopen",
      "direct",
      "private resumed input",
    ]]);
    assert.equal(reopenedStore.eventsAfter(0).filter(
      ({ event }) => event.type === "checkpoint.created",
    ).length, 1);
    assert.deepEqual(eventTypes(reopenedStore).slice(-2), [
      "session.recovery-required",
      "session.running",
    ]);
    const events = reopenedStore.eventsAfter(0).map(({ event }) => event);
    assert.deepEqual(events.map(validateControlEvent), events);
    assert.deepEqual(
      events.map(({ sequence }) => sequence),
      events.map((_, index) => index + 1),
    );
  } finally {
    await reopened?.close();
    await state.cleanup();
  }
});

test("gateway preserves paused state across a crash during restart recovery", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    await state.gateway.accept(command("session.pause", {
      reason_code: "operator-request",
    }, "command-pause"));
    await state.gateway.close();

    const interruptedStore = await GatewayDurableStore.open(state.root, "session-1");
    await assert.rejects(PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store: interruptedStore,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must not create a second Prime root");
      },
      async restoreSession() {
        throw new Error("SENTINEL_CRASH_DURING_RESTORE");
      },
      async createCheckpoint() {
        throw new Error("checkpoint not expected");
      },
    }));
    assert.equal(eventTypes(interruptedStore).at(-1), "session.recovery-required");

    const recoveredStore = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession();
    restoredSession.supervisorGeneration = "supervisor-generation-3";
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store: recoveredStore,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must not create a second Prime root");
      },
      async restoreSession(_identity, onRecovered) {
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-3",
            "crash-recovery-transport",
          ),
          primeCursor: { generation: "prime-events-3", sequence: 12 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-3",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("checkpoint not expected");
      },
    });

    const inputRef = await state.privateValues.putInput("private paused input");
    await assert.rejects(reopened.accept(command("input.submit", {
      input_id: "input-after-recovery-crash",
      delivery: "direct",
      content_ref: inputRef,
    }, "command-input-after-recovery-crash")));
    assert.equal(eventTypes(recoveredStore).at(-1), "session.paused");
  } finally {
    await reopened?.close();
    await state.cleanup();
  }
});

test("gateway preserves paused state across restart until explicit resume", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    await state.gateway.accept(command("session.pause", {
      reason_code: "operator-request",
    }, "command-pause"));
    await state.gateway.close();

    const reopenedStore = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession();
    restoredSession.supervisorGeneration = "supervisor-generation-3";
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store: reopenedStore,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must not create a second Prime root");
      },
      async restoreSession(_identity, onRecovered) {
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-3",
            "paused-reopened-transport",
          ),
          primeCursor: { generation: "prime-events-3", sequence: 12 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-3",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("checkpoint not expected");
      },
    });

    const inputRef = await state.privateValues.putInput("private paused input");
    await assert.rejects(reopened.accept(command("input.submit", {
      input_id: "input-before-resume",
      delivery: "direct",
      content_ref: inputRef,
    }, "command-input-before-resume")));
    await reopened.accept(command("session.resume", {
      reason_code: "operator-resume",
    }, "command-resume-after-reopen"));
    await reopened.accept(command("input.submit", {
      input_id: "input-after-resume",
      delivery: "direct",
      content_ref: inputRef,
    }, "command-input-after-resume"));

    assert.deepEqual(eventTypes(reopenedStore).slice(-3), [
      "session.recovery-required",
      "session.paused",
      "session.running",
    ]);
    assert.deepEqual(restoredSession.calls, [
      ["resume", "command-resume-after-reopen"],
      ["input", "input-after-resume", "direct", "private paused input"],
    ]);
    assert.equal(restoredSession.recoveries.length, 1);
  } finally {
    await reopened?.close();
    await state.cleanup();
  }
});

test("gateway maps daemon completion cursor and cancellation to unique terminals", async () => {
  const completed = await fixture();
  try {
    const goalRef = await completed.privateValues.putInput("goal");
    await completed.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    completed.session.emit({
      type: "session_event",
      activeSessionId: "prime-root-1",
      event: {
        type: "goal_update",
        goal: {
          active: false,
          status: "complete",
          tokensUsed: 17,
          timeUsedSeconds: 1,
          continuationsUsed: 1,
        },
      },
      meta: {
        id: "prime-event-1",
        protocol: { name: "prime-agent.daemon", version: 7 },
        sequence: 1,
        cursor: { generation: "worker-generation-1", sequence: 1 },
        emittedAt: "2026-08-10T03:30:00Z",
      },
    });
    completed.session.emit({
      type: "session_closed",
      activeSessionId: "prime-root-1",
      reason: "private-close-body",
    });
    await completed.gateway.settle();
    const events = completed.store.eventsAfter(0).map(({ event }) => event);
    assert.deepEqual(eventTypes(completed.store), [
      "session.created",
      "session.running",
      "goal.updated",
      "budget.reported",
      "session.completed",
    ]);
    assert.deepEqual(completed.store.snapshot().primeCursor, {
      generation: "worker-generation-1",
      sequence: 1,
    });
    assert.deepEqual(validateControlEventStream(events), events);
  } finally {
    await completed.cleanup();
  }

  const cancelled = await fixture();
  try {
    const goalRef = await cancelled.privateValues.putInput("goal");
    await cancelled.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    await cancelled.gateway.accept(command("session.cancel", {
      reason_code: "operator-request",
    }, "command-cancel"));
    const events = cancelled.store.eventsAfter(0).map(({ event }) => event);
    assert.deepEqual(eventTypes(cancelled.store), [
      "session.created",
      "session.running",
      "goal.updated",
      "session.cancelled",
    ]);
    assert.deepEqual(validateControlEventStream(events), events);
    assert.deepEqual(cancelled.session.calls, [["cancel", "command-cancel"]]);
  } finally {
    await cancelled.cleanup();
  }
});

test("gateway resolves admitted actions and preserves uncertain transport state", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const inputRef = await state.privateValues.putInput("private action input");
    const identity = state.gateway.nextEventIdentity();
    await state.gateway.emitActionProposal(proposal(
      identity,
      "action-1",
      inputRef,
    ));
    const admission = state.gateway.waitForAdmission("action-1");
    await state.gateway.accept(command("action.resolve", {
      action_id: "action-1",
      resolution: "admitted",
      reason_code: "authorized",
      receipt_ref: null,
    }, "command-admit"));
    assert.deepEqual(await admission, {
      resolution: "admitted",
      reasonCode: "authorized",
    });

    const terminal = state.gateway.waitForTerminal("action-1");
    await state.gateway.accept(command("action.resolve", {
      action_id: "action-1",
      resolution: "uncertain",
      reason_code: "transport-uncertain",
      receipt_ref: null,
    }, "command-terminal"));
    assert.deepEqual(await terminal, {
      resolution: "uncertain",
      reasonCode: "transport-uncertain",
    });
    assert.deepEqual(await state.gateway.actionStatus("action-1"), {
      action_id: "action-1",
      status: "uncertain",
      reason_code: "transport-uncertain",
    });
  } finally {
    await state.cleanup();
  }
});

test("gateway keeps public terminal command stable while resolving private result lookup", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const inputRef = await state.privateValues.putInput("private action input");
    const identity = state.gateway.nextEventIdentity();
    await state.gateway.emitActionProposal(proposal(identity, "action-1", inputRef));
    await state.gateway.accept(command("action.resolve", {
      action_id: "action-1",
      resolution: "admitted",
      reason_code: "authorized",
      receipt_ref: null,
    }, "command-admit"));
    const privateRef = await state.privateValues.bindResultReference(
      "command-terminal",
      "action-1",
      "receipt-1",
      {
        receiptRef: "receipt-1",
        artifactIds: ["artifact-1"],
        mediaTypes: ["text/plain"],
      },
    );

    const terminal = state.gateway.waitForTerminal("action-1");
    const publicCommand = command("action.resolve", {
      action_id: "action-1",
      resolution: "succeeded",
      reason_code: "executed",
      receipt_ref: "receipt-1",
    }, "command-terminal");
    await state.gateway.accept(structuredClone(publicCommand));

    assert.deepEqual(await terminal, {
      resolution: "succeeded",
      reasonCode: "executed",
      resultRef: privateRef,
    });
    assert.deepEqual(
      state.store
        .snapshot()
        .commandCount,
      3,
    );
    const storedTerminal = state.store
      .eventsAfter(0);
    assert.deepEqual(state.resultLookups, [["command-terminal", "action-1", "receipt-1"]]);
    assert.equal(JSON.stringify(storedTerminal).includes(privateRef), false);
  } finally {
    await state.cleanup();
  }
});

test("successful goal action resolution applies one canonical session terminal", async () => {
  for (const [kind, goalStatus, sessionType, reasonCode] of [
    ["goal.complete", "completed", "session.completed", "host-admitted-goal-complete"],
    ["goal.fail", "failed", "session.failed", "host-admitted-goal-fail"],
  ]) {
    const state = await fixture();
    try {
      const goalRef = await state.privateValues.putInput("goal");
      await state.gateway.accept(command("session.create", {
        system_id: "research.system",
        system_version: "1.0.0",
        goal_id: "goal-1",
        goal_ref: goalRef,
      }, "command-create"));
      const inputRef = await state.privateValues.putInput("private goal result");
      const actionId = kind === "goal.complete" ? "action-complete" : "action-fail";
      await state.gateway.emitActionProposal(goalProposal(
        state.gateway.nextEventIdentity(),
        actionId,
        inputRef,
        kind,
      ));
      await state.gateway.accept(command("action.resolve", {
        action_id: actionId,
        resolution: "admitted",
        reason_code: "authorized",
        receipt_ref: null,
      }, `admit-${actionId}`));
      const terminalCommandId = `terminal-${actionId}`;
      const receiptRef = `system-${kind}-${actionId}`;
      await state.privateValues.bindResultReference(
        terminalCommandId,
        actionId,
        receiptRef,
        { receiptRef, artifactIds: [], mediaTypes: [] },
      );

      await state.gateway.accept(command("action.resolve", {
        action_id: actionId,
        resolution: "succeeded",
        reason_code: "executed",
        receipt_ref: receiptRef,
      }, terminalCommandId));

      const events = state.store.eventsAfter(0).map(({ event }) => event);
      assert.deepEqual(events.slice(-2).map((event) => event.type), [
        "goal.updated",
        sessionType,
      ]);
      assert.deepEqual(events.at(-2).payload, {
        goal_id: "goal-1",
        status: goalStatus,
      });
      assert.deepEqual(events.at(-1).payload, { reason_code: reasonCode });
      assert.deepEqual(validateControlEventStream(events), events);
    } finally {
      await state.cleanup();
    }
  }
});

test("durable goal resolution completes its terminal events after gateway restart", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const inputRef = await state.privateValues.putInput("private goal result");
    const actionId = "action-complete";
    await state.gateway.emitActionProposal(goalProposal(
      state.gateway.nextEventIdentity(), actionId, inputRef, "goal.complete",
    ));
    await state.gateway.accept(command("action.resolve", {
      action_id: actionId,
      resolution: "admitted",
      reason_code: "authorized",
      receipt_ref: null,
    }, "command-admit"));
    const receiptRef = `system-goal.complete-${actionId}`;
    await state.privateValues.bindResultReference(
      "command-terminal",
      actionId,
      receiptRef,
      { receiptRef, artifactIds: [], mediaTypes: [] },
    );
    state.failNextGoalEventWrite();
    await assert.rejects(state.gateway.accept(command("action.resolve", {
      action_id: actionId,
      resolution: "succeeded",
      reason_code: "executed",
      receipt_ref: receiptRef,
    }, "command-terminal")));
    await state.gateway.close().catch(() => undefined);

    const store = await GatewayDurableStore.open(state.root, "session-1");
    const privateValues = await PrivateValueStore.open(state.root, {
      continuationRoot: state.sessionRoot,
    });
    const session = new FakePrimeSession(state.session.sessionPath);
    let tick = 30;
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store,
      privateValues,
      privateResults: privateValues,
      async createSession() {
        throw new Error("must restore");
      },
      async restoreSession(identity, onRecovered) {
        await onRecovered({
          transport: recoveryTransport(
            identity.supervisorGeneration,
            "goal-recovery-transport",
          ),
          primeCursor: { generation: "prime-events-1", sequence: 0 },
          transcriptSessionId: identity.transcriptSessionId,
          supervisorGeneration: identity.supervisorGeneration,
          sessionStatus: "running",
        });
        return session;
      },
      async createCheckpoint() {
        throw new Error("not used");
      },
      now() {
        tick += 1;
        return `2026-08-10T03:00:${String(tick).padStart(2, "0")}Z`;
      },
    });

    const events = store.eventsAfter(0).map(({ event }) => event);
    assert.equal(events.filter((event) =>
      event.type === "goal.updated" && event.payload.status === "completed"
    ).length, 1);
    assert.equal(events.filter((event) => event.type === "session.completed").length, 1);
    assert.deepEqual(validateControlEventStream(events), events);
  } finally {
    await reopened?.close();
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway leaves action admitted when successful result binding is missing and permits replay", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const inputRef = await state.privateValues.putInput("private action input");
    const identity = state.gateway.nextEventIdentity();
    await state.gateway.emitActionProposal(proposal(identity, "action-1", inputRef));
    await state.gateway.accept(command("action.resolve", {
      action_id: "action-1",
      resolution: "admitted",
      reason_code: "authorized",
      receipt_ref: null,
    }, "command-admit"));
    const publicCommand = command("action.resolve", {
      action_id: "action-1",
      resolution: "succeeded",
      reason_code: "executed",
      receipt_ref: "receipt-1",
    }, "command-terminal");
    const terminal = state.gateway.waitForTerminal("action-1");

    await assert.rejects(state.gateway.accept(structuredClone(publicCommand)));
    assert.deepEqual(await state.gateway.actionStatus("action-1"), {
      action_id: "action-1",
      status: "admitted",
      reason_code: "authorized",
    });
    assert.deepEqual(state.resultLookups, [["command-terminal", "action-1", "receipt-1"]]);

    const privateRef = await state.privateValues.bindResultReference(
      "command-terminal",
      "action-1",
      "receipt-1",
      {
        receiptRef: "receipt-1",
        artifactIds: ["artifact-1"],
        mediaTypes: ["text/plain"],
      },
    );
    await state.gateway.accept(structuredClone(publicCommand));

    assert.deepEqual(await terminal, {
      resolution: "succeeded",
      reasonCode: "executed",
      resultRef: privateRef,
    });
    assert.deepEqual(state.resultLookups, [
      ["command-terminal", "action-1", "receipt-1"],
      ["command-terminal", "action-1", "receipt-1"],
    ]);
    assert.equal(state.store.snapshot().commandCount, 3);
  } finally {
    await state.cleanup();
  }
});

test("gateway accepts failed receipts without private result lookup", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const inputRef = await state.privateValues.putInput("private action input");
    const identity = state.gateway.nextEventIdentity();
    await state.gateway.emitActionProposal(proposal(identity, "action-1", inputRef));
    await state.gateway.accept(command("action.resolve", {
      action_id: "action-1",
      resolution: "admitted",
      reason_code: "authorized",
      receipt_ref: null,
    }, "command-admit"));

    const terminal = state.gateway.waitForTerminal("action-1");
    await state.gateway.accept(command("action.resolve", {
      action_id: "action-1",
      resolution: "failed",
      reason_code: "executor-failed",
      receipt_ref: "failure-receipt-1",
    }, "command-terminal"));

    assert.deepEqual(await terminal, {
      resolution: "failed",
      reasonCode: "executor-failed",
    });
    assert.deepEqual(state.resultLookups, []);
  } finally {
    await state.cleanup();
  }
});

test("gateway serializes concurrently reserved action proposals", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const inputRef = await state.privateValues.putInput("private action input");
    const first = state.gateway.nextEventIdentity();
    const second = state.gateway.nextEventIdentity();
    await Promise.all([
      state.gateway.emitActionProposal(proposal(first, "action-1", inputRef)),
      state.gateway.emitActionProposal(proposal(second, "action-2", inputRef)),
    ]);
    const actions = state.store.eventsAfter(0)
      .map(({ event }) => event)
      .filter((event) => event.type === "action.proposed");
    assert.deepEqual(actions.map((event) => event.payload.action_id), [
      "action-1",
      "action-2",
    ]);
    assert.deepEqual(actions.map((event) => event.sequence), [3, 4]);
  } finally {
    await state.cleanup();
  }
});

test("gateway serializes concurrent command persistence", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const firstRef = await state.privateValues.putInput("private first");
    const secondRef = await state.privateValues.putInput("private second");
    await Promise.all([
      state.gateway.accept(command("input.submit", {
        input_id: "input-1",
        delivery: "direct",
        content_ref: firstRef,
      }, "command-input-1")),
      state.gateway.accept(command("input.submit", {
        input_id: "input-2",
        delivery: "follow_up",
        content_ref: secondRef,
      }, "command-input-2")),
    ]);
    assert.equal(state.store.snapshot().commandCount, 3);
    assert.deepEqual(state.session.calls, [
      ["input", "input-1", "direct", "private first"],
      ["input", "input-2", "follow_up", "private second"],
    ]);
  } finally {
    await state.cleanup();
  }
});

test("gateway rejects commands incompatible with canonical session state", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    await assert.rejects(state.gateway.accept(command("session.resume", {
      reason_code: "operator-request",
    }, "command-invalid-resume")));
    assert.deepEqual(state.session.calls, []);
    await state.gateway.accept(command("session.pause", {
      reason_code: "operator-request",
    }, "command-pause"));
    await assert.rejects(state.gateway.accept(command("session.pause", {
      reason_code: "operator-request",
    }, "command-invalid-pause")));
    assert.deepEqual(state.session.calls, [["pause", "command-pause"]]);
  } finally {
    await state.cleanup();
  }
});

test("gateway rejects unknown action resolution and replays failed handling", async () => {
  const state = await fixture();
  try {
    const unknown = command("action.resolve", {
      action_id: "action-unknown",
      resolution: "admitted",
      reason_code: "authorized",
      receipt_ref: null,
    }, "command-unknown-action");
    await assert.rejects(state.gateway.accept(unknown));
    await assert.rejects(state.gateway.accept(structuredClone(unknown)));
    await assert.rejects(state.gateway.actionStatus("action-unknown"));
    assert.equal(state.store.snapshot().commandCount, 1);
  } finally {
    await state.cleanup();
  }
});

test("gateway turns a native cursor regression into recovery and resumes only on resync", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.emit({
      type: "session_event",
      activeSessionId: "prime-root-1",
      event: { type: "message_update", text: "SENTINEL_PRIVATE_MESSAGE" },
      meta: {
        id: "prime-event-1",
        protocol: { name: "prime-agent.daemon", version: 7 },
        sequence: 1,
        cursor: { generation: "worker-generation-1", sequence: 1 },
        emittedAt: "2026-08-10T04:00:00Z",
      },
    });
    state.session.emit({
      type: "session_event",
      activeSessionId: "prime-root-1",
      event: { type: "message_update", text: "SENTINEL_PRIVATE_REGRESSION" },
      meta: {
        id: "prime-event-0",
        protocol: { name: "prime-agent.daemon", version: 7 },
        sequence: 0,
        cursor: { generation: "worker-generation-1", sequence: 0 },
        emittedAt: "2026-08-10T04:00:01Z",
      },
    });
    await state.gateway.settle();
    assert.deepEqual(eventTypes(state.store), [
      "session.created",
      "session.running",
      "fault.raised",
      "session.recovery-required",
    ]);
    state.session.emit({
      type: "session_resynced",
      activeSessionId: "prime-root-1",
      snapshot: { private: "SENTINEL_PRIVATE_SNAPSHOT" },
    });
    await state.gateway.settle();
    assert.deepEqual(eventTypes(state.store), [
      "session.created",
      "session.running",
      "fault.raised",
      "session.recovery-required",
      "session.running",
    ]);
    assert.equal(JSON.stringify(state.store.eventsAfter(0)).includes("SENTINEL"), false);
  } finally {
    await state.cleanup();
  }
});

test("gateway exposes unknown prompt admission as recoverable uncertainty", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.pauseError = new PrimePromptAdmissionUncertainError();
    await state.gateway.accept(command("session.pause", {
      reason_code: "operator-request",
    }, "command-pause"));
    assert.deepEqual(eventTypes(state.store), [
      "session.created",
      "session.running",
      "fault.raised",
      "session.recovery-required",
    ]);
    const fault = state.store.eventsAfter(0).at(-2).event;
    assert.deepEqual(fault.payload, {
      code: "prime-prompt-admission-uncertain",
      recoverable: true,
      evidence_ref: null,
    });
  } finally {
    await state.cleanup();
  }
});

test("gateway delegates private ecosystem activation only to its injected adapter", async () => {
  const calls = [];
  const receipt = Object.freeze({
    authorityDigest: "a".repeat(64),
    featureIds: Object.freeze(["ecosystem.packages"]),
    lifecycleCount: 0,
    mcpCount: 0,
    modelCredentialReads: 0,
    ownedProcessCount: 0,
    packageCount: 1,
    portfolioDigest: "b".repeat(64),
    providerOperations: 0,
    registrationCount: 0,
    resourceCount: 1,
    status: "succeeded",
  });
  const ecosystem = {
    async activate(frame) {
      calls.push(frame);
      return receipt;
    },
  };
  const state = await fixture({ ecosystemAdapter: ecosystem });
  try {
    const frame = Object.freeze({ format: "asterion.prime-ecosystem-frame/v1" });
    assert.equal(await state.gateway.activateEcosystem(frame), receipt);
    assert.deepEqual(calls, [frame]);
  } finally {
    await state.cleanup();
  }

  const withoutAdapter = await fixture();
  try {
    await assert.rejects(
      withoutAdapter.gateway.activateEcosystem({}),
      (error) => error.message === "Prime gateway operation failed",
    );
  } finally {
    await withoutAdapter.cleanup();
  }
});
