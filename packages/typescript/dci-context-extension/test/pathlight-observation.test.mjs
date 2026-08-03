import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import {
  closeSync,
  constants,
  fstatSync,
  fsyncSync,
  mkdtempSync,
  openSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import ts from "../../asterion-runtime/node_modules/typescript/lib/typescript.js";

const sourceUrl = new URL("../src/dci-pathlight-observation.ts", import.meta.url);
const fixtureRoot = new URL("../../../../tests/fixtures/pathlight-provider-request/v1/", import.meta.url);

async function loadObservation({
  fd = 9,
  contract = "dci.pathlight-provider-request-capture/v1",
  recordLimit,
  generationLimit,
} = {}) {
  process.env.ASTERION_DCI_PATHLIGHT_PRIVATE_FD = String(fd);
  process.env.ASTERION_DCI_PATHLIGHT_CAPTURE_CONTRACT = contract;
  let source = readFileSync(sourceUrl, "utf8");
  if (recordLimit !== undefined) {
    source = source.replace(
      "const MAX_PRIVATE_RECORD_BYTES = 64 * 1024 * 1024;",
      `const MAX_PRIVATE_RECORD_BYTES = ${recordLimit};`,
    );
  }
  if (generationLimit !== undefined) {
    source = source.replace(
      "const MAX_NATIVE_GENERATION_BYTES = 512 * 1024 * 1024;",
      `const MAX_NATIVE_GENERATION_BYTES = ${generationLimit};`,
    );
  }
  const result = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
      verbatimModuleSyntax: true,
    },
    reportDiagnostics: true,
  });
  assert.deepEqual(result.diagnostics ?? [], []);
  const encoded = Buffer.from(result.outputText).toString("base64");
  const loaded = await import(`data:text/javascript;base64,${encoded}#${Date.now()}-${Math.random()}`);
  assert.equal("ASTERION_DCI_PATHLIGHT_PRIVATE_FD" in process.env, false);
  assert.equal("ASTERION_DCI_PATHLIGHT_CAPTURE_CONTRACT" in process.env, false);
  return loaded;
}

class FakePi {
  constructor({ beforeAppend } = {}) {
    this.registrations = [];
    this.entries = [];
    this.beforeAppend = beforeAppend;
  }

  on(name, handler) {
    this.registrations.push({ name, handler });
  }

  appendEntry(customType, data) {
    this.beforeAppend?.();
    this.entries.push({ customType, data });
  }
}

async function withPrivateFile(run) {
  const root = mkdtempSync(join(tmpdir(), "asterion-pathlight-observation-"));
  const path = join(root, "provider-requests.jsonl");
  const fd = openSync(
    path,
    constants.O_CREAT | constants.O_EXCL | constants.O_RDWR,
    0o600,
  );
  try {
    assert.equal(fstatSync(fd).mode & 0o777, 0o600);
    return await run({ fd, path });
  } finally {
    closeSync(fd);
    rmSync(root, { recursive: true, force: true });
  }
}

function readRecords(path, fd) {
  fsyncSync(fd);
  const text = readFileSync(path, "utf8");
  return text === "" ? [] : text.trimEnd().split("\n").map(JSON.parse);
}

function fixture(name) {
  return JSON.parse(readFileSync(new URL(name, fixtureRoot), "utf8"));
}

function nestedArray(depth, leaf = "leaf") {
  let value = leaf;
  for (let index = 0; index < depth; index += 1) value = [value];
  return value;
}

