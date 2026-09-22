use std::io;
use std::process::{ExitStatus, Output, Stdio};
use std::time::Duration;

use tokio::io::{AsyncRead, AsyncReadExt};
use tokio::process::Command;
use tokio::runtime::Handle;
use tokio::sync::watch;
use tokio::task::JoinHandle;
use tokio::time::{Duration as TokioDuration, Instant, sleep_until, timeout};

use crate::policy::AuthorizedExecution;

#[derive(Debug, Eq, PartialEq)]
pub struct CapturedOutput {
    pub bytes: Vec<u8>,
    pub truncated: bool,
}

#[derive(Debug)]
pub struct BoundedProcessOutput {
    pub exit_status: Option<ExitStatus>,
    pub stdout: CapturedOutput,
    pub stderr: CapturedOutput,
    pub timed_out: bool,
    pub cancelled: bool,
}

struct ProcessOwner {
    child: Option<tokio::process::Child>,
    process_group: Option<u32>,
    stdout_task: Option<JoinHandle<io::Result<CapturedOutput>>>,
    stderr_task: Option<JoinHandle<io::Result<CapturedOutput>>>,
    stdout_joined: bool,
    stderr_joined: bool,
    leader_reaped: bool,
    disarmed: bool,
}

impl ProcessOwner {
    fn new(child: tokio::process::Child) -> Self {
        let process_group = child.id();
        Self {
            child: Some(child),
            process_group,
            stdout_task: None,
            stderr_task: None,
            stdout_joined: false,
            stderr_joined: false,
            leader_reaped: false,
            disarmed: false,
        }
    }

    fn disarm(&mut self) {
        self.disarmed = true;
    }

    async fn stop_and_reap(&mut self) -> io::Result<ExitStatus> {
        stop_and_reap(
            self.child.as_mut().expect("owned child"),
            self.process_group,
            self.stdout_task.as_mut().expect("owned stdout reader"),
            self.stderr_task.as_mut().expect("owned stderr reader"),
            self.stdout_joined,
            self.stderr_joined,
            &mut self.leader_reaped,
        )
        .await
    }
}

impl Drop for ProcessOwner {
    fn drop(&mut self) {
        if self.disarmed {
            return;
        }
        if !self.leader_reaped {
            let _ = terminate_process_group(self.process_group);
        }
        if let Some(task) = self.stdout_task.as_ref().filter(|_| !self.stdout_joined) {
            task.abort();
        }
        if let Some(task) = self.stderr_task.as_ref().filter(|_| !self.stderr_joined) {
            task.abort();
        }
        let Some(mut child) = self.child.take() else {
            return;
        };
        if !self.leader_reaped {
            let _ = child.start_kill();
        }
        let stdout_task = self.stdout_task.take();
        let stderr_task = self.stderr_task.take();
        let stdout_joined = self.stdout_joined;
        let stderr_joined = self.stderr_joined;
        let leader_reaped = self.leader_reaped;
        if let Ok(handle) = Handle::try_current() {
            handle.spawn(async move {
                if !leader_reaped {
                    let _ = timeout(TokioDuration::from_secs(1), child.wait()).await;
                }
                if let Some(task) = stdout_task.filter(|_| !stdout_joined) {
                    let _ = task.await;
                }
                if let Some(task) = stderr_task.filter(|_| !stderr_joined) {
                    let _ = task.await;
                }
            });
        }
    }
}

pub async fn execute_direct(execution: AuthorizedExecution) -> io::Result<Output> {
    let mut command = Command::new(execution.executable());
    command
        .args(execution.arguments())
        .current_dir(execution.cwd())
        .env_clear()
        .stdin(Stdio::null())
        .kill_on_drop(true);
    command.output().await
}

pub async fn execute_bounded(execution: AuthorizedExecution) -> io::Result<BoundedProcessOutput> {
    let (_cancel_tx, cancel_rx) = watch::channel(false);
    execute_bounded_cancellable(execution, cancel_rx).await
}

