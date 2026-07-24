#!/usr/bin/env bash
set -euo pipefail

CHECK_ONLY=0
if [ "$#" -gt 1 ] || { [ "$#" -eq 1 ] && [ "$1" != "--check" ]; }; then
    echo "Usage: $0 [--check]" >&2
    exit 2
fi
if [ "$#" -eq 1 ]; then
    CHECK_ONLY=1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_REPO_URL="${DCI_PI_REPO_URL:-https://github.com/earendil-works/pi.git}"
PI_DIR="${DCI_PI_DIR:-$PROJECT_ROOT/pi}"
case "$PI_DIR" in
    /*) ;;
    *) PI_DIR="$PROJECT_ROOT/${PI_DIR#./}" ;;
esac

if [ -L "$PI_DIR" ]; then
    echo "ERROR: DCI_PI_DIR must not be a symlink: $PI_DIR" >&2
    exit 2
fi

PI_LOCK_FILE="$PROJECT_ROOT/pi-revision.txt"
PI_REVISION="${DCI_PI_REVISION:-}"
if [ -z "$PI_REVISION" ]; then
    if [ ! -f "$PI_LOCK_FILE" ]; then
        echo "ERROR: Missing Pi revision lock: $PI_LOCK_FILE" >&2
        exit 2
    fi
    PI_REVISION="$(tr -d '[:space:]' < "$PI_LOCK_FILE")"
fi
case "$PI_REVISION" in
    ""|*[!0-9a-fA-F]*)
        echo "ERROR: Pi revision must be one full 40-character Git commit." >&2
        exit 2
        ;;
esac
if [ "${#PI_REVISION}" -ne 40 ]; then
    echo "ERROR: Pi revision must be one full 40-character Git commit." >&2
    exit 2
fi

if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: Node.js 22.19.0 or newer is required for the locked Pi checkout." >&2
    exit 2
fi
NODE_VERSION="$(node --version 2>/dev/null || true)"
if [[ ! "$NODE_VERSION" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] || {
    [ "${BASH_REMATCH[1]:-0}" -lt 22 ] ||
    { [ "${BASH_REMATCH[1]:-0}" -eq 22 ] && [ "${BASH_REMATCH[2]:-0}" -lt 19 ]; }
}; then
    echo "ERROR: Node.js 22.19.0 or newer is required for the locked Pi checkout." >&2
    exit 2
fi
if [ "$CHECK_ONLY" -eq 0 ] && ! command -v npm >/dev/null 2>&1; then
    echo "ERROR: npm is required to install the locked Pi dependencies." >&2
    exit 2
fi

source_changed=0
cloned=0
if [ "$CHECK_ONLY" -eq 1 ] && [ ! -e "$PI_DIR" ]; then
    echo "ERROR: Pi checkout does not exist for read-only verification: $PI_DIR" >&2
    exit 4
fi
if [ ! -e "$PI_DIR" ]; then
    echo "==> Cloning Pi into $PI_DIR without selecting a moving branch..."
    mkdir -p "$(dirname "$PI_DIR")"
    git clone --no-checkout "$PI_REPO_URL" "$PI_DIR"
    cloned=1
elif ! git -C "$PI_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ERROR: DCI_PI_DIR is not a Git worktree: $PI_DIR" >&2
    exit 2
fi

desired_commit="$(
    git -C "$PI_DIR" rev-parse --verify "$PI_REVISION^{commit}" 2>/dev/null || true
)"
if [ -z "$desired_commit" ]; then
    if [ "$CHECK_ONLY" -eq 1 ]; then
        echo "ERROR: Pi revision $PI_REVISION is not available locally; read-only check will not fetch." >&2
        exit 4
    fi
    echo "==> Fetching requested Pi revision $PI_REVISION..."
    if ! git -C "$PI_DIR" fetch --no-tags origin "$PI_REVISION"; then
        echo "ERROR: Cannot fetch Pi revision $PI_REVISION from $PI_REPO_URL." >&2
        exit 2
    fi
    desired_commit="$(
        git -C "$PI_DIR" rev-parse --verify "FETCH_HEAD^{commit}" 2>/dev/null || true
    )"
fi
if [ -z "$desired_commit" ]; then
    echo "ERROR: Cannot resolve Pi revision $PI_REVISION in $PI_DIR." >&2
    exit 2
fi

current_commit="$(git -C "$PI_DIR" rev-parse --verify HEAD 2>/dev/null || true)"
PI_CLI="$PI_DIR/packages/coding-agent/dist/cli.js"
if [ "$CHECK_ONLY" -eq 1 ]; then
    if [ "$current_commit" != "$desired_commit" ]; then
        echo "ERROR: Pi HEAD $current_commit does not match requested commit $desired_commit." >&2
        exit 4
    fi
    if [ -n "$(git -C "$PI_DIR" status --porcelain)" ]; then
        echo "WARN: Pi is at the requested commit but contains local changes; read-only check accepts the source revision only." >&2
    fi
    if [ ! -f "$PI_DIR/packages/coding-agent/dist/cli.js" ]; then
        echo "ERROR: Pi CLI is not built; run make setup-pi." >&2
        exit 4
    fi
    echo "==> Pi checkout and CLI verified at $desired_commit (read-only check)."
    exit 0
fi

if [ "$cloned" -eq 1 ]; then
    git -C "$PI_DIR" checkout --detach "$desired_commit"
    source_changed=1
elif [ "$current_commit" != "$desired_commit" ]; then
    if [ -n "$(git -C "$PI_DIR" status --porcelain)" ]; then
        echo "ERROR: Pi checkout is dirty at $current_commit; refusing to switch to $desired_commit." >&2
        echo "       Preserve or commit those changes, or set DCI_PI_DIR to another checkout." >&2
        exit 3
    fi
    echo "==> Switching clean Pi checkout from $current_commit to $desired_commit..."
    git -C "$PI_DIR" checkout --detach "$desired_commit"
    source_changed=1
elif [ -n "$(git -C "$PI_DIR" status --porcelain)" ]; then
    if [ ! -f "$PI_CLI" ]; then
        echo "ERROR: Pi checkout is dirty and the built CLI is missing; refusing a non-reproducible build." >&2
        echo "       Preserve or discard those changes, or set DCI_PI_DIR to another checkout." >&2
        exit 3
    fi
    echo "WARN: Pi is at the requested commit but contains local changes; leaving them untouched." >&2
fi

if [ "$source_changed" -eq 1 ] || [ ! -f "$PI_CLI" ]; then
    echo "==> Installing locked Pi dependencies (npm ci --include=dev)..."
    (cd "$PI_DIR" && npm ci --include=dev)
    PI_TSGO="$PI_DIR/node_modules/.bin/tsgo"
    if [ ! -x "$PI_TSGO" ]; then
        echo "ERROR: Locked Pi TypeScript compiler is unavailable after npm ci." >&2
        exit 2
    fi
    echo "==> Building Pi from locked checked-in sources..."
    (cd "$PI_DIR/packages/tui" && npm run build)
    (cd "$PI_DIR/packages/ai" && "$PI_TSGO" -p tsconfig.build.json)
    (cd "$PI_DIR/packages/agent" && npm run build)
    (cd "$PI_DIR/packages/coding-agent" && npm run build)
else
    echo "==> Pi CLI already built at verified commit $desired_commit; skipping build."
fi