test("hook writes private raw first, appends only a safe summary, and preserves task input", async () => {
  await withPrivateFile(async ({ fd, path }) => {
    const extension = await loadObservation({ fd });
    const payload = {
      instructions: "SENTINEL_PRIVATE_PAYLOAD",
      messages: [{ role: "user", content: "question" }],
      tools: [{ name: "SENTINEL_PRIVATE_TOOL", input_schema: { sentinelPrivateKey: "secret" } }],
      provider: "SENTINEL_PROVIDER",
      model: "SENTINEL_MODEL",
      answer: "SENTINEL_ANSWER",
      config: { mode: "SENTINEL_CONFIG" },
    };
    const before = structuredClone(payload);
    const pi = new FakePi({ beforeAppend: () => assert.notEqual(fstatSync(fd).size, 0) });
    extension.default(pi);

    assert.deepEqual(pi.registrations.map(({ name }) => name), ["before_provider_request"]);
    const returned = pi.registrations[0].handler(
      { type: "before_provider_request", payload },
      {},
    );
    const [privateRecord] = readRecords(path, fd);

    assert.equal(returned, undefined);
    assert.deepEqual(payload, before);
    assert.equal(pi.entries[0].customType, "dci-provider-request-observation");
    assert.equal(JSON.stringify(pi.entries).includes("SENTINEL_PRIVATE_PAYLOAD"), false);
    assert.equal(JSON.stringify(pi.entries).includes("sentinelPrivateKey"), false);
    assert.equal(JSON.stringify(pi.entries).includes("SENTINEL_PROVIDER"), false);
    assert.equal(JSON.stringify(pi.entries).includes("SENTINEL_MODEL"), false);
    assert.equal(JSON.stringify(pi.entries).includes("SENTINEL_ANSWER"), false);
    assert.equal(JSON.stringify(pi.entries).includes("SENTINEL_CONFIG"), false);
    assert.equal(privateRecord.payload_json.includes("SENTINEL_PRIVATE_PAYLOAD"), true);
    assert.equal(privateRecord.payload_sha256, pi.entries[0].data.payload_sha256);
    assert.equal(privateRecord.summary_sha256, pi.entries[0].data.summary_sha256);
    assert.deepEqual(Object.keys(privateRecord).sort(), [
      "captured_at",
      "payload_bytes",
      "payload_json",
      "payload_sha256",
      "request_index",
      "schema",
      "shape_sha256",
      "summary_sha256",
    ]);
    assert.deepEqual(Object.keys(pi.entries[0].data).sort(), [
      "capture_status",
      "field_count",
      "leaf_count",
      "missing_evidence",
      "payload_bytes",
      "payload_sha256",
      "request_index",
      "schema",
      "segments",
      "shape_sha256",
      "summary_sha256",
      "text_characters",
    ]);
  });
});

test("canonical fixtures close simple and tool-result observations", async () => {
  const extension = await loadObservation();
  for (const name of ["valid-simple.json", "valid-tools.json"]) {
    const value = fixture(name);
    assert.deepEqual(extension.summarizeProviderPayload(value.payload), value.summary, name);
  }
  const invalid = fixture("invalid-summary.json");
  assert.notDeepEqual(extension.summarizeProviderPayload(invalid.payload), invalid.summary);
});

test("shape projection is independent of object key order and preserves array semantics", async () => {
  const extension = await loadObservation();
  const first = extension.summarizeProviderPayload({
    messages: [{ role: "user", content: ["first", "second"] }],
    nested: { alpha: 1, beta: true },
  });
  const second = extension.summarizeProviderPayload({
    nested: { beta: true, alpha: 1 },
    messages: [{ content: ["first", "second"], role: "user" }],
  });
  const reversed = extension.summarizeProviderPayload({
    messages: [{ role: "user", content: ["second", "first"] }],
    nested: { alpha: 1, beta: true },
  });

  assert.notEqual(first.payload_sha256, second.payload_sha256);
  assert.equal(first.shape_sha256, second.shape_sha256);
  assert.equal(first.summary_sha256, second.summary_sha256);
  assert.notEqual(first.segments[0].content_sha256, reversed.segments[0].content_sha256);
});

test("segments require explicit roles and recognize instructions and tool results", async () => {
  const extension = await loadObservation();
  const observed = extension.summarizeProviderPayload({
    instructions: "system contract",
    messages: [
      { role: "system", content: "system message" },
      { role: "user", content: "question" },
      { role: "assistant", content: "answer draft" },
      { role: "tool", tool_call_id: "call-1", content: "tool result" },
      { content: "unlabelled" },
    ],
  });

  assert.deepEqual(observed.segments.map(({ role }) => role), [
    "system", "system", "user", "assistant", "tool-result", "unknown",
  ]);
  assert.equal(observed.segments[0].structure_kind, "contract");
  assert.equal(observed.segments[4].structure_kind, "tool-result");
  assert.match(observed.segments[4].source_call_sha256, /^[0-9a-f]{64}$/);
  assert.equal(observed.segments[5].missing_evidence, true);
});

