# Changelog

Notable changes to the connector and the SDK. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0]

First version.

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
