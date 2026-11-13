from __future__ import annotations

from dataclasses import dataclass, replace

BECH32_PREFIX = "neutronx"
FEE_DENOM = "untx"
MARGIN_DECIMALS = 6


@dataclass(frozen=True)
class Network:
    name: str
    chain_id: str
    grpc_endpoint: str
    secure: bool
    margin_denom: str
    bech32_prefix: str = BECH32_PREFIX
    fee_denom: str = FEE_DENOM
    margin_decimals: int = MARGIN_DECIMALS
    indexer_url: str | None = None
    indexer_ws_url: str | None = None

    def with_endpoint(self, grpc_endpoint: str, *, secure: bool) -> Network:
        return replace(self, grpc_endpoint=grpc_endpoint, secure=secure)

    def with_indexer(self, indexer_url: str, indexer_ws_url: str) -> Network:
        return replace(self, indexer_url=indexer_url.rstrip("/"), indexer_ws_url=indexer_ws_url)


MAINNET = Network(
    name="mainnet",
    chain_id="neutronx-1",
    grpc_endpoint="grpc.neutronchain.io:443",
    secure=True,
    margin_denom="ibc/ED4C195406CEFBAC6CF3AA64BBF84292910D27B51C78D81374101F9424BC1EC1",
    indexer_url="https://api.neutronx.com/v1",
    indexer_ws_url="wss://api.neutronx.com/v1/ws",
)

TESTNET = Network(
    name="testnet",
    chain_id="neutronx-testnet-1",
    grpc_endpoint="testnet-rpc.neutronchain.io:9090",
    secure=False,
    margin_denom="ibc/6A99DEC6CDF3A99035FEE19CABC747D6B09984E697E5E974E6562B66F0654857",
    indexer_url="https://indexer-test.neutronchain.io/v1",
    indexer_ws_url="wss://indexer-test.neutronchain.io/v1/ws",
)
