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

pkill -f 'agent-switchboard|openclaw-voice-server|agent_switchboard\.app' || true

LOG_FILE="${AGENT_SWITCHBOARD_LOG_FILE:-/tmp/agent-switchboard.log}"
nohup "$PYTHON_BIN" -m agent_switchboard.app >"$LOG_FILE" 2>&1 </dev/null &

echo "agent-switchboard restarted in background"
echo "pid: $!"
echo "log: $LOG_FILE"