test("unknown JSON structures remain body-free and explicitly incomplete", async () => {
  const extension = await loadObservation();
  const observed = extension.summarizeProviderPayload({
    sentinelUnknownKey: { nested: "SENTINEL_UNKNOWN_VALUE" },
  });
  assert.deepEqual(observed.segments.map(({ role, structure_kind, missing_evidence }) => ({
    role, structure_kind, missing_evidence,
  })), [{ role: "unknown", structure_kind: "missing", missing_evidence: true }]);
  assert.equal(JSON.stringify(observed).includes("sentinelUnknownKey"), false);
  assert.equal(JSON.stringify(observed).includes("SENTINEL_UNKNOWN_VALUE"), false);
});

test("strict JSON rejects circular, BigInt, non-finite, and unsupported values with one fixed error", async () => {
  const extension = await loadObservation();
  const circular = {};
  circular.self = circular;
  for (const payload of [
    circular,
    { value: 1n },
    { value: Number.NaN },
    { value: Number.POSITIVE_INFINITY },
    { value: undefined },
  ]) {
    assert.throws(
      () => extension.summarizeProviderPayload(payload),
      (error) => error instanceof Error && error.message === "provider request observation unavailable",
    );
  }
});

test("serialized JSON structural depth accepts 128 and rejects 129", async () => {
  const extension = await loadObservation();
  assert.doesNotThrow(() => extension.summarizeProviderPayload(
    nestedArray(128, 'string delimiters [{]} " \\ stay inert'),
  ));
  assert.throws(
    () => extension.summarizeProviderPayload(nestedArray(129, "SENTINEL_PRIVATE_DEPTH")),
    (error) => error instanceof Error
      && error.message === "provider request observation unavailable"
      && error.message.includes("SENTINEL_PRIVATE_DEPTH") === false,
  );
});

test("over-depth hook payload degrades without writing or leaking its sentinel", async () => {
  await withPrivateFile(async ({ fd, path }) => {
    const extension = await loadObservation({ fd });
    const pi = new FakePi();
    extension.default(pi);

    assert.equal(pi.registrations[0].handler(
      { type: "before_provider_request", payload: nestedArray(129, "SENTINEL_PRIVATE_DEPTH") },
      {},
    ), undefined);

    assert.equal(readRecords(path, fd).length, 0);
    assert.equal(JSON.stringify(pi.entries).includes("SENTINEL_PRIVATE_DEPTH"), false);
    assert.equal(pi.entries[0].data.capture_status, "missing");
    assert.equal(pi.entries[0].data.error, "provider request observation unavailable");
  });
});

test("complete descriptor writes tolerate partial writes", async () => {
  const extension = await loadObservation();
  const chunks = [];
  extension.writeAll(17, Buffer.from("abcdefghij"), (fd, value, offset, length) => {
    assert.equal(fd, 17);
    const written = Math.min(3, length);
    chunks.push(Buffer.from(value.subarray(offset, offset + written)));
    return written;
  });
  assert.equal(Buffer.concat(chunks).toString("utf8"), "abcdefghij");
});

