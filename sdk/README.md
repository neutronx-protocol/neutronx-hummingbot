# neutronx-sdk

Python SDK for the NeutronX perpetuals chain: keys and agent keys, transaction building and
signing, short-term orders, gRPC queries and broadcasting.

## Install

```bash
pip install neutronx-sdk   # or: uv add neutronx-sdk
```

Python 3.10+.

## Quick start

The example places one short-term order on the testnet, signed with an agent key. An agent key
trades for an account and cannot withdraw or transfer its funds, so it is the key to give a bot.
Agent keys are created at [exchange.neutronx.com/api-keys](https://exchange.neutronx.com/api-keys).

```python
import asyncio
import os
from decimal import Decimal

from neutronx_sdk import TESTNET, AccountSequence, NodeClient, OrderRequest, Side, TxBuilder, Wallet
from neutronx_sdk.orders import good_til_block, place_short_term_order_msg


async def main() -> None:
    wallet = Wallet.agent(
        os.environ["NEUTRONX_AGENT_KEY"],
        account=os.environ["NEUTRONX_ACCOUNT"],
        key_id=int(os.environ["NEUTRONX_AGENT_KEY_ID"]),
    )
    async with NodeClient(TESTNET) as client:
        status = await client.node.status()
        sequence = AccountSequence(client.auth, wallet.address, agent=wallet.is_agent)
        slot = await sequence.current()
        request = OrderRequest(
            pair="BTC/USDC",
            side=Side.BUY,
            price=Decimal("65000"),
            quantity=Decimal("0.001"),
            leverage=Decimal("3"),
            client_id=1,
        )
        msg = place_short_term_order_msg(wallet.address, request, good_til_block(status.height))
        tx = TxBuilder(wallet, TESTNET.chain_id).short_term(
            [msg], account_number=slot.account_number, sequence=slot.sequence
        )
        result = await client.tx.broadcast(tx)
        print(result.tx_hash, result.height)


asyncio.run(main())
```

To sign with the account's own key instead, use `Wallet.from_hex(...)` or
`Wallet.from_mnemonic(...)`. `MAINNET` is the other built-in network; `Network.with_endpoint`
points either one at a node of your own.

## What is in the package

| Module | Purpose |
|---|---|
| `neutronx_sdk.wallet`, `neutronx_sdk.crypto` | keys, addresses, account and agent wallets |
| `neutronx_sdk.orders` | order requests and the chain messages built from them |
| `neutronx_sdk.tx` | signing, fees, gas floors, decoding of transaction responses |
| `neutronx_sdk.node` | gRPC queries, broadcasting, account sequence, `TxSender` |
| `neutronx_sdk.indexer` | models and paths of the public indexer API |
| `neutronx_sdk.network` | `MAINNET` and `TESTNET` endpoints |

## Chain rules the SDK follows

- Short-term orders live at most 20 blocks past the height they are signed at. A short-term tx
  pays no fee and does not advance the account sequence: sign it with `AccountSequence.current()`,
  sign regular txs with `AccountSequence.reserve()`.
- A tx that places orders must carry a minimum of gas, and a short-term tx at most the chain's
  `short_term_max_gas_wanted`. On chain v1.82 the minimum is 60 000, plus 90 000 per order and
  40 000 per cancel, and a cancel by order id costs 15 000 more. Chain v1.81.2 starts from 40 000
  and has no extra for cancels by id, so gas sized for the newer rule is accepted by both.
  `neutronx_sdk.tx.tx_prefill_gas_floor` computes the minimum for a list of messages.
- An agent key signs for an account it cannot move funds from. Its txs carry the key id in a
  non-critical extension and sequence 0; its regular txs are unordered, with a timeout from
  `UnorderedNonce`.
- Limit prices sit on the market's tick grid; `snap_to_tick` rounds bids down and asks up.
- `UserOrders` may not list every short-term order; read the book with `OrderBook`.

## Protobuf isolation

Chain and Cosmos SDK descriptors load into a private descriptor pool, never the global one, so
the SDK runs next to other Cosmos SDKs in one process. `neutronx_sdk.proto.descriptors_ref()`
names the chain release they were built from.

The descriptors ship with the package, so using the SDK needs nothing else. They hold only the
messages and query methods the SDK uses; the list is in `scripts/trim_descriptors.py`.
`scripts/gen_descriptors.sh` is the maintainers' tool that rebuilds them for a new chain release.
It reads the chain's proto files, which are not public yet, from the checkout named in
`CHAIN_REPO` at the tag named in `CHAIN_REF`:

```bash
CHAIN_REPO=/path/to/chain CHAIN_REF=v1.82.0 scripts/gen_descriptors.sh
```

## Development

```bash
git clone https://github.com/neutronx-protocol/neutronx-hummingbot.git
cd neutronx-hummingbot/sdk
uv sync
uv run pytest
uv run pytest -m live        # reads the public testnet; NEUTRONX_LIVE_NETWORK=mainnet for mainnet
uv run ruff check
uv run ruff format --check
uv run pyright
```
