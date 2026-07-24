use std::collections::BTreeMap;
use std::fmt;
use std::path::{Path, PathBuf};

use serde::Deserialize;

use crate::protocol::{ExecuteRequest, PROTOCOL};

const MAX_DEADLINE_MS: u64 = 86_400_000;
const MAX_OUTPUT_BYTES: usize = 16_777_216;
const MAX_CONCURRENCY: usize = 256;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyConfig {
    pub workspace_root: PathBuf,
    pub programs: BTreeMap<String, PathBuf>,
    pub max_deadline_ms: u64,
    pub max_output_bytes: usize,
    pub max_concurrency: usize,
}

#[derive(Debug)]
pub struct TrustedPolicy {
    workspace_root: PathBuf,
    programs: BTreeMap<String, PathBuf>,
    pub max_deadline_ms: u64,
    pub max_output_bytes: usize,
    pub max_concurrency: usize,
}

#[derive(Debug, Eq, PartialEq)]
pub struct AuthorizedExecution {
    request_id: String,
    executable: PathBuf,
    arguments: Vec<String>,
    cwd: PathBuf,
    deadline_ms: u64,
    max_output_bytes: usize,
}

#[derive(Debug, Eq, PartialEq)]
pub struct PolicyError(&'static str);

#[derive(Debug, Eq, PartialEq)]
pub struct AuthorizationError(&'static str);

impl fmt::Display for PolicyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.0)
    }
}

impl std::error::Error for PolicyError {}

impl fmt::Display for AuthorizationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.0)
    }
}

impl std::error::Error for AuthorizationError {}

impl TryFrom<PolicyConfig> for TrustedPolicy {
    type Error = PolicyError;

    fn try_from(config: PolicyConfig) -> Result<Self, Self::Error> {
        let workspace_root = config
            .workspace_root
            .canonicalize()
            .map_err(|_| PolicyError("workspace root is unavailable"))?;
        if !workspace_root.is_dir() {
            return Err(PolicyError("workspace root is not a directory"));
        }
        if config.programs.is_empty() {
            return Err(PolicyError("program allowlist is empty"));
        }
        if !(1..=MAX_DEADLINE_MS).contains(&config.max_deadline_ms) {
            return Err(PolicyError("deadline limit is invalid"));
        }
        if !(1..=MAX_OUTPUT_BYTES).contains(&config.max_output_bytes) {
            return Err(PolicyError("output limit is invalid"));
        }
        if !(1..=MAX_CONCURRENCY).contains(&config.max_concurrency) {
            return Err(PolicyError("concurrency limit is invalid"));
        }

        let mut programs = BTreeMap::new();
        for (program_id, path) in config.programs {
            if program_id.is_empty() || !path.is_absolute() {
                return Err(PolicyError("program entry is invalid"));
            }
            let path = path
                .canonicalize()
                .map_err(|_| PolicyError("program is unavailable"))?;
            if !path.is_file() {
                return Err(PolicyError("program is not a file"));
            }
            programs.insert(program_id, path);
        }

        Ok(Self {
            workspace_root,
            programs,
            max_deadline_ms: config.max_deadline_ms,
            max_output_bytes: config.max_output_bytes,
            max_concurrency: config.max_concurrency,
        })
    }
}

impl TrustedPolicy {
    pub fn workspace_root(&self) -> &Path {
        &self.workspace_root
    }

    pub fn program(&self, program_id: &str) -> Option<&Path> {
        self.programs.get(program_id).map(PathBuf::as_path)
    }

    pub fn authorize(
        &self,
        request: ExecuteRequest,
    ) -> Result<AuthorizedExecution, AuthorizationError> {
        if request.protocol != PROTOCOL {
            return Err(AuthorizationError("protocol is unsupported"));
        }
        let executable = self
            .programs
            .get(&request.program_id)
            .cloned()
            .ok_or(AuthorizationError("program is not authorized"))?;
        if request.deadline_ms == 0 || request.deadline_ms > self.max_deadline_ms {
            return Err(AuthorizationError("deadline exceeds policy"));
        }
        if request.max_output_bytes == 0 || request.max_output_bytes > self.max_output_bytes {
            return Err(AuthorizationError("output limit exceeds policy"));
        }
        if request.cwd.is_absolute() {
            return Err(AuthorizationError("working directory must be relative"));
        }

        let cwd = self
            .workspace_root
            .join(&request.cwd)
            .canonicalize()
            .map_err(|_| AuthorizationError("working directory is unavailable"))?;
        if !cwd.starts_with(&self.workspace_root) {
            return Err(AuthorizationError("working directory is outside workspace"));
        }
        if !cwd.is_dir() {
            return Err(AuthorizationError("working directory is unavailable"));
        }

        Ok(AuthorizedExecution {
            request_id: request.request_id,
            executable,
            arguments: request.arguments,
            cwd,
            deadline_ms: request.deadline_ms,
            max_output_bytes: request.max_output_bytes,
        })
    }
}

impl AuthorizedExecution {
    pub fn request_id(&self) -> &str {
        &self.request_id
    }

    pub fn executable(&self) -> &Path {
        &self.executable
    }

    pub fn arguments(&self) -> &[String] {
        &self.arguments
    }

    pub fn cwd(&self) -> &Path {
        &self.cwd
    }

    pub fn deadline_ms(&self) -> u64 {
        self.deadline_ms
    }

    pub fn max_output_bytes(&self) -> usize {
        self.max_output_bytes
    }
}
