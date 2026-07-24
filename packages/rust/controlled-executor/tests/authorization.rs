use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use dci_controlled_executor::policy::{PolicyConfig, TrustedPolicy};
use dci_controlled_executor::protocol::{ExecuteRequest, ExecutorRequest};

fn workspace() -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let path = std::env::temp_dir().join(format!("dci-executor-authorization-{nonce}"));
    fs::create_dir_all(path.join("nested")).expect("workspace");
    path
}

fn policy(workspace_root: PathBuf) -> TrustedPolicy {
    TrustedPolicy::try_from(PolicyConfig {
        workspace_root,
        programs: BTreeMap::from([(
            "fixture".to_owned(),
            std::env::current_exe().expect("test executable"),
        )]),
        max_deadline_ms: 30_000,
        max_output_bytes: 65_536,
        max_concurrency: 2,
    })
    .expect("policy")
}

fn request() -> ExecuteRequest {
    ExecuteRequest {
        protocol: "dci.executor/v1".to_owned(),
        request_id: "request-1".to_owned(),
        program_id: "fixture".to_owned(),
        arguments: vec!["--flag".to_owned(), "literal value".to_owned()],
        cwd: PathBuf::from("nested"),
        deadline_ms: 1_000,
        max_output_bytes: 4_096,
    }
}

#[test]
fn denies_unknown_program_id() {
    let workspace_root = workspace();
    let trusted = policy(workspace_root.clone());
    let mut execute = request();
    execute.program_id = "missing".to_owned();

    let error = trusted
        .authorize(execute)
        .expect_err("unknown program denied");

    assert_eq!(error.to_string(), "program is not authorized");
    fs::remove_dir_all(workspace_root).expect("cleanup");
}

#[test]
fn denies_cwd_escape_and_missing_directory() {
    let workspace_root = workspace();
    let trusted = policy(workspace_root.clone());

    let mut escaped = request();
    escaped.cwd = PathBuf::from("..");
    assert_eq!(
        trusted
            .authorize(escaped)
            .expect_err("escape denied")
            .to_string(),
        "working directory is outside workspace"
    );

    let mut missing = request();
    missing.cwd = PathBuf::from("missing");
    assert_eq!(
        trusted
            .authorize(missing)
            .expect_err("missing denied")
            .to_string(),
        "working directory is unavailable"
    );

    let mut absolute = request();
    absolute.cwd = workspace_root.join("nested");
    assert_eq!(
        trusted
            .authorize(absolute)
            .expect_err("absolute cwd denied")
            .to_string(),
        "working directory must be relative"
    );
    fs::remove_dir_all(workspace_root).expect("cleanup");
}

#[test]
fn deserializes_closed_execute_wire_request() {
    let wire = serde_json::json!({
        "protocol": "dci.executor/v1",
        "request_id": "request-1",
        "type": "execute",
        "program_id": "fixture",
        "arguments": ["--flag"],
        "cwd": "nested",
        "deadline_ms": 1000,
        "max_output_bytes": 4096
    });

    let parsed: ExecutorRequest = serde_json::from_value(wire.clone()).expect("request");
    let ExecutorRequest::Execute(request) = parsed else {
        panic!("execute fixture parsed as cancel");
    };
    assert_eq!(request.program_id, "fixture");

    let mut unknown = wire;
    unknown["environment"] = serde_json::json!({"TOKEN": "not-allowed"});
    assert!(serde_json::from_value::<ExecutorRequest>(unknown).is_err());
}

#[test]
fn denies_request_limits_outside_trusted_policy() {
    let workspace_root = workspace();
    let trusted = policy(workspace_root.clone());

    let mut deadline = request();
    deadline.deadline_ms = 30_001;
    assert_eq!(
        trusted
            .authorize(deadline)
            .expect_err("deadline denied")
            .to_string(),
        "deadline exceeds policy"
    );

    let mut output = request();
    output.max_output_bytes = 65_537;
    assert_eq!(
        trusted
            .authorize(output)
            .expect_err("output denied")
            .to_string(),
        "output limit exceeds policy"
    );
    fs::remove_dir_all(workspace_root).expect("cleanup");
}

#[test]
fn valid_request_produces_only_canonical_bounded_execution_values() {
    let workspace_root = workspace();
    let trusted = policy(workspace_root.clone());
    let expected_program = std::env::current_exe()
        .expect("test executable")
        .canonicalize()
        .expect("canonical executable");

    let authorized = trusted.authorize(request()).expect("authorized");

    assert_eq!(authorized.request_id(), "request-1");
    assert_eq!(authorized.executable(), expected_program);
    assert_eq!(
        authorized.cwd(),
        workspace_root.join("nested").canonicalize().expect("cwd")
    );
    assert_eq!(authorized.arguments(), ["--flag", "literal value"]);
    assert_eq!(authorized.deadline_ms(), 1_000);
    assert_eq!(authorized.max_output_bytes(), 4_096);
    fs::remove_dir_all(workspace_root).expect("cleanup");
}
