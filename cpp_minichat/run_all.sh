#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RPC_DIR="$ROOT/cpp_rpc_lab"
CHAT_DIR="$ROOT/cpp_minichat"
RPC_PORT="${RPC_PORT:-18888}"
CHAT_PORT="${CHAT_PORT:-19191}"

echo "[1/4] building rpc user service"
make -C "$RPC_DIR"

echo "[2/4] building minichat"
make -C "$CHAT_DIR"

echo "[3/4] starting rpc user service on 127.0.0.1:$RPC_PORT"
"$RPC_DIR/rpc_server" "$RPC_PORT" &
RPC_PID=$!

cleanup() {
  echo
  echo "stopping services"
  kill "$RPC_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

sleep 1

echo "[4/4] starting minichat on http://127.0.0.1:$CHAT_PORT/"
echo "open: http://127.0.0.1:$CHAT_PORT/"
"$CHAT_DIR/minichat" "$CHAT_PORT" "127.0.0.1" "$RPC_PORT"
