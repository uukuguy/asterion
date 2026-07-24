use std::collections::BTreeMap;
use std::io;
use std::sync::Arc;

use tokio::io::{AsyncBufRead, AsyncBufReadExt, AsyncWrite, AsyncWriteExt};
use tokio::sync::{Mutex, mpsc, watch};

use crate::policy::TrustedPolicy;
use crate::process::execute_bounded_cancellable;
use crate::protocol::{
    CancelRequest, ExecutionStatus, ExecutorRequest, ExecutorResponse, PROTOCOL,
};

#[derive(Clone)]
struct ExecutorService {
    policy: Arc<TrustedPolicy>,
    in_flight: Arc<Mutex<BTreeMap<String, watch::Sender<bool>>>>,
    responses: mpsc::UnboundedSender<ExecutorResponse>,
}

impl ExecutorService {
    fn new(policy: TrustedPolicy) -> (Self, mpsc::UnboundedReceiver<ExecutorResponse>) {
        let (responses, receiver) = mpsc::unbounded_channel();
        (
            Self {
                policy: Arc::new(policy),
                in_flight: Arc::new(Mutex::new(BTreeMap::new())),
                responses,
            },
            receiver,
        )
    }

    async fn submit_line(&self, line: &str) {
        match serde_json::from_str::<ExecutorRequest>(line) {
            Ok(ExecutorRequest::Execute(request)) => {
                let request_id = request.request_id.clone();
                let execution = match self.policy.authorize(request) {
                    Ok(execution) => execution,
                    Err(_) => {
                        self.send_denied(request_id, "authorization_denied");
                        return;
                    }
                };
                let (cancel_tx, cancel_rx) = watch::channel(false);
                {
                    let mut in_flight = self.in_flight.lock().await;
                    if in_flight.contains_key(&request_id) {
                        self.send_denied(request_id, "duplicate_request_id");
                        return;
                    }
                    if in_flight.len() >= self.policy.max_concurrency {
                        self.send_denied(request_id, "concurrency_limit");
                        return;
                    }
                    in_flight.insert(request_id.clone(), cancel_tx);
                }

                let service = self.clone();
                tokio::spawn(async move {
                    let response = match execute_bounded_cancellable(execution, cancel_rx).await {
                        Ok(output) => {
                            let status = if output.cancelled {
                                ExecutionStatus::Cancelled
                            } else if output.timed_out {
                                ExecutionStatus::TimedOut
                            } else if output.exit_status.is_some_and(|status| status.success()) {
                                ExecutionStatus::Completed
                            } else {
                                ExecutionStatus::Failed
                            };
                            ExecutorResponse::ExecutionResult {
                                protocol: PROTOCOL,
                                request_id: request_id.clone(),
                                status,
                                exit_code: output.exit_status.and_then(|status| status.code()),
                                stdout: String::from_utf8_lossy(&output.stdout.bytes).into_owned(),
                                stderr: String::from_utf8_lossy(&output.stderr.bytes).into_owned(),
                                stdout_truncated: output.stdout.truncated,
                                stderr_truncated: output.stderr.truncated,
                                code: None,
                            }
                        }
                        Err(_) => ExecutorResponse::ExecutionResult {
                            protocol: PROTOCOL,
                            request_id: request_id.clone(),
                            status: ExecutionStatus::Failed,
                            exit_code: None,
                            stdout: String::new(),
                            stderr: String::new(),
                            stdout_truncated: false,
                            stderr_truncated: false,
                            code: Some("execution_failed"),
                        },
                    };
                    service.in_flight.lock().await.remove(&request_id);
                    let _ = service.responses.send(response);
                });
            }
            Ok(ExecutorRequest::Cancel(request)) => self.cancel(request).await,
            Err(_) => {
                let _ = self
                    .responses
                    .send(ExecutorResponse::protocol_error("unknown".to_owned()));
            }
        }
    }

    async fn cancel(&self, request: CancelRequest) {
        if request.protocol != PROTOCOL {
            let _ = self
                .responses
                .send(ExecutorResponse::protocol_error(request.request_id));
            return;
        }
        let cancel = self
            .in_flight
            .lock()
            .await
            .get(&request.target_request_id)
            .cloned();
        let accepted = cancel.is_some();
        if let Some(cancel) = cancel {
            let _ = cancel.send(true);
        }
        let _ = self.responses.send(ExecutorResponse::CancelAcknowledged {
            protocol: PROTOCOL,
            request_id: request.request_id,
            target_request_id: request.target_request_id,
            accepted,
        });
    }

    fn send_denied(&self, request_id: String, code: &'static str) {
        let _ = self.responses.send(ExecutorResponse::ExecutionResult {
            protocol: PROTOCOL,
            request_id,
            status: ExecutionStatus::Denied,
            exit_code: None,
            stdout: String::new(),
            stderr: String::new(),
            stdout_truncated: false,
            stderr_truncated: false,
            code: Some(code),
        });
    }

    async fn has_in_flight(&self) -> bool {
        !self.in_flight.lock().await.is_empty()
    }
}

pub async fn serve_jsonl<R, W>(policy: TrustedPolicy, reader: R, mut writer: W) -> io::Result<()>
where
    R: AsyncBufRead + Unpin,
    W: AsyncWrite + Unpin,
{
    let (service, mut responses) = ExecutorService::new(policy);
    let mut lines = reader.lines();
    let mut input_open = true;
    loop {
        if !input_open && !service.has_in_flight().await {
            while let Ok(response) = responses.try_recv() {
                write_response(&mut writer, response).await?;
            }
            break;
        }
        tokio::select! {
            line = lines.next_line(), if input_open => match line? {
                Some(line) => service.submit_line(&line).await,
                None => input_open = false,
            },
            response = responses.recv() => {
                let Some(response) = response else { break };
                write_response(&mut writer, response).await?;
            }
        }
    }
    Ok(())
}

async fn write_response<W>(writer: &mut W, response: ExecutorResponse) -> io::Result<()>
where
    W: AsyncWrite + Unpin,
{
    let line = serde_json::to_vec(&response).map_err(io::Error::other)?;
    writer.write_all(&line).await?;
    writer.write_all(b"\n").await?;
    writer.flush().await
}
