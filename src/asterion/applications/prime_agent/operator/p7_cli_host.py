"""Operator-only P7 CLI wiring."""
# ruff: noqa: E701, E702
from __future__ import annotations
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from dotenv import dotenv_values
from asterion.runtime.host import CancellationSignal
from asterion.runtimes.prime_agent_host import PrimeP7DevelopmentHostService, PrimeSmallVerificationCancelled, PrimeSmallVerificationRequest, PrimeSmallVerificationResult
from asterion.services.registry import HostServiceFactoryBinding, HostServiceFactoryContext
from .p5_cli_host import _host_platform, _inspect_image, _sealed_seccomp
from .p7_broker_service import P7BrokerService
from .p7_development_docker import P7DevelopmentDockerTransport, P7DevelopmentDockerWorkerService
from .p7_development_gateway import PrimeP7DevelopmentGateway
from .p7_development_host import run_p7_development_lifecycle
from .p7_development_sdk_provider import create_prime_p7_development_sdk_provider
from .p7_resource_lock import verify_p7_development_resources
_CAPABILITY_ID="prime.arc-agi-3-development"; _PROVIDER_ID="prime-agent"; _APPLICATION_ID="prime.arc-agi-3"; _APPLICATION_VERSION="1.0.0"; _RUN=re.compile(r"[a-z][a-z0-9.-]*\Z")
_DEADLINE_SECONDS = 300
_LifecycleRunner = Callable[[Path, str], Awaitable[object]]
class PrimeP7CliHostError(ValueError):
 def __init__(self,*_:object)->None: super().__init__("prime P7 CLI host is unavailable")
class PrimeP7DevelopmentService(PrimeP7DevelopmentHostService):
 def __init__(self,root:Path,*,lifecycle_runner:_LifecycleRunner|None=None)->None:
  self.root=root;self.used=False;self._lifecycle_runner=_run if lifecycle_runner is None else lifecycle_runner
 async def verify(self,request:PrimeSmallVerificationRequest,*,signal:CancellationSignal|None=None)->PrimeSmallVerificationResult:
  if self.used or type(request) is not PrimeSmallVerificationRequest or _RUN.fullmatch(request.run_id) is None:raise PrimeP7CliHostError()
  self.used=True
  if _cancelled(signal):raise PrimeSmallVerificationCancelled()
  task=asyncio.create_task(self._lifecycle_runner(self.root,request.run_id))
  try:
   async with asyncio.timeout(_DEADLINE_SECONDS): trace=await _await_with_cancellation(task,signal)
   return PrimeSmallVerificationResult(request.run_id,trace.trace_sha256,scope="p7-development")
  except PrimeSmallVerificationCancelled:
   task.cancel();await _shielded_wait(task);raise
  except asyncio.CancelledError:
   task.cancel();await _shielded_wait(task);raise
  except BaseException:
   task.cancel();await _shielded_wait(task);raise PrimeP7CliHostError() from None
def create_prime_p7_cli_factory(*,repo_root:Path)->HostServiceFactoryBinding:
 root=Path(repo_root).resolve()
 @asynccontextmanager
 async def factory(context:HostServiceFactoryContext):
  _context(context);_preflight(root);yield PrimeP7DevelopmentService(root)
 return HostServiceFactoryBinding(_CAPABILITY_ID,(),factory)
def create_host_service_factory()->HostServiceFactoryBinding:return create_prime_p7_cli_factory(repo_root=Path.cwd())
def _context(c:object)->None:
 if type(c) is not HostServiceFactoryContext or (c.provider_id,c.application_id,c.application_version,c.capability_id)!=(_PROVIDER_ID,_APPLICATION_ID,_APPLICATION_VERSION,_CAPABILITY_ID) or dict(c.options):raise PrimeP7CliHostError()
