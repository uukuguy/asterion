import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  readdir,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  GatewayDurableStore,
  PrimeEcosystemAdapter,
  PrimeEcosystemError,
  validatePrimeEcosystemFrame,
} from "../dist/src/index.js";

const PRIVATE_BODY = "SENTINEL_PRIVATE_ECOSYSTEM_BODY";
const PRIVATE_LEASE = "mcp-lease:SENTINEL_PRIVATE_LEASE";
const PRIVATE_ERROR = "SENTINEL_PRIVATE_MODULE_ERROR";
const ARTIFACT_LOCK_DIGEST = "c0ffac5cb40be428ca4a60041694c2359bb1dd0c0ea182dabed1191247df03bc";
const MODULE_LOCK_DIGEST = "bcc22f2da837d9feab0d27fc177012f39d4ee00d7b5f7b0fc9ec877f74b922d2";

function digest(value) {
  const encoded = typeof value === "string"
    ? value
    : JSON.stringify(value, Object.keys(value).sort());
  return createHash("sha256").update(encoded).digest("hex");
}

function canonical(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonical).join(",")}]`;
  }
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}

function sha256Canonical(value) {
  return createHash("sha256").update(canonical(value)).digest("hex");
}

function expectedReceipt(frame, changes = {}) {
  return {
    authorityDigest: frame.authorityDigest,
    featureIds: frame.features,
    lifecycleCount: frame.resources.filter(({ kind }) => kind === "extension").length,
    mcpCount: frame.resources.filter(({ kind }) => kind === "mcp-server").length,
    modelCredentialReads: 0,
    ownedProcessCount: 0,
    packageCount: frame.resources.filter(({ kind }) => kind === "package").length,
    portfolioDigest: frame.portfolioDigest,
    providerOperations: 0,
    registrationCount: frame.registrations.length,
    resourceCount: frame.resources.length,
    status: "succeeded",
    ...changes,
  };
}

async function fixture() {
  const temporary = await realpath(
    await mkdtemp(join(tmpdir(), "asterion-prime-ecosystem-")),
  );
  const portfolioDigest = digest("portfolio-1");
  const projectionRoot = join(temporary, portfolioDigest);
  await mkdir(projectionRoot, { mode: 0o700 });
  await chmod(projectionRoot, 0o700);

  const definitions = [
    ["extension-1", "extension"],
    ["package-1", "package"],
  ];
  const resources = [];
  for (const [resourceId, kind] of definitions) {
    const projectionPath = join(projectionRoot, resourceId);
    const body = `${PRIVATE_BODY}:${resourceId}`;
    const filePath = join(projectionPath, "payload.txt");
    await mkdir(projectionPath, { mode: 0o700 });
    await chmod(projectionPath, 0o700);
    await writeFile(filePath, body, { mode: 0o600 });
    await chmod(filePath, 0o600);
    const files = [{
      relative_path: "payload.txt",
      sha256: digest(body),
      size_bytes: Buffer.byteLength(body),
    }];
    resources.push({
      contentDigest: sha256Canonical(files),
      kind,
      projectionPath,
      resourceId,
      scope: "project",
      source: {
        contentDigest: digest(`source:${resourceId}`),
        kind: "local-child",
        sourceId: `source-${resourceId}`,
        version: "1.0.0",
      },
      version: "1.0.0",
    });
  }
  resources.sort((left, right) => [
    left.kind,
    left.scope,
    left.resourceId,
    left.version,
    left.source.sourceId,
    left.source.kind,
    left.source.version,
    left.source.contentDigest,
    left.contentDigest,
  ].join("\0").localeCompare([
    right.kind,
    right.scope,
    right.resourceId,
    right.version,
    right.source.sourceId,
    right.source.kind,
    right.source.version,
    right.source.contentDigest,
    right.contentDigest,
  ].join("\0")));

  const registrations = [
    { extensionId: "extension-1", kind: "command", registrationId: "command-1", version: "1.0.0" },
    { extensionId: "extension-1", kind: "tool", registrationId: "tool-1", version: "1.0.0" },
  ];
  const frame = {
    artifactLockDigest: ARTIFACT_LOCK_DIGEST,
    authorityDigest: digest("authority-1@7"),
    effectId: `ecosystem:portfolio-1:${portfolioDigest.slice(0, 32)}`,
    features: [
      "ecosystem.extension-state-commands",
      "ecosystem.extensions-lifecycle",
      "ecosystem.packages",
      "ecosystem.tools",
    ],
    format: "asterion.prime-ecosystem-frame/v1",
    limits: {
      deadlineMs: 30_000,
      maxBytes: 8 * 1024 * 1024,
      maxEntries: 4096,
      maxProcesses: 1,
    },
    mcpCredentialLeaseId: PRIVATE_LEASE,
    moduleLockDigest: MODULE_LOCK_DIGEST,
    portfolioDigest,
    projectionRoot,
    registrations,
    resources,
  };
  const gatewayRoot = join(temporary, "gateway");
  return {
    frame,
    gatewayRoot,
    projectionRoot,
    temporary,
    async cleanup() {
      await rm(temporary, { recursive: true, force: true });
    },
  };
}

function clone(value) {
  return structuredClone(value);
}

test("validates and freezes the exact private ecosystem frame", async () => {
  const state = await fixture();
  try {
    const validated = validatePrimeEcosystemFrame(state.frame);

    assert.equal(validated.format, "asterion.prime-ecosystem-frame/v1");
    assert.equal(validated.resources[0].kind, "extension");
    assert.equal(Object.isFrozen(validated), true);
    assert.equal(Object.isFrozen(validated.resources), true);
    assert.equal(Object.isFrozen(validated.resources[0].source), true);
    assert.notEqual(validated, state.frame);
  } finally {
    await state.cleanup();
  }
});

test("rejects non-exact keys, noncanonical arrays, duplicates, and unsafe limits before bind", async () => {
  const state = await fixture();
  try {
    const extra = { ...clone(state.frame), provider: PRIVATE_BODY };
    const missing = clone(state.frame);
    delete missing.authorityDigest;
    const unsortedFeatures = clone(state.frame);
    unsortedFeatures.features.reverse();
    const unsortedResources = clone(state.frame);
    unsortedResources.resources.reverse();
    const unsortedRegistrations = clone(state.frame);
    unsortedRegistrations.registrations.reverse();
    const duplicateResource = clone(state.frame);
    duplicateResource.resources = [duplicateResource.resources[0], duplicateResource.resources[0]];
    const duplicateRegistration = clone(state.frame);
    duplicateRegistration.registrations = [
      duplicateRegistration.registrations[0],
      duplicateRegistration.registrations[0],
    ];
    const unsafe = clone(state.frame);
    unsafe.limits.deadlineMs = Number.MAX_SAFE_INTEGER + 1;
    const booleanInteger = clone(state.frame);
    booleanInteger.limits.maxEntries = true;
    const overCap = clone(state.frame);
    overCap.limits.maxBytes = 8 * 1024 * 1024 + 1;
    const byteBudget = clone(state.frame);
    byteBudget.limits.maxBytes = 1;
    const entryBudget = clone(state.frame);
    entryBudget.limits.maxEntries = 1;
    const processCap = clone(state.frame);
    processCap.limits.maxProcesses = 2;
    const deadlineCap = clone(state.frame);
    deadlineCap.limits.deadlineMs = 30_001;
    const nonAsciiResourceId = clone(state.frame);
    nonAsciiResourceId.resources[0].resourceId = "resource-\uE000";
    const nonAsciiRegistrationId = clone(state.frame);
    nonAsciiRegistrationId.registrations[0].registrationId = "registration-\u{10000}";

    for (const invalid of [
      extra,
      missing,
      unsortedFeatures,
      unsortedResources,
      unsortedRegistrations,
      duplicateResource,
      duplicateRegistration,
      unsafe,
      booleanInteger,
      overCap,
      byteBudget,
      entryBudget,
      processCap,
      deadlineCap,
      nonAsciiResourceId,
      nonAsciiRegistrationId,
    ]) {
      assert.throws(
        () => validatePrimeEcosystemFrame(invalid),
        (error) => error instanceof PrimeEcosystemError && error.message === "Prime ecosystem frame is invalid",
      );
    }
  } finally {
    await state.cleanup();
  }
});

test("rejects digest, source, lock, feature, path, and projection content drift", async () => {
  const state = await fixture();
  try {
    const effectDrift = clone(state.frame);
    effectDrift.effectId = `ecosystem:portfolio-1:${"f".repeat(32)}`;
    const sourceDrift = clone(state.frame);
    sourceDrift.resources[0].source.contentDigest = "A".repeat(64);
    const moduleDrift = clone(state.frame);
    moduleDrift.moduleLockDigest = "f".repeat(64);
    const artifactDrift = clone(state.frame);
    artifactDrift.artifactLockDigest = "f".repeat(64);
    const featureDrift = clone(state.frame);
    featureDrift.features = ["ecosystem.packages"];
    const outside = clone(state.frame);
    outside.resources[0].projectionPath = join(state.temporary, "outside");
    const contentDrift = clone(state.frame);
    contentDrift.resources[0].contentDigest = "f".repeat(64);

    for (const invalid of [
      effectDrift,
      sourceDrift,
      moduleDrift,
      artifactDrift,
      featureDrift,
      outside,
      contentDrift,
    ]) {
      assert.throws(() => validatePrimeEcosystemFrame(invalid), PrimeEcosystemError);
    }
  } finally {
    await state.cleanup();
  }
});

test("rejects projection roots, directories, and files with non-private modes", async () => {
  for (const target of ["root", "resource", "file"]) {
    const state = await fixture();
    try {
      const resourcePath = state.frame.resources[0].projectionPath;
      const targetPath = target === "root"
        ? state.projectionRoot
        : target === "resource"
          ? resourcePath
          : join(resourcePath, "payload.txt");
      await chmod(targetPath, target === "file" ? 0o644 : 0o755);
      assert.throws(() => validatePrimeEcosystemFrame(state.frame), PrimeEcosystemError);
    } finally {
      await state.cleanup();
    }
  }
});

test("rejects special permission bits on projection roots, directories, and files", async () => {
  for (const [target, mode] of [
    ["root", 0o1700],
    ["resource", 0o2700],
    ["file", 0o4600],
  ]) {
    const state = await fixture();
    try {
      const resourcePath = state.frame.resources[0].projectionPath;
      const targetPath = target === "root"
        ? state.projectionRoot
        : target === "resource"
          ? resourcePath
          : join(resourcePath, "payload.txt");
      await chmod(targetPath, mode);
      assert.throws(() => validatePrimeEcosystemFrame(state.frame), PrimeEcosystemError);
    } finally {
      await state.cleanup();
    }
  }
});

test("hashes the complete projection manifest in global relative-path order", async () => {
  const state = await fixture();
  try {
    const resource = state.frame.resources[0];
    await rm(join(resource.projectionPath, "payload.txt"));
    await mkdir(join(resource.projectionPath, "a"), { mode: 0o700 });
    await chmod(join(resource.projectionPath, "a"), 0o700);
    await writeFile(join(resource.projectionPath, "a", "x"), "nested", { mode: 0o600 });
    await chmod(join(resource.projectionPath, "a", "x"), 0o600);
    await writeFile(join(resource.projectionPath, "a."), "sibling", { mode: 0o600 });
    await chmod(join(resource.projectionPath, "a."), 0o600);
    resource.contentDigest = sha256Canonical([
      { relative_path: "a.", sha256: digest("sibling"), size_bytes: 7 },
      { relative_path: "a/x", sha256: digest("nested"), size_bytes: 6 },
    ]);
    assert.doesNotThrow(() => validatePrimeEcosystemFrame(state.frame));
  } finally {
    await state.cleanup();
  }
});

test("orders projection paths by Unicode code point like Python", async () => {
  const state = await fixture();
  try {
    const resource = state.frame.resources[0];
    const bmpPath = "\uE000";
    const supplementaryPath = "\u{10000}";
    await rm(join(resource.projectionPath, "payload.txt"));
    await writeFile(join(resource.projectionPath, bmpPath), "bmp", { mode: 0o600 });
    await chmod(join(resource.projectionPath, bmpPath), 0o600);
    await writeFile(
      join(resource.projectionPath, supplementaryPath),
      "supplementary",
      { mode: 0o600 },
    );
    await chmod(join(resource.projectionPath, supplementaryPath), 0o600);
    resource.contentDigest = sha256Canonical([
      { relative_path: bmpPath, sha256: digest("bmp"), size_bytes: 3 },
      {
        relative_path: supplementaryPath,
        sha256: digest("supplementary"),
        size_bytes: 13,
      },
    ]);

    assert.doesNotThrow(() => validatePrimeEcosystemFrame(state.frame));
  } finally {
    await state.cleanup();
  }
});

test("binds the exact ecosystem effect before Prime lifecycle", async () => {
  const state = await fixture();
  try {
    const calls = [];
    const store = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
    const bind = store.bindEcosystemEffect.bind(store);
    const commit = store.commitEcosystemEffectResult.bind(store);
    store.bindEcosystemEffect = async (frame) => {
      calls.push("bind");
      return bind(frame);
    };
    store.commitEcosystemEffectResult = async (effectId, receipt) => {
      calls.push("commit");
      return commit(effectId, receipt);
    };
    const module = {
      calls: 0,
      async activate(frame) {
        calls.push("module-start");
        this.calls += 1;
        assert.notEqual(store.ecosystemEffectBinding(frame.effectId), undefined);
        const receipt = expectedReceipt(frame);
        calls.push("module-end");
        return receipt;
      },
    };

    const result = await new PrimeEcosystemAdapter({ store, module }).activate(state.frame);

    assert.deepEqual(calls, ["bind", "module-start", "module-end", "commit"]);
    assert.equal(module.calls, 1);
    assert.equal(result.status, "succeeded");
    assert.equal(result.providerOperations, 0);
    assert.deepEqual(store.ecosystemEffectResult(state.frame.effectId), result);
  } finally {
    await state.cleanup();
  }
});

test("validation rejects before durable bind or module activation", async () => {
  const state = await fixture();
  try {
    const calls = [];
    const store = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
    const bind = store.bindEcosystemEffect.bind(store);
    store.bindEcosystemEffect = async (frame) => {
      calls.push("bind");
      return bind(frame);
    };
    const module = {
      async activate() {
        calls.push("module");
        return {};
      },
    };
    const invalid = { ...clone(state.frame), body: PRIVATE_BODY };

    await assert.rejects(
      new PrimeEcosystemAdapter({ store, module }).activate(invalid),
      PrimeEcosystemError,
    );
    assert.deepEqual(calls, []);
  } finally {
    await state.cleanup();
  }
});

test("returns an existing terminal result unchanged without replaying the module", async () => {
  const state = await fixture();
  try {
    const store = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
    const firstModule = { async activate(frame) { return expectedReceipt(frame); } };
    const first = await new PrimeEcosystemAdapter({ store, module: firstModule }).activate(state.frame);
    const reopened = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
    const failModule = {
      calls: 0,
      async activate() {
        this.calls += 1;
        throw new Error(PRIVATE_ERROR);
      },
    };

    const replayed = await new PrimeEcosystemAdapter({
      store: reopened,
      module: failModule,
    }).activate(state.frame);

    assert.deepEqual(replayed, first);
    assert.equal(failModule.calls, 0);
  } finally {
    await state.cleanup();
  }
});

test("concurrent duplicate activation invokes the module once and fences the duplicate", async () => {
  const state = await fixture();
  let releaseModule;
  try {
    const store = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
    let moduleStarted;
    const started = new Promise((resolve) => { moduleStarted = resolve; });
    const gate = new Promise((resolve) => { releaseModule = resolve; });
    const module = {
      calls: 0,
      async activate(frame) {
        this.calls += 1;
        moduleStarted();
        await gate;
        return expectedReceipt(frame);
      },
    };
    const adapter = new PrimeEcosystemAdapter({ store, module });
    const firstPromise = adapter.activate(state.frame);
    await started;
    const secondPromise = adapter.activate(state.frame);
    const duplicate = await Promise.race([
      secondPromise,
      new Promise((resolve) => setTimeout(() => resolve("timed-out"), 100)),
    ]);
    releaseModule();
    const first = await firstPromise;
    const second = await secondPromise;
    assert.notEqual(duplicate, "timed-out");
    assert.equal(module.calls, 1);
    assert.equal(first.status, "uncertain");
    assert.deepEqual(second, first);
  } finally {
    releaseModule?.();
    await state.cleanup();
  }
});

test("reopen fences a bound nonterminal effect as uncertain", async () => {
  const state = await fixture();
  try {
    const boundStore = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
    await boundStore.bindEcosystemEffect(state.frame);
    const reopened = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
    const failModule = {
      calls: 0,
      async activate() {
        this.calls += 1;
        throw new Error(PRIVATE_ERROR);
      },
    };

    const result = await new PrimeEcosystemAdapter({
      store: reopened,
      module: failModule,
    }).activate(state.frame);

    assert.equal(result.status, "uncertain");
    assert.equal(failModule.calls, 0);
    assert.deepEqual(reopened.ecosystemEffectResult(state.frame.effectId), result);
  } finally {
    await state.cleanup();
  }
});

test("commit write failure reopens as uncertain without replaying the module", async () => {
  const state = await fixture();
  try {
    await GatewayDurableStore.open(state.gatewayRoot, "session-1");
    let writes = 0;
    const faulted = await GatewayDurableStore.open(state.gatewayRoot, "session-1", {
      faultInjector(stage) {
        if (stage === "before_write" && ++writes === 2) {
          throw new Error("SENTINEL_ECOSYSTEM_COMMIT_WRITE");
        }
      },
    });
    const module = {
      calls: 0,
      async activate(frame) {
        this.calls += 1;
        return expectedReceipt(frame);
      },
    };
    await assert.rejects(
      new PrimeEcosystemAdapter({ store: faulted, module }).activate(state.frame),
      (error) => error.message === "Prime gateway durable write failed",
    );
    assert.equal(module.calls, 1);
    const reopened = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
    const replayModule = {
      calls: 0,
      async activate() {
        this.calls += 1;
        return {};
      },
    };
    const recovered = await new PrimeEcosystemAdapter({
      store: reopened,
      module: replayModule,
    }).activate(state.frame);
    assert.equal(recovered.status, "uncertain");
    assert.equal(replayModule.calls, 0);
  } finally {
    await state.cleanup();
  }
});

test("durable commit rejects receipt identity and expected-count drift", async () => {
  for (const drift of [
    { effectId: "ecosystem:override:" + "0".repeat(32) },
    { resourceCount: 99 },
    { featureIds: ["ecosystem.unexpected"] },
  ]) {
    const state = await fixture();
    try {
      const store = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
      await store.bindEcosystemEffect(state.frame);
      await assert.rejects(
        store.commitEcosystemEffectResult(
          state.frame.effectId,
          { ...expectedReceipt(state.frame), ...drift },
        ),
        (error) => error.message === "Prime gateway durable record conflicts",
      );
    } finally {
      await state.cleanup();
    }
  }
});

test("replay rejects a terminal result whose expected count drifts from its binding", async () => {
  const state = await fixture();
  try {
    const store = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
    await new PrimeEcosystemAdapter({
      store,
      module: { async activate(frame) { return expectedReceipt(frame); } },
    }).activate(state.frame);
    const recordsRoot = join(state.gatewayRoot, "public", "records");
    const recordName = (await readdir(recordsRoot)).sort().at(-1);
    const recordPath = join(recordsRoot, recordName);
    const record = JSON.parse(await readFile(recordPath, "utf8"));
    record.payload.resourceCount += 1;
    record.payload_digest = sha256Canonical({
      kind: record.kind,
      record_id: record.record_id,
      payload: record.payload,
    });
    const { digest: _digest, ...body } = record;
    record.digest = sha256Canonical(body);
    await writeFile(recordPath, `${canonical(record)}\n`, { mode: 0o600 });
    await assert.rejects(
      GatewayDurableStore.open(state.gatewayRoot, "session-1"),
      (error) => error.message === "Prime gateway durable store is corrupt",
    );
  } finally {
    await state.cleanup();
  }
});

test("commits redacted uncertainty for module failures and receipt drift", async () => {
  const cases = [
    { async activate() { throw new Error(PRIVATE_ERROR); } },
    { async activate(frame) { return expectedReceipt(frame, { providerOperations: 1 }); } },
    { async activate(frame) { return expectedReceipt(frame, { modelCredentialReads: 1 }); } },
    { async activate(frame) { return expectedReceipt(frame, { lifecycleCount: 0 }); } },
    { async activate(frame) { return { ...expectedReceipt(frame), error: PRIVATE_BODY }; } },
  ];
  for (const module of cases) {
    const state = await fixture();
    try {
      const store = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
      const result = await new PrimeEcosystemAdapter({ store, module }).activate(state.frame);
      assert.equal(result.status, "uncertain");
      assert.equal(JSON.stringify(result).includes("SENTINEL"), false);
    } finally {
      await state.cleanup();
    }
  }
});

test("commits every exact terminal status without lifecycle replay", async () => {
  for (const status of ["failed", "cancelled", "uncertain"]) {
    const state = await fixture();
    try {
      const store = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
      const module = {
        calls: 0,
        async activate(frame) {
          this.calls += 1;
          return expectedReceipt(frame, { status });
        },
      };
      const result = await new PrimeEcosystemAdapter({ store, module }).activate(state.frame);
      assert.equal(result.status, status);
      assert.equal(module.calls, 1);
      const replay = await new PrimeEcosystemAdapter({ store, module }).activate(state.frame);
      assert.deepEqual(replay, result);
      assert.equal(module.calls, 1);
    } finally {
      await state.cleanup();
    }
  }
});

test("public frame digest excludes projection paths and MCP lease identities", async () => {
  const first = await fixture();
  const second = await fixture();
  try {
    second.frame.mcpCredentialLeaseId = "mcp-lease:another-private-lease";
    const firstStore = await GatewayDurableStore.open(first.gatewayRoot, "session-1");
    const secondStore = await GatewayDurableStore.open(second.gatewayRoot, "session-1");
    const firstBinding = await firstStore.bindEcosystemEffect(first.frame);
    const secondBinding = await secondStore.bindEcosystemEffect(second.frame);

    assert.equal(firstBinding.disposition, "created");
    assert.equal(secondBinding.disposition, "created");
    assert.equal(firstBinding.binding.frameDigest, secondBinding.binding.frameDigest);
    assert.equal(JSON.stringify(firstBinding.binding).includes(first.projectionRoot), false);
    assert.equal(JSON.stringify(secondBinding.binding).includes(second.frame.mcpCredentialLeaseId), false);
  } finally {
    await first.cleanup();
    await second.cleanup();
  }
});

test("a pre-existing effect rejects public frame digest drift without module replay", async () => {
  const state = await fixture();
  try {
    const store = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
    await store.bindEcosystemEffect(state.frame);
    const drifted = clone(state.frame);
    drifted.authorityDigest = "f".repeat(64);
    const module = {
      calls: 0,
      async activate() {
        this.calls += 1;
        return {};
      },
    };

    await assert.rejects(
      new PrimeEcosystemAdapter({ store, module }).activate(drifted),
      (error) => error.message === "Prime gateway durable record conflicts",
    );
    assert.equal(module.calls, 0);
    assert.equal(store.ecosystemEffectResult(state.frame.effectId), undefined);
  } finally {
    await state.cleanup();
  }
});

test("durable public bindings, results, snapshots, and errors exclude private ecosystem values", async () => {
  const state = await fixture();
  try {
    const store = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
    const result = await new PrimeEcosystemAdapter({
      store,
      module: { async activate(frame) { return expectedReceipt(frame); } },
    }).activate(state.frame);
    const publicValues = JSON.stringify({
      binding: store.ecosystemEffectBinding(state.frame.effectId),
      result,
      snapshot: store.snapshot(),
    });
    assert.equal(publicValues.includes(state.projectionRoot), false);
    assert.equal(publicValues.includes(PRIVATE_LEASE), false);
    assert.equal(publicValues.includes(PRIVATE_BODY), false);

    const invalid = { ...clone(state.frame), body: PRIVATE_BODY };
    assert.throws(
      () => validatePrimeEcosystemFrame(invalid),
      (error) =>
        error instanceof PrimeEcosystemError &&
        !error.message.includes(PRIVATE_BODY) &&
        !error.message.includes(state.projectionRoot) &&
        !error.message.includes(PRIVATE_LEASE),
    );
  } finally {
    await state.cleanup();
  }
});
