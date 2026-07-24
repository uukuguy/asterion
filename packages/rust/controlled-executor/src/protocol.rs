use std::path::PathBuf;

use serde::{Deserialize, Serialize};

pub const PROTOCOL: &str = "dci.executor/v1";

#[derive(Debug, Deserialize)]
#[serde(tag = "type")]
pub enum ExecutorRequest {
    #[serde(rename = "execute")]
    Execute(ExecuteRequest),
    #[serde(rename = "cancel")]
    Cancel(CancelRequest),
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecuteRequest {
    pub protocol: String,
    pub request_id: String,
    pub program_id: String,
    pub arguments: Vec<String>,
    pub cwd: PathBuf,
    pub deadline_ms: u64,
    pub max_output_bytes: usize,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CancelRequest {
    pub protocol: String,
    pub request_id: String,
    pub target_request_id: String,
}

#[derive(Debug, Serialize)]
#[serde(tag = "type")]
pub enum ExecutorResponse {
    #[serde(rename = "execution.result")]
    ExecutionResult {
        protocol: &'static str,
        request_id: String,
        status: ExecutionStatus,
        exit_code: Option<i32>,
        stdout: String,
        stderr: String,
        stdout_truncated: bool,
        stderr_truncated: bool,
        code: Option<&'static str>,
    },
    #[serde(rename = "cancel.acknowledged")]
    CancelAcknowledged {
        protocol: &'static str,
        request_id: String,
        target_request_id: String,
        accepted: bool,
    },
    #[serde(rename = "protocol.error")]
    ProtocolError {
        protocol: &'static str,
        request_id: String,
        code: &'static str,
        message: &'static str,
    },
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ExecutionStatus {
    Completed,
    Failed,
    TimedOut,
    Cancelled,
    Denied,
}

impl ExecutorResponse {
    pub fn protocol_error(request_id: String) -> Self {
        Self::ProtocolError {
            protocol: PROTOCOL,
            request_id,
            code: "invalid_request",
            message: "request is invalid",
        }
    }
}
