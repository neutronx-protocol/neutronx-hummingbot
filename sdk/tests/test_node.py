from __future__ import annotations

from collections.abc import AsyncIterator

import grpc
import pytest

from neutronx_sdk import (
    TESTNET,
    AccountSequence,
    ChainTxError,
    NodeClient,
    SignedTx,
    TxConfirmationTimeoutError,
    TxFailure,
)
from tests.fakes import BUDGET_LOG, FakeChain, serve

ACCOUNT = "neutronx1account"


@pytest.fixture
def chain() -> FakeChain:
    return FakeChain()


@pytest.fixture
async def client(chain: FakeChain) -> AsyncIterator[NodeClient]:
    async with serve(chain) as node:
        yield node


async def test_markets_skip_unnamed_entries(client: NodeClient) -> None:
    markets = await client.perps.markets()
    assert [m.pair for m in markets] == ["BTC/USDC"]
    assert str(markets[0].tick_size) == "0.1"


async def test_all_user_orders_walks_every_page(client: NodeClient, chain: FakeChain) -> None:
    orders = await client.orderbook.all_user_orders(
        ACCOUNT, status_filter="open", include="regular"
    )
    assert [o.order_id for o in orders] == [1, 2, 3]
    pages = chain.calls("UserOrders")
    assert [p.page for p in pages] == [1, 2, 3]
    assert pages[0].status_filter == "open"
    assert pages[0].include == "regular"


async def test_missing_agent_key_reads_as_none(client: NodeClient) -> None:
    assert await client.agentkeys.agent_key(ACCOUNT, 5) is None


async def test_sequence_reserves_and_refreshes(client: NodeClient, chain: FakeChain) -> None:
    sequence = AccountSequence(client.auth, ACCOUNT)
    first = await sequence.reserve()
    second = await sequence.reserve()
    current = await sequence.current()
    assert (first.account_number, first.sequence) == (12, 7)
    assert second.sequence == 8
    assert current.sequence == 9
    chain.sequence = 20
    sequence.mark_stale()
    assert (await sequence.reserve()).sequence == 20


async def test_agent_sequence_is_always_zero(client: NodeClient) -> None:
    sequence = AccountSequence(client.auth, ACCOUNT, agent=True)
    assert (await sequence.reserve()).sequence == 0
    assert (await sequence.current()).sequence == 0
    assert sequence.sequence == 7


async def test_broadcast_waits_for_commit(client: NodeClient, chain: FakeChain) -> None:
    result = await client.tx.broadcast(SignedTx(b"tx"), poll_interval=0.01)
    assert result.height == chain.height + 1
    assert result.gas_used == 130_000
    assert result.events[0].attributes == {"order_id": "55"}
    assert len(result.msg_responses) == 1
    assert [name for name, _ in chain.requests] == ["BroadcastTx", "GetTx", "GetTx"]


async def test_check_tx_refusal_raises(client: NodeClient, chain: FakeChain) -> None:
    chain.check_tx_results.append((25, BUDGET_LOG))
    with pytest.raises(ChainTxError) as raised:
        await client.tx.broadcast(SignedTx(b"tx"), poll_interval=0.01)
    assert raised.value.check_tx
    assert raised.value.failure is TxFailure.SIGNER_BUDGET
    assert raised.value.queued_height == 900


async def test_deliver_failure_raises(client: NodeClient, chain: FakeChain) -> None:
    chain.deliver_code = 11
    with pytest.raises(ChainTxError) as raised:
        await client.tx.broadcast(SignedTx(b"tx"), poll_interval=0.01)
    assert not raised.value.check_tx
    assert raised.value.height == chain.height + 1
    assert raised.value.failure is TxFailure.OUT_OF_GAS


async def test_uncommitted_tx_times_out(client: NodeClient, chain: FakeChain) -> None:
    chain.pending_polls = 1_000
    with pytest.raises(TxConfirmationTimeoutError) as raised:
        await client.tx.broadcast(SignedTx(b"tx"), confirm_timeout=0.1, poll_interval=0.02)
    assert raised.value.tx_hash == "ABCD"


async def test_unavailable_node_surfaces_grpc_error() -> None:
    node = NodeClient(TESTNET.with_endpoint("127.0.0.1:1", secure=False), timeout=0.5)
    try:
        with pytest.raises(grpc.aio.AioRpcError):
            await node.perps.markets()
    finally:
        await node.close()