def _preflight(root:Path)->None:
 external=Path(os.environ.get("ASTERION_P7_EXTERNAL_ROOT",root.parent/"external-prime/arc-agi-3")).resolve(); game=external/"environment_files/ls20/9607627b"
 if sys.platform!="linux" or os.geteuid()!=0 or not all(p.is_file() for p in (Path("/usr/bin/docker"),Path("/tmp/asterion-node22/bin/node"),root/"packages/typescript/prime-gateway/dist/src/p7-development-main.js",external/"venv/bin/python3")) or not (root/"3th-party/prime-agent").is_dir() or not dotenv_values(root/".env"):raise PrimeP7CliHostError()
 verify_p7_development_resources(game)
def _cfg(root:Path):
 value=dotenv_values(root/".env")
 if any(type(k)is not str or type(v)is not str for k,v in value.items()):raise PrimeP7CliHostError()
 return dict(value)
def _seccomp_fd():
 try:
  return _sealed_seccomp(Path("/tmp/asterion-p1-development-seccomp.json"))
 except BaseException:
  # Orb's Python lacks memfd_create; the operator-owned profile is still a
  # read-only regular file passed directly to Docker.
  fd=os.open("/tmp/asterion-p1-development-seccomp.json",os.O_RDONLY|os.O_CLOEXEC)
  if os.fstat(fd).st_size<=0: os.close(fd);raise PrimeP7CliHostError()
  return fd
async def _run(root:Path,run_id:str):
 external=Path(os.environ.get("ASTERION_P7_EXTERNAL_ROOT",root.parent/"external-prime/arc-agi-3")).resolve();game=external/"environment_files/ls20/9607627b"; broker=None;transport=None
 try:
  with TemporaryDirectory(prefix="asterion-p7-") as work:
   os.chown(work,65534,65534);os.chmod(work,0o700);broker=P7BrokerService(interpreter=external/"venv/bin/python3",asterion_src=root/"src",resource_root=game)
   transport=P7DevelopmentDockerTransport(docker_executable="/usr/bin/docker",socket_path="/var/run/docker.sock",seccomp_profile_fd=_seccomp_fd(),platform=_host_platform())
   worker=P7DevelopmentDockerWorkerService(image_digest=_inspect_image(Path("/usr/bin/docker"),Path("/var/run/docker.sock")),transport=transport,run_id=run_id,session_id="p7-"+run_id,goal_id="prime.arc-agi-3/v1",workspace=work,broker_private_dir=str(broker.private_dir),broker_model_socket=str(broker.model_socket))
   return await run_p7_development_lifecycle(gateway=PrimeP7DevelopmentGateway(node_bin="/tmp/asterion-node22/bin/node",entrypoint=root/"packages/typescript/prime-gateway/dist/src/p7-development-main.js",deadline_seconds=300),provider=create_prime_p7_development_sdk_provider(_cfg(root)),worker=worker,broker=broker,run_id=run_id,session_id="p7-"+run_id,prime_source_root=str(root/"3th-party/prime-agent"),workspace=work)
 finally:
  if broker:broker.close()
  if transport:transport.close()
def _cancelled(signal:CancellationSignal|None)->bool:
 if signal is None:return False
 try:return signal.cancelled is True
 except BaseException:raise PrimeP7CliHostError() from None
async def _await_with_cancellation(task:asyncio.Task[object],signal:CancellationSignal|None)->object:
 while not task.done():
  if _cancelled(signal):raise PrimeSmallVerificationCancelled()
  try:await asyncio.wait_for(asyncio.shield(task),timeout=0.05)
  except TimeoutError:continue
 return task.result()
async def _shielded_wait(task:asyncio.Task[object])->None:
 while not task.done():
  try:await asyncio.shield(task)
  except asyncio.CancelledError:continue
  except BaseException:break
 try:task.result()
 except BaseException:pass
__all__=("PrimeP7CliHostError","PrimeP7DevelopmentService","create_host_service_factory","create_prime_p7_cli_factory")
