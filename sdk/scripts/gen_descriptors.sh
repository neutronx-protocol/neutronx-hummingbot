#!/usr/bin/env bash
set -euo pipefail

SDK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHAIN_REPO="${CHAIN_REPO:?set CHAIN_REPO to a checkout of the chain repository}"
CHAIN_REF="${CHAIN_REF:?set CHAIN_REF to the chain release tag to build from}"
OUT_DIR="$SDK_DIR/src/neutronx_sdk/proto"

for tool in buf go git uv; do
  command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 1; }
done
[[ -d "$CHAIN_REPO/.git" ]] || { echo "CHAIN_REPO is not a git checkout: $CHAIN_REPO" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git -C "$CHAIN_REPO" archive "$CHAIN_REF" proto go.mod | tar -x -C "$WORK"
SDK_VERSION="$(awk '$1 == "github.com/cosmos/cosmos-sdk" { print $2; exit }' "$WORK/go.mod")"
[[ -n "$SDK_VERSION" ]] || { echo "cosmos-sdk version not found in go.mod at $CHAIN_REF" >&2; exit 1; }
SDK_PROTO="$(cd "$WORK" && GOFLAGS=-mod=mod go mod download -json "github.com/cosmos/cosmos-sdk@$SDK_VERSION" | awk -F'"' '/"Dir":/ { print $4 }')/proto"
[[ -d "$SDK_PROTO" ]] || { echo "cosmos-sdk protos not found: $SDK_PROTO" >&2; exit 1; }

buf export "$SDK_PROTO" --output "$WORK/export"
buf export "$WORK/proto" --output "$WORK/chain"
cp -R "$WORK/chain/neutronx" "$WORK/export/"

FILES=(
  cosmos/auth/v1beta1/auth.proto
  cosmos/auth/v1beta1/query.proto
  cosmos/bank/v1beta1/query.proto
  cosmos/base/abci/v1beta1/abci.proto
  cosmos/base/node/v1beta1/query.proto
  cosmos/base/tendermint/v1beta1/query.proto
  cosmos/crypto/secp256k1/keys.proto
  cosmos/tx/signing/v1beta1/signing.proto
  cosmos/tx/v1beta1/service.proto
  cosmos/tx/v1beta1/tx.proto
  neutronx/agentkeys/v1/extension.proto
  neutronx/agentkeys/v1/params.proto
  neutronx/agentkeys/v1/query.proto
  neutronx/agentkeys/v1/state.proto
  neutronx/agentkeys/v1/tx.proto
  neutronx/oracle/v1/query.proto
  neutronx/orderbook/v1/events.proto
  neutronx/orderbook/v1/query.proto
  neutronx/orderbook/v1/tx.proto
  neutronx/orderbook/v1/types.proto
  neutronx/perps/v1/events.proto
  neutronx/perps/v1/params.proto
  neutronx/perps/v1/query.proto
  neutronx/perps/v1/state.proto
  neutronx/perps/v1/tx.proto
)

PATH_ARGS=()
for f in "${FILES[@]}"; do
  [[ -f "$WORK/export/$f" ]] || { echo "missing proto: $f" >&2; exit 1; }
  PATH_ARGS+=(--path "$WORK/export/$f")
done

buf build "$WORK/export" "${PATH_ARGS[@]}" --as-file-descriptor-set --exclude-source-info -o "$OUT_DIR/descriptors.binpb"
uv run --project "$SDK_DIR" python "$SDK_DIR/scripts/trim_descriptors.py" "$OUT_DIR/descriptors.binpb"
printf '%s cosmos-sdk %s\n' "$CHAIN_REF" "$SDK_VERSION" > "$OUT_DIR/descriptors.ref"
echo "descriptors for $CHAIN_REF (cosmos-sdk $SDK_VERSION) written to $OUT_DIR"
