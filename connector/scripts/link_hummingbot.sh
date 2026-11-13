#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HB_DIR="${1:-$REPO_DIR/hummingbot}"

[[ -d "$HB_DIR/hummingbot/connector/derivative" ]] || { echo "not a Hummingbot checkout: $HB_DIR" >&2; exit 1; }

link() {
  local target="$1" link_path="$2"
  if [[ -e "$link_path" && ! -L "$link_path" ]]; then
    echo "refusing to replace a real directory: $link_path" >&2
    exit 1
  fi
  ln -sfn "$target" "$link_path"
  echo "linked $link_path -> $target"
}

link "$REPO_DIR/connector/neutronx_perpetual" "$HB_DIR/hummingbot/connector/derivative/neutronx_perpetual"
link "$REPO_DIR/connector/tests" "$HB_DIR/test/hummingbot/connector/derivative/neutronx_perpetual"

if [[ -x "$HB_DIR/.venv/bin/python" ]]; then
  VIRTUAL_ENV="$HB_DIR/.venv" uv pip install -q -e "$REPO_DIR/sdk"
  echo "installed neutronx-sdk into $HB_DIR/.venv"
fi
