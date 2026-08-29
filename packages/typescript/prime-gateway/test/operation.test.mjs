import assert from "node:assert/strict";
import test from "node:test";

import {
  PrimeGatewaySidecar,
  PrimeOperationGateway,
  PRIME_GATEWAY_IPC_PROTOCOL,
} from "../dist/src/index.js";

const effects = Object.freeze({
  credential_value_reads: 0,
  provider_model_requests: 0,
  network_operations: 0,
  package_manager_operations: 0,
  os_process_restart_operations: 0,
  external_telemetry_deliveries: 0,
  uploads: 0,
});

function transaction(operationId = "operation-1", requestRef = "private-request-1") {
  return {
    protocol: "asterion.operation/v1",
    operation_id: operationId,
    request: {
      protocol: "asterion.operation/v1",
      request_kind: "doctor-request",
      request_ref: requestRef,
      request_sha256: "a".repeat(64),
      media_type: "application/json",
      byte_count: 2,
      purpose: "operation.doctor.read",
      client_id: "client-1",
      session_id: "session-1",
      generation: 1,
      authority_revision: 1,
    },
    session_id: "session-1",
    client_id: "client-1",
    generation: 1,
    authority_revision: 1,
    authority_id: "authority-1",
    idempotency_key: "idempotency-1",
    feature_id: "operation.doctor",
    requested_at: "2026-08-10T03:00:00Z",
  };
}

function receipt(value, status = "succeeded") {
  return {
    protocol: "asterion.operation/v1",
    receipt_id: `receipt-${value.operation_id}`,
    operation_id: value.operation_id,
    request_ref: value.request.request_ref,
    request_sha256: value.request.request_sha256,
    purpose: value.request.purpose,
    session_id: value.session_id,
    client_id: value.client_id,
    generation: value.generation,
    authority_revision: value.authority_revision,
    authority_id: value.authority_id,
    idempotency_key: value.idempotency_key,
    feature_id: value.feature_id,
    status,
    reason_code: status === "succeeded" ? "operation-succeeded" : "operation-uncertain",
    receipt_ref: `receipt-ref-${value.operation_id}`,
    reconciliation_ref: status === "uncertain" ? "reconcile-1" : null,
    effect_counts: effects,
    completed_at: "2026-08-10T03:00:01Z",
  };
}

test("operation gateway replays one redacted receipt for an exact transaction", async () => {
  const calls = [];
  const gateway = new PrimeOperationGateway({
    async execute(value) {
      calls.push(value.operation_id);
      return receipt(value);
    },
    async cancel() { throw new Error("not reached"); },
    async reconcile() { throw new Error("not reached"); },
  });
  const first = await gateway.execute(transaction());
  const duplicate = await gateway.execute(transaction());

  assert.equal(calls.length, 1);
  assert.deepEqual(duplicate, first);
  assert.equal(JSON.stringify(first).includes("SENTINEL_SECRET"), false);
  assert.equal(first.effect_counts.network_operations, 0);
  await assert.rejects(
    gateway.execute(transaction("operation-1", "private-conflict")),
  );
  assert.equal(calls.length, 1);
});

test("operation gateway reconciles only an exact fenced uncertain transaction", async () => {
  const calls = [];
  const gateway = new PrimeOperationGateway({
    async execute(value) { return receipt(value, "uncertain"); },
    async cancel() { throw new Error("not reached"); },
    async reconcile(value) {
      calls.push(value.operation_id);
      return receipt(value);
    },
  });
  await gateway.execute(transaction("operation-uncertain"));
  const resolved = await gateway.reconcile(transaction("operation-uncertain"));

  assert.equal(resolved.status, "succeeded");
  assert.deepEqual(calls, ["operation-uncertain"]);
  await assert.rejects(
    gateway.reconcile(transaction("operation-uncertain", "private-conflict")),
  );
  assert.deepEqual(calls, ["operation-uncertain"]);
});

test("sidecar accepts only an empty private operation envelope", async () => {
  const gateway = new PrimeOperationGateway({
    async execute(value) { return receipt(value); },
    async cancel() { throw new Error("not reached"); },
    async reconcile() { throw new Error("not reached"); },
  });
  const sidecar = new PrimeGatewaySidecar({
    currentGeneration: 1,
    gateway: {
      async accept() {}, updateRemainingBudget() {}, eventsAfterCursor() { return []; }, async close() {},
    },
    privateValues: {},
    operation: gateway,
  });
  const result = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "operation-envelope-1",
    type: "operation.execute",
    transaction: transaction(),
    private: {},
  });
  assert.equal(result.type, "operation.receipt");
  assert.equal(JSON.stringify(result).includes("SENTINEL_SECRET"), false);
  assert.equal(result.receipt.effect_counts.network_operations, 0);

  const rejected = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "operation-envelope-2",
    type: "operation.execute",
    transaction: transaction("operation-2"),
    private: { body: "SENTINEL_SECRET" },
  });
  assert.deepEqual(rejected, {
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "operation-envelope-2",
    type: "error",
    code: "prime-gateway-sidecar-failed",
  });
});
