use std::io;
use std::process::{ExitStatus, Output, Stdio};
use std::time::Duration;

use tokio::io::{AsyncRead, AsyncReadExt};
use tokio::process::Command;
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

    let mut child = command.spawn()?;
    let process_group = child.id();
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| io::Error::other("child stdout is unavailable"))?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| io::Error::other("child stderr is unavailable"))?;
    let mut stdout_task = tokio::spawn(read_capped(stdout, output_limit));
    let mut stderr_task = tokio::spawn(read_capped(stderr, output_limit));

    enum OperationOutcome {
        Finished(io::Result<(ExitStatus, CapturedOutput, CapturedOutput)>),
        TimedOut,
        Cancelled,
    }
    let outcome = {
        let operation = async {
            let exit_status = child.wait().await?;
            let stdout = join_capture(&mut stdout_task).await?;
            let stderr = join_capture(&mut stderr_task).await?;
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
            let _ = stop_and_reap(
                &mut child,
                process_group,
                &mut stdout_task,
                &mut stderr_task,
            )
            .await;
            return Err(error);
        }
        OperationOutcome::TimedOut => {
            let exit_status = stop_and_reap(
                &mut child,
                process_group,
                &mut stdout_task,
                &mut stderr_task,
            )
            .await?;
            (exit_status, empty_capture(), empty_capture(), true, false)
        }
        OperationOutcome::Cancelled => {
            let exit_status = stop_and_reap(
                &mut child,
                process_group,
                &mut stdout_task,
                &mut stderr_task,
            )
            .await?;
            (exit_status, empty_capture(), empty_capture(), false, true)
        }
    };

    Ok(BoundedProcessOutput {
        exit_status: Some(exit_status),
        stdout,
        stderr,
        timed_out,
        cancelled,
    })
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
) -> io::Result<ExitStatus> {
    let group_result = terminate_process_group(process_group);
    let _ = child.start_kill();
    let exit_result = timeout(TokioDuration::from_secs(1), child.wait())
        .await
        .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "child cleanup exceeded grace"));
    stdout_task.abort();
    stderr_task.abort();
    let _ = stdout_task.await;
    let _ = stderr_task.await;
    group_result?;
    exit_result?
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
