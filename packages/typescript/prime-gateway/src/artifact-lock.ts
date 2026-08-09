import { execFile as execFileCallback } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, readFile } from "node:fs/promises";
import { isAbsolute, join, normalize, sep } from "node:path";
import { promisify } from "node:util";

const execFile = promisify(execFileCallback);
const LOCK_FORMAT = "asterion.prime-artifact-lock/v1";
const LOCK_KEYS = Object.freeze([
  "daemon_protocol",
  "daemon_schema_id",
  "daemon_schema_revision",
  "files",
  "format",
  "package_name",
  "package_version",
  "source_commit",
]);
const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const COMMIT_PATTERN = /^[0-9a-f]{40}$/u;

export interface PrimeArtifactLock {
  readonly format: typeof LOCK_FORMAT;
  readonly source_commit: string;
  readonly package_name: string;
  readonly package_version: string;
  readonly daemon_protocol: number;
  readonly daemon_schema_revision: number;
  readonly daemon_schema_id: string;
  readonly files: Readonly<Record<string, string>>;
}

export interface PrimeArtifactEvidence {
  readonly commit: string;
  readonly packageName: string;
  readonly packageVersion: string;
  readonly protocolVersion: number;
  readonly schemaRevision: number;
  readonly schemaId: string;
  readonly fileDigests: Readonly<Record<string, string>>;
}

export class PrimeArtifactCompatibilityError extends Error {
  constructor() {
    super("Prime artifact is incompatible");
    this.name = "PrimeArtifactCompatibilityError";
  }
}

function incompatible(): never {
  throw new PrimeArtifactCompatibilityError();
}

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

function isSafeRelativeFile(value: string): boolean {
  if (value.length === 0 || isAbsolute(value) || value.includes("\\")) {
    return false;
  }
  const normalized = normalize(value);
  return (
    normalized === value &&
    normalized !== ".." &&
    !normalized.startsWith(`..${sep}`) &&
    !normalized.endsWith(sep)
  );
}

function parseLock(value: unknown): PrimeArtifactLock {
  if (!isRecord(value) || !hasExactKeys(value, LOCK_KEYS)) {
    incompatible();
  }
  const files = value.files;
  if (
    value.format !== LOCK_FORMAT ||
    typeof value.source_commit !== "string" ||
    !COMMIT_PATTERN.test(value.source_commit) ||
    typeof value.package_name !== "string" ||
    value.package_name.length === 0 ||
    typeof value.package_version !== "string" ||
    value.package_version.length === 0 ||
    !Number.isSafeInteger(value.daemon_protocol) ||
    Number(value.daemon_protocol) < 1 ||
    !Number.isSafeInteger(value.daemon_schema_revision) ||
    Number(value.daemon_schema_revision) < 1 ||
    typeof value.daemon_schema_id !== "string" ||
    value.daemon_schema_id.length === 0 ||
    !isRecord(files)
  ) {
    incompatible();
  }
  const entries = Object.entries(files);
  if (entries.length === 0) {
    incompatible();
  }
  const checkedFiles: Record<string, string> = {};
  for (const [path, digest] of entries) {
    if (
      !isSafeRelativeFile(path) ||
      typeof digest !== "string" ||
      !SHA256_PATTERN.test(digest)
    ) {
      incompatible();
    }
    checkedFiles[path] = digest;
  }
  const frozenFiles = Object.freeze(checkedFiles);
  return Object.freeze({
    format: LOCK_FORMAT,
    source_commit: value.source_commit,
    package_name: value.package_name,
    package_version: value.package_version,
    daemon_protocol: Number(value.daemon_protocol),
    daemon_schema_revision: Number(value.daemon_schema_revision),
    daemon_schema_id: value.daemon_schema_id,
    files: frozenFiles,
  });
}

function parseJson(bytes: Buffer): unknown {
  try {
    return JSON.parse(bytes.toString("utf8"));
  } catch {
    incompatible();
  }
}

