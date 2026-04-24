#!/usr/bin/env bash
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  SOURCE_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  if [[ "$SOURCE" != /* ]]; then
    SOURCE="$SOURCE_DIR/$SOURCE"
  fi
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing Python virtualenv at $PYTHON_BIN" >&2
  exit 1
fi

stop_existing() {
  local pattern="$1"
  local pids
  pids="$(pgrep -f "$pattern" | grep -v "^$$$" || true)"
  if [[ -z "$pids" ]]; then
    return
  fi
  xargs -r kill <<<"$pids"
  sleep 0.5
  xargs -r kill -KILL <<<"$pids" 2>/dev/null || true
}

stop_existing 'python.*-m maras_switchboard\.app'
stop_existing 'python.*-m agent_switchboard\.app'

LOG_FILE="${MARAS_SWITCHBOARD_LOG_FILE:-/tmp/maras-switchboard.log}"
setsid "$PYTHON_BIN" -m maras_switchboard.app >"$LOG_FILE" 2>&1 </dev/null &

echo "maras-switchboard restarted in background"
echo "pid: $!"
echo "log: $LOG_FILE"