pub async fn execute_bounded_cancellable(
    execution: AuthorizedExecution,
    mut cancel: watch::Receiver<bool>,
) -> io::Result<BoundedProcessOutput> {
    let output_limit = execution.max_output_bytes();
    let deadline = Duration::from_millis(execution.deadline_ms());
    let deadline_at = Instant::now() + deadline;
    let mut command = Command::new(execution.executable());
    command
        .args(execution.arguments())
        .current_dir(execution.cwd())
        .env_clear()
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    #[cfg(unix)]
    command.process_group(0);

    if *cancel.borrow() {
        return Ok(BoundedProcessOutput {
            exit_status: None,
            stdout: empty_capture(),
            stderr: empty_capture(),
            timed_out: false,
            cancelled: true,
        });
    }
    let mut owner = ProcessOwner::new(command.spawn()?);
    let stdout = owner
        .child
        .as_mut()
        .expect("owned child")
        .stdout
        .take()
        .ok_or_else(|| io::Error::other("child stdout is unavailable"))?;
    let stderr = owner
        .child
        .as_mut()
        .expect("owned child")
        .stderr
        .take()
        .ok_or_else(|| io::Error::other("child stderr is unavailable"))?;
    owner.stdout_task = Some(tokio::spawn(read_capped(stdout, output_limit)));
    owner.stderr_task = Some(tokio::spawn(read_capped(stderr, output_limit)));

    enum OperationOutcome {
        Finished(io::Result<(ExitStatus, CapturedOutput, CapturedOutput)>),
        TimedOut,
        Cancelled,
    }
    let outcome = {
        let process_group = owner.process_group;
        let child = owner.child.as_mut().expect("owned child");
        let stdout_task = owner.stdout_task.as_mut().expect("owned stdout reader");
        let stderr_task = owner.stderr_task.as_mut().expect("owned stderr reader");
        let stdout_joined = &mut owner.stdout_joined;
        let stderr_joined = &mut owner.stderr_joined;
        let leader_reaped = &mut owner.leader_reaped;
        let operation = async {
            // On Unix, observe the leader's exit without reaping it. Its PID
            // remains reserved while we clean the process group, so a reused
            // PGID cannot direct the signal at an unrelated process group.
            #[cfg(unix)]
            wait_for_exit_without_reaping(
                process_group.ok_or_else(|| io::Error::other("child PID is unavailable"))?,
            )
            .await?;
            #[cfg(not(unix))]
            let exit_status = child.wait().await?;
            let stdout_result = join_capture(stdout_task).await;
            *stdout_joined = true;
            let stdout = stdout_result?;
            let stderr_result = join_capture(stderr_task).await;
            *stderr_joined = true;
            let stderr = stderr_result?;
            #[cfg(unix)]
            let exit_status = {
                let group_result = terminate_completed_process_group(process_group);
                let exit_status = child.wait().await?;
                *leader_reaped = true;
                group_result?;
                exit_status
            };
            Ok((exit_status, stdout, stderr))
        };
        tokio::pin!(operation);
        if *cancel.borrow() {
            OperationOutcome::Cancelled
        } else {
            tokio::select! {
                biased;
                _ = wait_for_cancellation(&mut cancel) => OperationOutcome::Cancelled,
                _ = sleep_until(deadline_at) => OperationOutcome::TimedOut,
                result = &mut operation => OperationOutcome::Finished(result),
            }
        }
    };
    let (exit_status, stdout, stderr, timed_out, cancelled) = match outcome {
        OperationOutcome::Finished(Ok((exit_status, stdout, stderr))) => {
            (exit_status, stdout, stderr, false, false)
        }
        OperationOutcome::Finished(Err(error)) => {
            // The completed path has already reaped the group leader. Do not
            // signal its numeric PGID again: it may now belong to another run.
            if owner.leader_reaped {
                owner.disarm();
                return Err(error);
            }
            if owner.stop_and_reap().await.is_ok() {
                owner.disarm();
            }
            return Err(error);
        }
        OperationOutcome::TimedOut => {
            let exit_status = owner.stop_and_reap().await?;
            (exit_status, empty_capture(), empty_capture(), true, false)
        }
        OperationOutcome::Cancelled => {
            let exit_status = owner.stop_and_reap().await?;
            (exit_status, empty_capture(), empty_capture(), false, true)
        }
    };
    owner.disarm();

    Ok(BoundedProcessOutput {
        exit_status: Some(exit_status),
        stdout,
        stderr,
        timed_out,
        cancelled,
    })
}

