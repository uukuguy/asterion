import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import {
  fstatSync,
  closeSync,
  realpathSync,
  mkdtempSync,
  openSync,
  rmSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const loaderUrl = new URL(
  "../src/asterion/runtimes/resources/asterion_pi_extension_loader.mjs",
  import.meta.url,
);

function dependencyFixture(providerSource, extensionSource) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "asterion-pi-deps-")));
  const held = [];
  const pin = (name, source) => {
    const bytes = Buffer.from(source);
    const path = join(root, name);
    writeFileSync(path, bytes);
    const fd = openSync(path, "r");
    held.push(fd);
    return { fd, digest: createHash("sha256").update(bytes).digest("hex") };
  };
  const source = pin("extension.mjs", extensionSource);
  const provider = pin("provider.mjs", providerSource);
  const closureLock = pin("closure.json", "{}");
  const artifactLock = pin("artifact.json", "{}");
  const rootFd = openSync(root, "r");
  held.push(rootFd);
  const details = fstatSync(rootFd, {bigint: true});
  const metadata = {
    provider, closureLock, artifactLock,
    sourceRoot: {path: root, fd: rootFd, dev: String(details.dev), ino: String(details.ino)},
    exports: {value: "string"},
  };
  process.env.ASTERION_PI_EXTENSION_SOURCE_FD = String(source.fd);
  process.env.ASTERION_PI_EXTENSION_SOURCE_NAME = "extension.mjs";
  process.env.ASTERION_PI_EXTENSION_SOURCE_SHA256 = source.digest;
  process.env.ASTERION_PI_EXTENSION_DEPENDENCIES = JSON.stringify(metadata);
  return {metadata, held, cleanup() {
    for (const fd of held) {try {closeSync(fd);} catch {}}
    delete process.env.ASTERION_PI_EXTENSION_DEPENDENCIES;
    rmSync(root, {recursive: true, force: true});
  }};
}

test("loader supplies an exact frozen mapping and owns provider teardown", async () => {
  const fixture = dependencyFixture(
    'export function verifyDependencies() {}\nexport function createDependencies() {return {dependencies: {value: "original"}, close() {globalThis.__dependencyClosed = true;}};}',
    'export default (pi, dependencies) => { if (!Object.isFrozen(dependencies)) throw Error(); pi.registerTool({name: dependencies.value}); };',
  );
  const names = [];
  const hooks = {};
  try {
    const loader = await import(loaderUrl);
    await loader.default({registerTool: (tool) => names.push(tool.name), on: (name, callback) => {hooks[name] = callback;}});
    assert.deepEqual(names, ["original"]);
    assert.equal(process.env.ASTERION_PI_EXTENSION_DEPENDENCIES, undefined);
    await hooks.session_shutdown();
    assert.equal(globalThis.__dependencyClosed, true);
    for (const fd of fixture.held) assert.throws(() => fstatSync(fd));
  } finally { delete globalThis.__dependencyClosed; fixture.cleanup(); }
});

test("locked application provider uses the verified modules and releases its guard", () => {
  const script = `
    import assert from "node:assert/strict";
    import {readFileSync, realpathSync} from "node:fs";
    import {pathToFileURL} from "node:url";
    const providerPath = "tools/build_asterion_prime_compaction_lock.mjs";
    assert.equal(typeof (await import(pathToFileURL(realpathSync(providerPath)))).createDependencies, "function", "locked dependency factory missing");
    const provider = await import("data:text/javascript;base64,"+readFileSync(providerPath).toString("base64"));
    assert.equal(typeof provider.createDependencies, "function", "locked dependency factory missing");
    const sourceRoot = realpathSync("3th-party/prime-agent");
    const context = {sourceRoot,
      lockBytes: readFileSync("packages/typescript/asterion-prime-extension/resources/pi-compaction-lock.json"),
      artifactLockBytes: readFileSync("packages/typescript/prime-gateway/resources/prime-artifact-lock.json")};
    await provider.verifyDependencies(context);
    const handle = await provider.createDependencies(context);
    try {
      assert(Object.isFrozen(handle.dependencies));
      assert.deepEqual(Object.keys(handle.dependencies).sort(), ["buildSessionContext", "buildSummarizationPrompt", "convertToLlm", "prepareCompaction", "serializeConversation", "summarizationSystemPrompt", "turnPrefixPrompt"]);
      const actual = await import(pathToFileURL(sourceRoot+"/packages/coding-agent/dist/core/compaction/compaction.js"));
      assert.equal(handle.dependencies.prepareCompaction, actual.prepareCompaction);
      assert.equal(handle.dependencies.buildSummarizationPrompt, actual.buildSummarizationPrompt);
      assert.equal(typeof handle.dependencies.summarizationSystemPrompt, "string");
      assert.equal(typeof handle.dependencies.turnPrefixPrompt, "string");
      await assert.rejects(import("data:text/javascript,export default 1"));
    } finally {handle.close();}
    assert.equal((await import("data:text/javascript,export default 2")).default, 2);
  `;
  execFileSync(process.execPath, ["--input-type=module", "-e", script], {
    cwd: new URL("..", import.meta.url), timeout: 30_000, stdio: "pipe",
    env: {PATH: process.env.PATH, LANG: "C.UTF-8"},
  });
});