test("closed private descriptor degrades safely after the raw write attempt", async () => {
  const root = mkdtempSync(join(tmpdir(), "asterion-pathlight-closed-"));
  const path = join(root, "capture.jsonl");
  const fd = openSync(path, constants.O_CREAT | constants.O_EXCL | constants.O_RDWR, 0o600);
  const extension = await loadObservation({ fd });
  closeSync(fd);
  try {
    const pi = new FakePi();
    extension.default(pi);
    assert.doesNotThrow(() => pi.registrations[0].handler(
      { type: "before_provider_request", payload: { messages: [] } },
      {},
    ));
    assert.deepEqual(pi.entries, [{
      customType: "dci-provider-request-observation",
      data: {
        schema: "dci.provider-request-observation/v1",
        request_index: 1,
        capture_status: "missing",
        missing_evidence: ["provider-request-private"],
        error: "provider request observation unavailable",
      },
    }]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("append failure never escapes and leaves the private record for fail-closed reconciliation", async () => {
  await withPrivateFile(async ({ fd, path }) => {
    const extension = await loadObservation({ fd });
    const pi = new FakePi();
    pi.appendEntry = () => { throw new Error("SENTINEL_APPEND_FAILURE"); };
    extension.default(pi);
    assert.doesNotThrow(() => pi.registrations[0].handler(
      { type: "before_provider_request", payload: { messages: [] } },
      {},
    ));
    assert.equal(readRecords(path, fd).length, 1);
  });
});

test("serialization failures never escape the hook or enter private evidence", async () => {
  await withPrivateFile(async ({ fd, path }) => {
    const extension = await loadObservation({ fd });
    const pi = new FakePi();
    extension.default(pi);
    assert.doesNotThrow(() => pi.registrations[0].handler(
      { type: "before_provider_request", payload: { privateKey: 1n } },
      {},
    ));
    assert.equal(readRecords(path, fd).length, 0);
    assert.equal(JSON.stringify(pi.entries).includes("privateKey"), false);
    assert.equal(pi.entries[0].data.capture_status, "missing");
  });
});

test("private record and native generation limits are inclusive and overflow only observation", async () => {
  const extension = await loadObservation();
  const mib = 1024 * 1024;
  assert.equal(extension.captureFitsLimits(64 * mib, 448 * mib), true);
  assert.equal(extension.captureFitsLimits(64 * mib + 1, 0), false);
  assert.equal(extension.captureFitsLimits(1, 512 * mib - 1), true);
  assert.equal(extension.captureFitsLimits(1, 512 * mib), false);
});

test("record and cumulative overflow skip raw bytes and return undefined", async () => {
  await withPrivateFile(async ({ fd, path }) => {
    const recordLimited = await loadObservation({ fd, recordLimit: 256 });
    const recordPi = new FakePi();
    recordLimited.default(recordPi);
    assert.equal(recordPi.registrations[0].handler(
      { type: "before_provider_request", payload: { messages: [{ role: "user", content: "x".repeat(512) }] } },
      {},
    ), undefined);
    assert.equal(readRecords(path, fd).length, 0);
    assert.equal(recordPi.entries[0].data.capture_status, "missing");
  });

  await withPrivateFile(async ({ fd, path }) => {
    const generationLimited = await loadObservation({
      fd,
      recordLimit: 4096,
      generationLimit: 1200,
    });
    const pi = new FakePi();
    generationLimited.default(pi);
    for (let index = 0; index < 10; index += 1) {
      assert.equal(pi.registrations[0].handler(
        { type: "before_provider_request", payload: { messages: [] } },
        {},
      ), undefined);
    }
    const captured = pi.entries.filter(({ data }) => data.capture_status === "captured");
    const missing = pi.entries.filter(({ data }) => data.capture_status === "missing");
    assert.notEqual(captured.length, 0);
    assert.notEqual(missing.length, 0);
    assert.equal(readRecords(path, fd).length, captured.length);
  });
});

test("environment capture configuration is fixed at module load", async () => {
  await withPrivateFile(async ({ fd, path }) => {
    const extension = await loadObservation({ fd });
    process.env.ASTERION_DCI_PATHLIGHT_PRIVATE_FD = "999999";
    process.env.ASTERION_DCI_PATHLIGHT_CAPTURE_CONTRACT = "SENTINEL_LATE_CONTRACT";
    try {
      const pi = new FakePi();
      extension.default(pi);
      pi.registrations[0].handler(
        { type: "before_provider_request", payload: { messages: [] } },
        {},
      );
      assert.equal(readRecords(path, fd).length, 1);
    } finally {
      delete process.env.ASTERION_DCI_PATHLIGHT_PRIVATE_FD;
      delete process.env.ASTERION_DCI_PATHLIGHT_CAPTURE_CONTRACT;
    }
  });
});
