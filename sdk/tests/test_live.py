from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from neutronx_sdk import MAINNET, TESTNET, Network, NodeClient

pytestmark = pytest.mark.live

NETWORKS = {"testnet": TESTNET, "mainnet": MAINNET}


def _network() -> Network:
    return NETWORKS[os.environ.get("NEUTRONX_LIVE_NETWORK", "testnet")]


@pytest.fixture
async def client() -> AsyncIterator[NodeClient]:
    network = _network()
    async with NodeClient(network) as node:
        yield node


async def test_markets_and_book(client: NodeClient) -> None:
    markets = await client.perps.markets()
    assert markets
    active = [m for m in markets if m.is_active]
    assert active
    book = await client.orderbook.order_book(active[0].pair, depth=5)
    assert book.pair == active[0].pair
    assert book.height > 0


async def test_params_match_network(client: NodeClient) -> None:
    perps = await client.perps.params()
    orderbook = await client.orderbook.params()
    assert perps.margin_denom.startswith("ibc/")
    assert orderbook.short_term_order_ttl_blocks > 0
    assert orderbook.min_order_notional > 0


async def test_status_and_oracle(client: NodeClient) -> None:
    status = await client.node.status()
    assert status.height > 0
    prices = await client.oracle.prices()
    assert prices
    assert all(p.price > 0 for p in prices)
