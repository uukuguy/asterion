import { existsSync, readFileSync } from "node:fs";

const selfCheck = '{"credentials_absent":true,"effective_capabilities":0,"effective_user_id":65534,"no_new_privileges":1,"nonloopback_network_absent":true,"root_read_only":true,"seccomp_mode":2,"workspace_only_writable":true}';

const writableKernelMounts = new Set(["/dev", "/dev/mqueue", "/dev/pts", "/proc", "/sys"]);
const credentialSentinels = ["/run/secrets", "/root/.aws", "/home/node/.aws", "/home/node/.config/gcloud", "/workspace/.env"];

function unescapeMount(value) {
  return value.replaceAll("\\040", " ").replaceAll("\\011", "\t").replaceAll("\\012", "\n").replaceAll("\\134", "\\");
}

function parseMounts(raw) {
  return raw.trimEnd().split("\n").map((line) => {
    const fields = line.split(" ");
    if (fields.length !== 6) throw new Error("worker check failed");
    return { device: unescapeMount(fields[0]), mountPoint: unescapeMount(fields[1]), type: fields[2], options: new Set(fields[3].split(",")) };
  });
}

function workspaceOnlyWritable(mounts) {
  let rootReadOnly = false;
  let workspaceWritable = false;
  for (const { device, mountPoint, type, options } of mounts) {
    if (mountPoint === "/") rootReadOnly = options.has("ro");
    if (mountPoint === "/workspace") workspaceWritable = device === "tmpfs" && type === "tmpfs" && options.has("rw") && options.has("nodev") && options.has("noexec") && options.has("nosuid");
    if (options.has("rw") && mountPoint !== "/workspace" && !writableKernelMounts.has(mountPoint)) return false;
  }
  return rootReadOnly && workspaceWritable;
}

function credentialSentinelAbsent() {
  return credentialSentinels.every((sentinel) => !existsSync(sentinel));
}

function requireClosedWorker() {
  if (process.getuid() !== 65534) throw new Error("worker check failed");
  const status = readFileSync("/proc/self/status", "utf8");
  const mounts = parseMounts(readFileSync("/proc/mounts", "utf8"));
  const devices = readFileSync("/proc/net/dev", "utf8");
  if (!status.includes("NoNewPrivs:\t1") || !status.includes("CapEff:\t0000000000000000") || !status.includes("Seccomp:\t2") || !workspaceOnlyWritable(mounts) || !credentialSentinelAbsent() || devices.split("\n").some((line) => line.includes(":") && !line.trimStart().startsWith("lo:"))) throw new Error("worker check failed");
}

async function releaseFrame() {
  let text = "";
  for await (const chunk of process.stdin) {
    text += chunk;
    if (Buffer.byteLength(text) > 1024) throw new Error("release frame invalid");
  }
  const releaseCount = text === '{"release":true}\n' ? 1 : 0;
  if (releaseCount !== 1) throw new Error("release frame invalid");
}

requireClosedWorker();
process.stdout.write(`${selfCheck}\n`);
await releaseFrame();
process.stderr.write("unproven fixed Prime/IPython sequence incomplete\n");
