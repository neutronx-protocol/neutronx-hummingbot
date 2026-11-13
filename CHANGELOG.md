# Changelog

Notable changes to the connector and the SDK. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-11-13

### Connector

- Orders carry the leverage the market allows at the moment, which open interest can lower below
  the market maximum.
- A market order is priced by the market's slippage limit instead of a fixed 5%.
- Verified on mainnet (chain v1.81.2) in addition to the testnet.
- The connector warns at start when the wallet holds less than 0.1 USDC for transaction fees.
- A failed cancel of a lost order no longer stops the remaining lost orders from being cancelled.
- The main connector class is covered by the shared Hummingbot derivative test suite.

### SDK

- `Market` gains `effective_max_leverage` and `max_slippage`.
- Python 3.13 is tested and declared as supported.

## [0.1.0] - 2026-11-13

First version. The SDK is published on PyPI as
[`neutronx-sdk`](https://pypi.org/project/neutronx-sdk/0.1.0/).

### Connector

- `neutronx_perpetual` and `neutronx_perpetual_testnet` for Hummingbot 2.17.0.
- `LIMIT`, `LIMIT_MAKER` and `MARKET` orders, one-way positions, per-pair leverage.
- Signing with an agent key or the account's own key.
- Order, fill and position updates from the indexer WebSocket, reconciled against the chain.
- Batching of cancels and resting orders into one transaction.
- Back-off on indexer rate limits and a separate budget for network checks.

### SDK

- Keys, mnemonics, account and agent wallets.
- Order messages, transaction building and signing, gas floors.
- gRPC queries, broadcasting with confirmation, account sequence handling.
- Models and paths of the public indexer API.

[Unreleased]: https://github.com/neutronx-protocol/neutronx-hummingbot/compare/sdk-v0.1.1...HEAD
[0.1.1]: https://github.com/neutronx-protocol/neutronx-hummingbot/releases/tag/sdk-v0.1.1
[0.1.0]: https://github.com/neutronx-protocol/neutronx-hummingbot/releases/tag/sdk-v0.1.0