function verifyPackageIdentity(
  packageLockBytes: Buffer,
  codingPackageBytes: Buffer,
  lock: PrimeArtifactLock,
): void {
  const packageLock = parseJson(packageLockBytes);
  const codingPackage = parseJson(codingPackageBytes);
  if (!isRecord(packageLock) || !isRecord(codingPackage)) {
    incompatible();
  }
  const packages = packageLock.packages;
  const rootPackage = isRecord(packages) ? packages[""] : undefined;
  const lockedCodingPackage = isRecord(packages)
    ? packages["packages/coding-agent"]
    : undefined;
  if (
    packageLock.name !== "prime-agent" ||
    packageLock.version !== lock.package_version ||
    packageLock.lockfileVersion !== 3 ||
    !isRecord(rootPackage) ||
    rootPackage.name !== "prime-agent" ||
    rootPackage.version !== lock.package_version ||
    !isRecord(lockedCodingPackage) ||
    lockedCodingPackage.name !== lock.package_name ||
    lockedCodingPackage.version !== lock.package_version ||
    codingPackage.name !== lock.package_name ||
    codingPackage.version !== lock.package_version
  ) {
    incompatible();
  }
}

async function pathExists(path: string): Promise<boolean> {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    if (
      typeof error === "object" &&
      error !== null &&
      "code" in error &&
      error.code === "ENOENT"
    ) {
      return false;
    }
    incompatible();
  }
}

async function readLockedFile(root: string, relativePath: string): Promise<Buffer> {
  const parts = relativePath.split("/");
  let target = root;
  for (const [index, part] of parts.entries()) {
    target = join(target, part);
    const stat = await lstat(target);
    const isLast = index === parts.length - 1;
    if (
      stat.isSymbolicLink() ||
      (isLast ? !stat.isFile() : !stat.isDirectory())
    ) {
      incompatible();
    }
  }
  return readFile(target);
}

async function verifyGit(root: string, expectedCommit: string): Promise<void> {
  const options = {
    cwd: root,
    encoding: "utf8" as const,
    env: {
      GIT_CONFIG_GLOBAL: "/dev/null",
      GIT_CONFIG_NOSYSTEM: "1",
      PATH: process.env.PATH,
    },
    maxBuffer: 64 * 1024,
    timeout: 10_000,
  };
  try {
    const status = await execFile(
      "git",
      ["status", "--porcelain", "--untracked-files=no"],
      options,
    );
    const head = await execFile("git", ["rev-parse", "HEAD"], options);
    if (status.stdout.length !== 0 || head.stdout.trim() !== expectedCommit) {
      incompatible();
    }
  } catch (error) {
    if (error instanceof PrimeArtifactCompatibilityError) {
      throw error;
    }
    incompatible();
  }
}

export async function loadPrimeArtifactLock(
  url: URL,
): Promise<PrimeArtifactLock> {
  try {
    return parseLock(JSON.parse(await readFile(url, "utf8")));
  } catch (error) {
    if (error instanceof PrimeArtifactCompatibilityError) {
      throw error;
    }
    incompatible();
  }
}

export async function verifyPrimeArtifact(
  root: string,
  candidateLock: PrimeArtifactLock,
): Promise<PrimeArtifactEvidence> {
  try {
    const lock = parseLock(candidateLock);
    const rootStat = await lstat(root);
    if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) {
      incompatible();
    }
    const bytesByPath = new Map<string, Buffer>();
    for (const [relativePath, expectedDigest] of Object.entries(lock.files)) {
      const bytes = await readLockedFile(root, relativePath);
      const actualDigest = createHash("sha256").update(bytes).digest("hex");
      if (actualDigest !== expectedDigest) {
        incompatible();
      }
      bytesByPath.set(relativePath, bytes);
    }
    const packageLockBytes = bytesByPath.get("package-lock.json");
    const codingPackageBytes = bytesByPath.get(
      "packages/coding-agent/package.json",
    );
    if (packageLockBytes === undefined || codingPackageBytes === undefined) {
      incompatible();
    }
    verifyPackageIdentity(packageLockBytes, codingPackageBytes, lock);
    if (await pathExists(join(root, ".git"))) {
      await verifyGit(root, lock.source_commit);
    }
    const fileDigests = Object.freeze({ ...lock.files });
    return Object.freeze({
      commit: lock.source_commit,
      packageName: lock.package_name,
      packageVersion: lock.package_version,
      protocolVersion: lock.daemon_protocol,
      schemaRevision: lock.daemon_schema_revision,
      schemaId: lock.daemon_schema_id,
      fileDigests,
    });
  } catch (error) {
    if (error instanceof PrimeArtifactCompatibilityError) {
      throw error;
    }
    incompatible();
  }
}