test("module guard rejects different or absent bytes returned by the next loader", () => {
  const script = `
    import assert from "node:assert/strict";
    import {createHash} from "node:crypto";
    import {mkdtempSync, realpathSync, writeFileSync, rmSync} from "node:fs";
    import {tmpdir} from "node:os";
    import {join} from "node:path";
    import {pathToFileURL} from "node:url";
    import {registerHooks} from "node:module";
    import {guardCompactionImports} from "./tools/build_asterion_prime_compaction_lock.mjs";
    const root = realpathSync(mkdtempSync(join(tmpdir(), "asterion-load-race-")));
    try {
      for (const [index, source] of ["globalThis.__unverified = true; export default 2;", null].entries()) {
        const name = "entry"+index+".mjs", original = "export default 1;";
        const url = pathToFileURL(join(root,name)).href;
        writeFileSync(join(root,name), original);
        const attack = registerHooks({load(target,context,nextLoad) {
          const loaded = nextLoad(target,context);
          return target === url ? {...loaded,source} : loaded;
        }});
        const guard = guardCompactionImports({root,lock:{files:{[name]:createHash("sha256").update(original).digest("hex")}}});
        try {
          await assert.rejects(import(url), {message:"Pi compaction closure is incompatible"});
          assert.equal(globalThis.__unverified, undefined);
        } finally {guard.deregister();attack.deregister();}
      }
      // A later hook may mutate a lower hook's retained buffer after the guard
      // returns. The compiled source must be the guard's independent copy.
      for (const kind of ["buffer", "typed-array", "array-buffer"]) {
        const name = kind+".mjs", original = "export default 1;";
        const url = pathToFileURL(join(root,name)).href;
        writeFileSync(join(root,name), original);
        const bytes = new Uint8Array(Buffer.from(original));
        const shared = kind === "buffer" ? Buffer.from(bytes.buffer)
          : kind === "typed-array" ? bytes : bytes.buffer;
        const lower = registerHooks({load(target,context,nextLoad) {
          const loaded=nextLoad(target,context);
          return target===url ? {...loaded,source:shared} : loaded;
        }});
        const guard = guardCompactionImports({root,lock:{files:{[name]:createHash("sha256").update(original).digest("hex")}}});
        const upper = registerHooks({load(target,context,nextLoad) {
          const loaded=nextLoad(target,context);
          if(target===url)bytes.set(Buffer.from("export default 2;"));
          return loaded;
        }});
        try {assert.equal((await import(url)).default,1);}
        finally {upper.deregister();guard.deregister();lower.deregister();}
      }
    } finally {rmSync(root,{recursive:true,force:true});}
  `;
  execFileSync(process.execPath, ["--input-type=module", "-e", script], {
    cwd: new URL("..", import.meta.url), timeout: 30_000, stdio: "pipe",
    env: {PATH: process.env.PATH, LANG: "C.UTF-8"},
  });
});

test("loader rejects dependency shape and digest drift with owned cleanup", async () => {
  for (const shape of ['{}', '{value: 1}', '{value: "ok", extra: "secret"}']) {
    const fixture = dependencyFixture(
      `export function verifyDependencies() {}\nexport function createDependencies() {return {dependencies: ${shape}, close() {globalThis.__dependencyClosed = true;}};}`,
      'export default () => {globalThis.__extensionRan = true;};',
    );
    try {
      const loader = await import(loaderUrl);
      await assert.rejects(loader.default({on() {}}), {message: "Asterion pinned Pi extension is invalid"});
      assert.equal(globalThis.__extensionRan, undefined);
      assert.equal(globalThis.__dependencyClosed, true);
      for (const fd of fixture.held) assert.throws(() => fstatSync(fd));
    } finally { delete globalThis.__dependencyClosed; fixture.cleanup(); }
  }
  const fixture = dependencyFixture('export function verifyDependencies() {}', 'export default () => {};');
  fixture.metadata.closureLock.digest = "a".repeat(64);
  process.env.ASTERION_PI_EXTENSION_DEPENDENCIES = JSON.stringify(fixture.metadata);
  try {
    const loader = await import(loaderUrl);
    await assert.rejects(loader.default({on() {}}), {message: "Asterion pinned Pi extension is invalid"});
    for (const fd of fixture.held) assert.throws(() => fstatSync(fd));
  } finally {fixture.cleanup();}
});

