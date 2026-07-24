use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use dci_controlled_executor::policy::{PolicyConfig, TrustedPolicy};

fn workspace() -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let path = std::env::temp_dir().join(format!("dci-executor-policy-{nonce}"));
    fs::create_dir_all(&path).expect("workspace");
    path
}

fn config(workspace_root: PathBuf) -> PolicyConfig {
    PolicyConfig {
        workspace_root,
        programs: BTreeMap::from([(
            "fixture".to_owned(),
            std::env::current_exe().expect("test executable"),
        )]),
        max_deadline_ms: 30_000,
        max_output_bytes: 65_536,
        max_concurrency: 2,
    }
}

#[test]
fn canonicalizes_trusted_workspace_and_programs() {
    let workspace_root = workspace();
    let policy = TrustedPolicy::try_from(config(workspace_root.clone())).expect("policy");

    assert_eq!(
        policy.workspace_root(),
        workspace_root.canonicalize().expect("canonical workspace")
    );
    assert!(policy.program("fixture").expect("program").is_absolute());
    fs::remove_dir_all(workspace_root).expect("cleanup");
}

#[test]
fn rejects_relative_programs_and_invalid_resource_limits() {
    let workspace_root = workspace();
    let mut relative = config(workspace_root.clone());
    relative
        .programs
        .insert("fixture".to_owned(), PathBuf::from("bin/tool"));
    assert!(TrustedPolicy::try_from(relative).is_err());

    let mut no_deadline = config(workspace_root.clone());
    no_deadline.max_deadline_ms = 0;
    assert!(TrustedPolicy::try_from(no_deadline).is_err());

    let mut no_concurrency = config(workspace_root.clone());
    no_concurrency.max_concurrency = 0;
    assert!(TrustedPolicy::try_from(no_concurrency).is_err());
    fs::remove_dir_all(workspace_root).expect("cleanup");
}
