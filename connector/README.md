# neutronx_perpetual

Hummingbot perpetual connector for NeutronX. It reads market and account data from the public
NeutronX indexer (`/v1` REST and WebSocket) and signs and broadcasts transactions to the chain
through [`neutronx-sdk`](../sdk).

- [Install](#install)
- [Connect](#connect)
- [What to expect](#what-to-expect)
- [Limitations](#limitations)
- [Indexer limits](#indexer-limits)
- [How it works](#how-it-works)
- [Development](#development)

## Install

The connector is not part of the Hummingbot distribution yet. The setup script clones Hummingbot
2.17.0 next to this directory, builds it and links the connector and the SDK into it:

```bash
connector/scripts/setup_hummingbot.sh
cd hummingbot
.venv/bin/python bin/hummingbot_quickstart.py
```

It needs `git` and [`uv`](https://docs.astral.sh/uv/). To use an existing Hummingbot checkout,
run `connector/scripts/link_hummingbot.sh /path/to/hummingbot` instead.

## Connect

Two connectors are registered: `neutronx_perpetual` (mainnet) and `neutronx_perpetual_testnet`.
In Hummingbot run `connect neutronx_perpetual` and answer the prompts:

| Prompt | Value |
|---|---|
| Account address | the `neutronx1…` address that holds the margin |
| Private key | hex key that signs for the account; an agent key is recommended |
| Agent key id | id of the agent key, or `0` when the account's own key signs |
| Subaccount id | subaccount to trade from, `0` unless you use several |
| Indexer API key | optional, raises the indexer limits; leave blank otherwise |

### Agent keys

An agent key is a separate key the account registers for itself on chain (the `agentkeys`
module). It can place and cancel orders for the account and cannot deposit, withdraw or transfer,
so nothing on the machine that runs the bot can move funds.

Create one at [exchange.neutronx.com/api-keys](https://exchange.neutronx.com/api-keys), then give
Hummingbot the agent key, its id and the account address. On start the connector
asks the chain about the key and refuses to trade if it is missing, expired, belongs to another
public key or lacks permission for the order messages.

## What to expect

- **Order types.** `LIMIT`, `LIMIT_MAKER` (post-only) and `MARKET`. A market order is sent as an
  immediate-or-cancel limit 5% through the mid price.
- **Position mode.** One-way only: the chain nets positions per pair and subaccount.
- **Leverage.** Kept per pair, sent with every order and capped at the market maximum.
- **Collateral and fees.** Margin is USDC. Trading fees follow the account's fee tier on chain.
  Transaction gas is paid in the margin asset.
- **Sizes and prices.** Quantities step by `1e-8`; prices are snapped to the market tick.
- **Order ids.** Client order ids are numeric (the chain's uint32 `client_id`).

## Limitations

- Hedge mode is not supported.
- A resting limit order placed together with other orders reaches the book one block before it
  can match, so an order priced through the book fills a block later than on a centralized venue.
- The chain refuses a reduce-only order when the position it should close is already gone.
  Strategies that send a closing order after the position was closed another way (some DCA
  executors do) will log the refusal.
- The chain may shrink a reduce-only order to the size of the position. Such an order is reported
  as `CANCELED` after its fills, so the unfilled remainder is not counted as traded.
- A fill that lands at the moment Hummingbot shuts down is not recorded in that session.
- Fills arrive from the indexer. If the indexer falls more than 30 blocks behind the chain the
  connector reports itself not connected and stops placing new orders until it catches up;
  cancels still go out.
- Verified with Hummingbot 2.17.0 on the testnet (chain v1.82). The gas rules also cover chain
  v1.81.2.

## Indexer limits

The indexer counts requests per IP address: 120 a minute and 50 subscriptions per socket without
an API key, 600 and 200 with one.

Bots that share an IP share the limit. Give each one a part of it with the Hummingbot setting
`rate_limits_share_pct`, leaving six requests a minute per bot for its network checks: 30 for
each of three bots without an API key.

When the indexer answers 429, the connector pauses its REST requests for the `Retry-After` the
server names, doubling up to 30 s while the limit keeps refusing.

## How it works

### Layout

The package mirrors how it lands in Hummingbot: `neutronx_perpetual/` becomes
`hummingbot/connector/derivative/neutronx_perpetual/`, `tests/` becomes
`test/hummingbot/connector/derivative/neutronx_perpetual/`.

| File | Role |
|---|---|
| `neutronx_perpetual_derivative.py` | Hummingbot contract, delegates to the data sources |
| `neutronx_perpetual_api_order_book_data_source.py` | indexer `orderbook`, `trades`, `ticker` channels |
| `neutronx_perpetual_user_stream_data_source.py` | indexer `orders`, `fills`, `positions` channels |
| `neutronx_perpetual_utils.py` | config maps for mainnet and testnet, default fees |
| `neutronx_perpetual_constants.py`, `neutronx_perpetual_web_utils.py` | names, limits, URLs |
| `data_sources/neutronx_data_source.py` | chain facade: markets, params, orders, balances, positions, signing |
| `data_sources/tx_queue.py` | batches cancels and places into transactions |
| `data_sources/translators.py` | every conversion from SDK and indexer models to Hummingbot types |
| `data_sources/indexer_stream.py` | WebSocket connect, subscribe, heartbeat, error frames |

### Transactions

Orders and cancels requested within 0.2 s are sent together. Cancels go out as one
`MsgBatchCancelOrders` and resting limit orders as one `MsgBatchPlaceOrders` in the same
transaction. Immediate-or-cancel orders travel in a transaction of their own, sent alongside:
the block proposer does not match a transaction that holds a batch message, and an
immediate-or-cancel order it does not match is cancelled with `not_in_batch`.

A transaction with orders must carry a minimum of gas or the proposer leaves it out. The minimum
comes from `neutronx_sdk.tx`, and the queue sizes each batch to fit under the gas ceiling.

When the chain refuses a transaction because an order to cancel is already gone, that cancel is
reported as gone and the rest goes out again as one transaction. Any other refusal of a batch
makes the queue send its orders one by one, so one bad order does not fail the others.

### Order state

Open orders are reconciled account-wide from the chain. A finished order is looked up on chain
first and then in indexer history, read from the newest page back to one minute before the order
was created. Lost orders are checked on chain before a new cancel is sent.

A finished order reaches Hummingbot only after its fills do. While the chain shows more filled
than the indexer has delivered, the order stays open, its fills are fetched at most every 5 s,
and a cancel the chain already accepted is not sent again. After 120 s the final state goes out
with the fills that arrived and an error names the gap.

The final state of the last 10 000 finished orders is kept, so repeated status requests for them
cost no requests.

### Network status

The network check has a rate limit of its own, so it never waits behind other polling. The
connector reports not connected after two failed checks in a row, or while the indexer lags the
chain by more than 30 blocks; a single failed check is logged and tolerated. A 429 on the status
endpoint counts as the indexer being reachable.

Prices and funding info come from one `/markets/tickers` read shared by all pairs, and funding
payments from one `/accounts/{owner}/funding` read per poll. The order book source opens as many
sockets as its subscriptions need, three per pair.

## Development

```bash
connector/scripts/setup_hummingbot.sh
cd hummingbot
.venv/bin/python -m pytest test/hummingbot/connector/derivative/neutronx_perpetual
.venv/bin/flake8 --config .flake8 hummingbot/connector/derivative/neutronx_perpetual
.venv/bin/isort --settings-path pyproject.toml --check-only hummingbot/connector/derivative/neutronx_perpetual
```
