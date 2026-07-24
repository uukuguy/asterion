use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::{Value, json};

static NEXT_WORKSPACE: AtomicU64 = AtomicU64::new(0);

#[test]
fn binary_loads_trusted_policy_and_flushes_in_flight_result_after_stdin_eof() {
    let nonce = NEXT_WORKSPACE.fetch_add(1, Ordering::Relaxed);
    let workspace = std::env::temp_dir().join(format!(
        "dci-executor-operator-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir_all(&workspace).expect("workspace");
    let config_path = workspace.join("policy.json");
    fs::write(
        &config_path,
        serde_json::to_vec(&json!({
            "workspace_root": workspace,
            "programs": {"echo": PathBuf::from("/bin/echo")},
            "max_deadline_ms": 30000,
            "max_output_bytes": 65536,
            "max_concurrency": 2
        }))
        .expect("policy json"),
    )
    .expect("policy file");
    let mut child = Command::new(env!("CARGO_BIN_EXE_dci-controlled-executor"))
        .arg(&config_path)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn executor");
    let request = json!({
        "protocol": "dci.executor/v1",
        "request_id": "exec-1",
        "type": "execute",
        "program_id": "echo",
        "arguments": ["operator-ok"],
        "cwd": ".",
        "deadline_ms": 1000,
        "max_output_bytes": 1024
    });
    writeln!(child.stdin.take().expect("stdin"), "{request}").expect("request");

    let output = child.wait_with_output().expect("wait executor");

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty(), "unexpected diagnostics");
    let lines: Vec<Value> = String::from_utf8(output.stdout)
        .expect("stdout")
        .lines()
        .map(|line| serde_json::from_str(line).expect("JSONL response"))
        .collect();
    assert_eq!(lines.len(), 1);
    assert_eq!(lines[0]["request_id"], "exec-1");
    assert_eq!(lines[0]["status"], "completed");
    assert_eq!(lines[0]["stdout"], "operator-ok\n");
    fs::remove_dir_all(workspace).expect("cleanup");
}