test("loader closes dependency resources on early extension failure and escaped roots", async () => {
  for (const scenario of ["source", "import", "root"]) {
    const fixture = dependencyFixture(
      'export function verifyDependencies() {} export function createDependencies() {return {dependencies: {value: "ok"}, close() {}};}',
      scenario === "import" ? 'throw Error("sentinel-private"); export default () => {};' : 'export default () => {};',
    );
    if (scenario === "source") process.env.ASTERION_PI_EXTENSION_SOURCE_SHA256 = "a".repeat(64);
    if (scenario === "root") {
      fixture.metadata.sourceRoot.path += "/..";
      process.env.ASTERION_PI_EXTENSION_DEPENDENCIES = JSON.stringify(fixture.metadata);
    }
    try {
      const loader = await import(loaderUrl);
      await assert.rejects(loader.default({on() {}}), {message: "Asterion pinned Pi extension is invalid"});
      assert.equal(process.env.ASTERION_PI_EXTENSION_DEPENDENCIES, undefined);
      for (const fd of fixture.held) assert.throws(() => fstatSync(fd));
    } finally {fixture.cleanup();}
  }
});

test("loader imports the exact bytes held by the source descriptor", async () => {
  const root = mkdtempSync(join(tmpdir(), "asterion-pi-loader-"));
  const sourcePath = join(root, "extension.mjs");
  const original = Buffer.from(
    'export default (pi) => pi.registerTool({ name: "original" });\n',
  );
  writeFileSync(sourcePath, original);
  const descriptor = openSync(sourcePath, "r");
  unlinkSync(sourcePath);
  writeFileSync(
    sourcePath,
    'export default (pi) => pi.registerTool({ name: "replacement" });\n',
  );
  process.env.ASTERION_PI_EXTENSION_SOURCE_FD = String(descriptor);
  process.env.ASTERION_PI_EXTENSION_SOURCE_NAME = "extension.mjs";
  process.env.ASTERION_PI_EXTENSION_SOURCE_SHA256 = createHash("sha256")
    .update(original)
    .digest("hex");
  const names = [];

  try {
    const loader = await import(`${loaderUrl.href}?case=pinned`);
    await loader.default({ registerTool: (tool) => names.push(tool.name) });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }

  assert.deepEqual(names, ["original"]);
  assert.equal(process.env.ASTERION_PI_EXTENSION_SOURCE_FD, undefined);
  assert.equal(process.env.ASTERION_PI_EXTENSION_SOURCE_NAME, undefined);
  assert.equal(process.env.ASTERION_PI_EXTENSION_SOURCE_SHA256, undefined);
});

test("loader closes the source descriptor when metadata is rejected", async () => {
  const root = mkdtempSync(join(tmpdir(), "asterion-pi-loader-"));
  const sourcePath = join(root, "extension.mjs");
  const source = Buffer.from("export default () => {};\n");
  writeFileSync(sourcePath, source);
  const descriptor = openSync(sourcePath, "r");
  process.env.ASTERION_PI_EXTENSION_SOURCE_FD = String(descriptor);
  process.env.ASTERION_PI_EXTENSION_SOURCE_NAME = "../extension.mjs";
  process.env.ASTERION_PI_EXTENSION_SOURCE_SHA256 = createHash("sha256")
    .update(source)
    .digest("hex");

  try {
    const loader = await import(`${loaderUrl.href}?case=metadata`);
    await assert.rejects(loader.default({}), {
      message: "Asterion pinned Pi extension is invalid",
    });
    assert.throws(() => fstatSync(descriptor));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("loader rejects mismatched pinned-source metadata without echoing it", async () => {
  const root = mkdtempSync(join(tmpdir(), "asterion-pi-loader-"));
  const sourcePath = join(root, "secret-extension.mjs");
  writeFileSync(sourcePath, "export default () => {};\n");
  const descriptor = openSync(sourcePath, "r");
  process.env.ASTERION_PI_EXTENSION_SOURCE_FD = String(descriptor);
  process.env.ASTERION_PI_EXTENSION_SOURCE_NAME = "secret-extension.mjs";
  process.env.ASTERION_PI_EXTENSION_SOURCE_SHA256 = "a".repeat(64);

  try {
    const loader = await import(`${loaderUrl.href}?case=mismatch`);
    await assert.rejects(
      loader.default({}),
      (error) =>
        error instanceof Error &&
        error.message === "Asterion pinned Pi extension is invalid",
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
