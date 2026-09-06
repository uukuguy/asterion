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
from asterion.applications.prime_agent.operator.development_preparation import PrimeDevelopmentPaths, resolve_prepared_prime_development
from asterion.runtime.host import CancellationSignal
from asterion.runtimes.prime_agent_host import PrimeP7DevelopmentHostService, PrimeSmallVerificationCancelled, PrimeSmallVerificationRequest, PrimeSmallVerificationResult
from asterion.services.registry import HostServiceFactoryBinding, HostServiceFactoryContext
from asterion.services.progress import HostProgressEvent, HostProgressReporter
from .p5_cli_host import _host_platform, _inspect_image, _sealed_seccomp
from .p7_broker_service import P7BrokerService
from .p7_development_docker import P7DevelopmentDockerTransport, P7DevelopmentDockerWorkerService
from .p7_development_gateway import PrimeP7DevelopmentGateway
from .p7_development_host import run_p7_development_lifecycle
from .p7_development_sdk_provider import create_prime_p7_development_sdk_provider
from .p7_resource_lock import verify_p7_development_resources
from .p7_runtime_lock import verify_p7_development_runtime
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
  _context(context);_emit(context.progress,"preflight","started")
  try:
   paths=_prepared_paths(root);_preflight(root,paths,context.progress)
  except BaseException:
   _emit(context.progress,"preflight","failed");raise PrimeP7CliHostError() from None
  _emit(context.progress,"preflight","succeeded")
  yield PrimeP7DevelopmentService(root,lifecycle_runner=lambda value,run_id:_run(value,run_id,context.progress,paths))
 return HostServiceFactoryBinding(_CAPABILITY_ID,(),factory)
def create_host_service_factory()->HostServiceFactoryBinding:return create_prime_p7_cli_factory(repo_root=Path.cwd())
def _context(c:object)->None:
 if type(c) is not HostServiceFactoryContext or (c.provider_id,c.application_id,c.application_version,c.capability_id)!=(_PROVIDER_ID,_APPLICATION_ID,_APPLICATION_VERSION,_CAPABILITY_ID) or dict(c.options):raise PrimeP7CliHostError()
def _prepared_paths(root:Path)->PrimeDevelopmentPaths:
 if sys.platform!="linux" or os.geteuid()!=0:raise PrimeP7CliHostError()
 try:return resolve_prepared_prime_development(root,"p7")
 except BaseException:raise PrimeP7CliHostError() from None
def _external(root:Path)->Path:
 value=os.environ.get("ASTERION_P7_EXTERNAL_ROOT")
 return Path(value).resolve() if value else (root.parent/"external-prime/arc-agi-3").resolve()
def _preflight(root:Path,paths:PrimeDevelopmentPaths,progress:HostProgressReporter|None=None)->None:
 external=Path(os.environ.get("ASTERION_P7_EXTERNAL_ROOT",root.parent/"external-prime/arc-agi-3")).resolve(); game=external/"environment_files/ls20/9607627b"
 try:
  _emit(progress,"source","started")
  if not all(p.is_file() for p in (Path("/usr/bin/docker"),paths.node,paths.gateway_root/"dist/src/p7-development-main.js",external/"venv/bin/python3")) or not paths.source_root.is_dir():raise ValueError
  verify_p7_development_resources(game);verify_p7_development_runtime(external)
  if not dotenv_values(root/".env"):raise ValueError
  _emit(progress,"source","succeeded")
 except BaseException:
  _emit(progress,"source","failed");raise PrimeP7CliHostError() from None
def _cfg(root:Path):
 value=dotenv_values(root/".env")
 if any(type(k)is not str or type(v)is not str for k,v in value.items()):raise PrimeP7CliHostError()
 return dict(value)
async def _run(root:Path,run_id:str,progress:HostProgressReporter|None=None,paths:PrimeDevelopmentPaths|None=None):
 external=Path(os.environ.get("ASTERION_P7_EXTERNAL_ROOT",root.parent/"external-prime/arc-agi-3")).resolve();game=external/"environment_files/ls20/9607627b"; broker=None;transport=None
 try:
  paths=paths or _prepared_paths(root)
  with TemporaryDirectory(prefix="asterion-p7-") as work:
   verify_p7_development_resources(game)
   runtime=verify_p7_development_runtime(external)
   _emit(progress,"image","started")
   image=_inspect_image(Path("/usr/bin/docker"),Path("/var/run/docker.sock"))
   _emit(progress,"image","succeeded")
   os.chown(work,65534,65534);os.chmod(work,0o700);broker=P7BrokerService(interpreter=external/"venv/bin/python3",asterion_src=root/"src",resource_root=game)
   transport=P7DevelopmentDockerTransport(docker_executable="/usr/bin/docker",socket_path="/var/run/docker.sock",seccomp_profile_fd=_sealed_seccomp(paths.seccomp),platform=_host_platform())
   worker=P7DevelopmentDockerWorkerService(image_digest=image,transport=transport,run_id=run_id,session_id="p7-"+run_id,goal_id="prime.arc-agi-3/v1",workspace=work,broker_private_dir=str(broker.private_dir),broker_model_socket=str(broker.model_socket))
   return await run_p7_development_lifecycle(gateway=PrimeP7DevelopmentGateway(node_bin=str(paths.node),entrypoint=paths.gateway_root/"dist/src/p7-development-main.js",deadline_seconds=300),provider=create_prime_p7_development_sdk_provider(_cfg(root)),worker=worker,broker=broker,run_id=run_id,session_id="p7-"+run_id,prime_source_root=str(paths.source_root),workspace=work,runtime=runtime,progress=progress)
 finally:
  if broker:broker.close()
  if transport:transport.close()
def _emit(reporter:HostProgressReporter|None,component:str,state:str,current:int|None=None,total:int|None=None)->None:
 if reporter is None:return
 try:reporter.emit(HostProgressEvent(component,state,current,total))
 except BaseException:pass
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
