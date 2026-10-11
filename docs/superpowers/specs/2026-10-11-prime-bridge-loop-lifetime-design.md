# Prime bridge loop lifetime repair

User authorized solving migration defects and separating framework from P7 adaptation. A same-input native old/new small verification completed identical two-round computation but new owner cleanup=false. A provider-free real socket/worker reproduction isolated the exception: WorkspaceOwner closes a worker from the application loop while its creating ToolBridgeServer loop is idle; SubprocessPythonWorker treats !loop.is_running as unavailable. That state is normal between the bridge's blocking socket requests. Later bridge-local service closure succeeds, but the workspace failure receipt is already latched.

Responsibility: generic Prime tool bridge/worker ownership integration introduced by standard entry migration. Not P7-specific logic. It is a shutdown defect, not proven game reasoning interference.

Repair the bridge's loop lifetime: one owned asyncio loop stays running during socket serving, using sock_recv/sock_sendall and awaiting dispatch. The existing worker cross-loop closure can then schedule on its creating loop while the bridge is idle. Keep close/no-start behavior, newline framing, transport projection, selected tool semantics and error replies. A synchronous direct-dispatch seam may remain only for existing unit callers; native serving uses the asynchronous dispatch.

Keep independent model and worker reaping before resistant domain shutdown. Do not weaken cleanup receipts, increase task/grace budgets, move ownership into P7, add a runner, or permit unknown-effect retries. Resource and protocol surfaces stay unchanged.

Acceptance: real bridge socket + real worker idle-loop regression fails before repair; owner close passes afterward and reaps worker/bridge/model. Cover ordinary EOF, dispatch/error response parity, cancellation and existing resistant-domain controls. Run focused affected checks, independent Sol review and promotion. Only after provider-free closure passes may the root authorize one current-side repeat of the exact small native task; old-side native success remains frozen. No ARC trial.
