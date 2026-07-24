use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use dci_controlled_executor::policy::{PolicyConfig, TrustedPolicy};
use dci_controlled_executor::service::serve_jsonl;
use serde_json::{Value, json};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::time::timeout;

static NEXT_WORKSPACE: AtomicU64 = AtomicU64::new(0);

fn policy() -> (TrustedPolicy, PathBuf) {
    let nonce = NEXT_WORKSPACE.fetch_add(1, Ordering::Relaxed);
    let workspace = std::env::temp_dir().join(format!(
        "dci-executor-service-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir_all(&workspace).expect("workspace");
    let policy = TrustedPolicy::try_from(PolicyConfig {
        workspace_root: workspace.clone(),
        programs: BTreeMap::from([("python".to_owned(), PathBuf::from("/usr/bin/python3"))]),
        max_deadline_ms: 30_000,
        max_output_bytes: 65_536,
        max_concurrency: 4,
    })
    .expect("policy");
    (policy, workspace)
}

fn execute(request_id: &str, delay: &str, output: &str) -> Value {
    json!({
        "protocol": "dci.executor/v1",
        "request_id": request_id,
        "type": "execute",
        "program_id": "python",
        "arguments": ["-c", "import sys,time; time.sleep(float(sys.argv[1])); print(sys.argv[2])", delay, output],
        "cwd": ".",
        "deadline_ms": 5000,
        "max_output_bytes": 4096
    })
}

async fn start_service() -> (
    tokio::io::WriteHalf<tokio::io::DuplexStream>,
    tokio::io::Lines<BufReader<tokio::io::ReadHalf<tokio::io::DuplexStream>>>,
    PathBuf,
) {
    let (policy, workspace) = policy();
    let (client, server) = tokio::io::duplex(65_536);
    let (server_read, server_write) = tokio::io::split(server);
    tokio::spawn(serve_jsonl(
        policy,
        BufReader::new(server_read),
        server_write,
    ));
    let (client_read, client_write) = tokio::io::split(client);
    (client_write, BufReader::new(client_read).lines(), workspace)
}

async fn send(writer: &mut tokio::io::WriteHalf<tokio::io::DuplexStream>, value: &Value) {
    writer
        .write_all(format!("{value}\n").as_bytes())
        .await
        .expect("write request");
}

async fn response(
    lines: &mut tokio::io::Lines<BufReader<tokio::io::ReadHalf<tokio::io::DuplexStream>>>,
) -> Value {
    let line = timeout(Duration::from_secs(2), lines.next_line())
        .await
        .expect("response timeout")
        .expect("read response")
        .expect("response line");
    serde_json::from_str(&line).expect("response json")
}

#[tokio::test]
async fn service_keeps_input_responsive_and_emits_out_of_order_results() {
    let (mut writer, mut lines, workspace) = start_service().await;
    send(&mut writer, &execute("slow", "0.3", "slow")).await;
    send(&mut writer, &execute("fast", "0", "fast")).await;

    let first = response(&mut lines).await;
    let second = response(&mut lines).await;

    assert_eq!(first["request_id"], "fast");
    assert_eq!(second["request_id"], "slow");
    fs::remove_dir_all(workspace).expect("cleanup");
}

#[tokio::test]
async fn duplicate_in_flight_request_id_is_denied() {
    let (mut writer, mut lines, workspace) = start_service().await;
    send(&mut writer, &execute("duplicate", "0.2", "first")).await;
    send(&mut writer, &execute("duplicate", "0", "second")).await;

    let first = response(&mut lines).await;
    let second = response(&mut lines).await;

    let responses = [first, second];
    assert_eq!(
        responses
            .iter()
            .filter(|item| item["status"] == "denied")
            .count(),
        1
    );
    assert_eq!(
        responses
            .iter()
            .filter(|item| item["status"] == "completed")
            .count(),
        1
    );
    fs::remove_dir_all(workspace).expect("cleanup");
}

#[tokio::test]
async fn accepted_cancel_emits_ack_and_exactly_one_cancelled_terminal_result() {
    let (mut writer, mut lines, workspace) = start_service().await;
    send(&mut writer, &execute("target", "10", "late")).await;
    send(
        &mut writer,
        &json!({
            "protocol": "dci.executor/v1",
            "request_id": "cancel-1",
            "type": "cancel",
            "target_request_id": "target"
        }),
    )
    .await;

    let first = response(&mut lines).await;
    let second = response(&mut lines).await;
    let responses = [first, second];

    assert!(
        responses
            .iter()
            .any(|item| { item["type"] == "cancel.acknowledged" && item["accepted"] == true })
    );
    assert_eq!(
        responses
            .iter()
            .filter(|item| item["type"] == "execution.result"
                && item["request_id"] == "target"
                && item["status"] == "cancelled")
            .count(),
        1
    );
    assert!(
        timeout(Duration::from_millis(100), lines.next_line())
            .await
            .is_err(),
        "duplicate terminal result emitted"
    );
    fs::remove_dir_all(workspace).expect("cleanup");
}

#[tokio::test]
async fn malformed_json_returns_safe_error_without_echoing_input() {
    let (mut writer, mut lines, workspace) = start_service().await;
    writer
        .write_all(b"{\"secret\":\"TOP-SECRET\"\n")
        .await
        .expect("write malformed request");

    let error = response(&mut lines).await;

    assert_eq!(error["type"], "protocol.error");
    assert_eq!(error["code"], "invalid_request");
    assert!(!error.to_string().contains("TOP-SECRET"));
    fs::remove_dir_all(workspace).expect("cleanup");
}