#[cfg(unix)]
async fn wait_for_exit_without_reaping(pid: u32) -> io::Result<()> {
    tokio::task::spawn_blocking(move || {
        loop {
            let mut status: libc::siginfo_t = unsafe { std::mem::zeroed() };
            let result = unsafe {
                libc::waitid(
                    libc::P_PID,
                    pid as libc::id_t,
                    &mut status,
                    libc::WEXITED | libc::WNOWAIT,
                )
            };
            if result == 0 {
                return Ok(());
            }
            let error = io::Error::last_os_error();
            if error.kind() != io::ErrorKind::Interrupted {
                return Err(error);
            }
        }
    })
    .await
    .map_err(io::Error::other)?
}

async fn wait_for_cancellation(cancel: &mut watch::Receiver<bool>) {
    loop {
        if *cancel.borrow() {
            return;
        }
        if cancel.changed().await.is_err() {
            std::future::pending::<()>().await;
        }
    }
}

async fn stop_and_reap(
    child: &mut tokio::process::Child,
    process_group: Option<u32>,
    stdout_task: &mut JoinHandle<io::Result<CapturedOutput>>,
    stderr_task: &mut JoinHandle<io::Result<CapturedOutput>>,
    stdout_joined: bool,
    stderr_joined: bool,
    leader_reaped: &mut bool,
) -> io::Result<ExitStatus> {
    let group_result = terminate_process_group(process_group);
    let _ = child.start_kill();
    let exit_result = timeout(TokioDuration::from_secs(1), child.wait())
        .await
        .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "child cleanup exceeded grace"));
    if matches!(&exit_result, Ok(Ok(_))) {
        *leader_reaped = true;
    }
    if !stdout_joined {
        stdout_task.abort();
        let _ = stdout_task.await;
    }
    if !stderr_joined {
        stderr_task.abort();
        let _ = stderr_task.await;
    }
    group_result?;
    exit_result?
}

#[cfg(unix)]
fn terminate_completed_process_group(process_group: Option<u32>) -> io::Result<()> {
    match terminate_process_group(process_group) {
        // Darwin reports EPERM for a group containing only the exited leader.
        // There is no signalable process left in that case. This executor is
        // not a sandbox: a descendant that changed credentials also cannot be
        // forcibly stopped by this owner.
        Err(error) if error.raw_os_error() == Some(libc::EPERM) => Ok(()),
        result => result,
    }
}

#[cfg(unix)]
fn terminate_process_group(process_group: Option<u32>) -> io::Result<()> {
    let Some(process_group) = process_group else {
        return Ok(());
    };
    let result = unsafe { libc::kill(-(process_group as libc::pid_t), libc::SIGKILL) };
    if result == 0 {
        return Ok(());
    }
    let error = io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::ESRCH) {
        Ok(())
    } else {
        Err(error)
    }
}

#[cfg(not(unix))]
fn terminate_process_group(_: Option<u32>) -> io::Result<()> {
    Ok(())
}

fn empty_capture() -> CapturedOutput {
    CapturedOutput {
        bytes: Vec::new(),
        truncated: false,
    }
}

async fn read_capped<R>(mut reader: R, limit: usize) -> io::Result<CapturedOutput>
where
    R: AsyncRead + Unpin,
{
    let mut bytes = Vec::with_capacity(limit);
    let mut buffer = [0_u8; 8_192];
    let mut truncated = false;
    loop {
        let read = reader.read(&mut buffer).await?;
        if read == 0 {
            break;
        }
        let retained = limit.saturating_sub(bytes.len()).min(read);
        bytes.extend_from_slice(&buffer[..retained]);
        truncated |= retained < read;
    }
    Ok(CapturedOutput { bytes, truncated })
}

async fn join_capture(
    task: &mut JoinHandle<io::Result<CapturedOutput>>,
) -> io::Result<CapturedOutput> {
    task.await.map_err(io::Error::other)?
}
