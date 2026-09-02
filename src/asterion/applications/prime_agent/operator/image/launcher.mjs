import { readFileSync } from "node:fs";

const selfCheck = '{"credentials_absent":true,"effective_capabilities":0,"effective_user_id":65534,"no_new_privileges":1,"nonloopback_network_absent":true,"root_read_only":true,"seccomp_mode":2,"workspace_only_writable":true}';

function requireClosedWorker() {
  if (process.getuid() !== 65534) throw new Error("worker check failed");
  const status = readFileSync("/proc/self/status", "utf8");
  const mounts = readFileSync("/proc/mounts", "utf8");
  const devices = readFileSync("/proc/net/dev", "utf8");
  if (!status.includes("NoNewPrivs:\t1") || !status.includes("CapEff:\t0000000000000000") || !status.includes("Seccomp:\t2") || !mounts.includes(" / ") || !mounts.includes(" /workspace ") || devices.split("\n").some((line) => line.includes(":") && !line.trimStart().startsWith("lo:"))) throw new Error("worker check failed");
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
