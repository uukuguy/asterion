use std::env;
use std::fs;
use std::process::ExitCode;

use dci_controlled_executor::policy::{PolicyConfig, TrustedPolicy};
use dci_controlled_executor::service::serve_jsonl;
use tokio::io::BufReader;

#[tokio::main]
async fn main() -> ExitCode {
    match run().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(()) => {
            eprintln!("controlled executor failed");
            ExitCode::FAILURE
        }
    }
}

async fn run() -> Result<(), ()> {
    let mut arguments = env::args_os();
    let _program = arguments.next();
    let policy_path = arguments.next().ok_or(())?;
    if arguments.next().is_some() {
        return Err(());
    }
    let config: PolicyConfig =
        serde_json::from_slice(&fs::read(policy_path).map_err(|_| ())?).map_err(|_| ())?;
    let policy = TrustedPolicy::try_from(config).map_err(|_| ())?;
    serve_jsonl(
        policy,
        BufReader::new(tokio::io::stdin()),
        tokio::io::stdout(),
    )
    .await
    .map_err(|_| ())
}
