from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from neutronx_sdk import (
    ChainClock,
    ChainTxError,
    FeePolicy,
    NodeClient,
    OrderRequest,
    Side,
    TimeInForce,
    TxFailure,
    TxSender,
    UnorderedNonce,
    Wallet,
)
from neutronx_sdk.models import OrderbookParams
from neutronx_sdk.orders import (
    batch_cancel_orders_msg,
    cancel_short_term_order_msg,
    place_order_msg,
)
from neutronx_sdk.proto import parse
from tests.fakes import BUDGET_LOG, MISMATCH_LOG, FakeChain, serve

FEE = FeePolicy("ibc/USDC", gas_price=Decimal("0.001"))


@pytest.fixture
def chain() -> FakeChain:
    return FakeChain()


@pytest.fixture
async def client(chain: FakeChain) -> AsyncIterator[NodeClient]:
    async with serve(chain) as node:
        yield node


@pytest.fixture
def own(golden: dict[str, Any]) -> Wallet:
    return Wallet.from_hex(golden["key_hex"])


@pytest.fixture
def agent(golden: dict[str, Any], own: Wallet) -> Wallet:
    return Wallet.agent(golden["agent_key_hex"], account=own.address, key_id=5)


def _signed(chain: FakeChain, index: int = -1) -> tuple[Any, Any]:
    raw = parse("cosmos.tx.v1beta1.TxRaw", chain.calls("BroadcastTx")[index].tx_bytes)
    return (
        parse("cosmos.tx.v1beta1.TxBody", raw.body_bytes),
        parse("cosmos.tx.v1beta1.AuthInfo", raw.auth_info_bytes),
    )


async def test_regular_txs_reserve_consecutive_sequences(
    client: NodeClient, chain: FakeChain, own: Wallet
) -> None:
    chain.pending_polls = 0
    sender = TxSender(client, own, fee=FEE, poll_interval=0.01)
    msg = batch_cancel_orders_msg(own.address, [1])
    first = await sender.send([msg], gas_limit=200_000)
    await sender.send([msg], gas_limit=200_000)
    assert first.height == chain.height + 1
    assert sender.committed_height == chain.height + 1
    sequences = [_signed(chain, i)[1].signer_infos[0].sequence for i in (0, 1)]
    assert sequences == [7, 8]
    fee = _signed(chain)[1].fee
    assert (fee.amount[0].denom, fee.amount[0].amount, fee.gas_limit) == (
        "ibc/USDC",
        "200",
        200_000,
    )


async def test_sequence_mismatch_refreshes_and_retries(
    client: NodeClient, chain: FakeChain, own: Wallet
) -> None:
    chain.pending_polls = 0
    chain.check_tx_results.append((32, MISMATCH_LOG))
    sender = TxSender(client, own, fee=FEE, poll_interval=0.01)
    await sender.send([batch_cancel_orders_msg(own.address, [1])], gas_limit=200_000)
    assert len(chain.calls("BroadcastTx")) == 2
    assert len(chain.calls("Account")) == 2


async def test_other_check_tx_refusals_raise(
    client: NodeClient, chain: FakeChain, own: Wallet
) -> None:
    chain.check_tx_results.append((13, "insufficient fee"))
    sender = TxSender(client, own, fee=FEE, poll_interval=0.01)
    with pytest.raises(ChainTxError) as raised:
        await sender.send([batch_cancel_orders_msg(own.address, [1])], gas_limit=200_000)
    assert raised.value.check_tx
    assert sender.sequence.sequence == 8
    assert len(chain.calls("BroadcastTx")) == 1


async def test_agent_regular_tx_is_unordered_from_chain_time(
    client: NodeClient, chain: FakeChain, own: Wallet, agent: Wallet
) -> None:
    chain.pending_polls = 0
    sender = TxSender(client, agent, fee=FEE, nonce=UnorderedNonce(slot=7), poll_interval=0.01)
    await sender.send([batch_cancel_orders_msg(own.address, [1])], gas_limit=200_000)
    body, auth = _signed(chain)
    assert body.unordered
    assert auth.signer_infos[0].sequence == 0
    timeout_ns = body.timeout_timestamp.seconds * 1_000_000_000 + body.timeout_timestamp.nanos
    assert timeout_ns % 1000 == 7
    assert 50 <= body.timeout_timestamp.seconds - chain.block_seconds <= 70


async def test_short_term_waits_out_signer_budget(
    client: NodeClient, chain: FakeChain, own: Wallet
) -> None:
    chain.pending_polls = 0
    chain.height = 901
    chain.check_tx_results.append((25, BUDGET_LOG))
    sender = TxSender(client, own, fee=FEE, poll_interval=0.01)
    result = await sender.send_short_term(
        [cancel_short_term_order_msg(own.address, 1, "BTC/USDC", 920)]
    )
    assert result.height == 902
    assert len(chain.calls("BroadcastTx")) == 2
    assert chain.calls("Status")
    _body, auth = _signed(chain)
    assert auth.fee.gas_limit == 1_000_000
    assert not auth.fee.amount


async def test_short_term_budget_retries_are_bounded(
    client: NodeClient, chain: FakeChain, own: Wallet
) -> None:
    chain.height = 901
    chain.check_tx_results.extend([(25, BUDGET_LOG)] * 5)
    sender = TxSender(client, own, fee=FEE, poll_interval=0.01)
    with pytest.raises(ChainTxError) as raised:
        await sender.send_short_term([cancel_short_term_order_msg(own.address, 1, "BTC/USDC", 920)])
    assert raised.value.failure is TxFailure.SIGNER_BUDGET
    assert len(chain.calls("BroadcastTx")) == 5


async def test_short_term_sequence_mismatch_retries(
    client: NodeClient, chain: FakeChain, own: Wallet
) -> None:
    chain.pending_polls = 0
    chain.check_tx_results.append((32, MISMATCH_LOG))
    sender = TxSender(client, own, fee=FEE, poll_interval=0.01)
    await sender.send_short_term([cancel_short_term_order_msg(own.address, 1, "BTC/USDC", 920)])
    assert len(chain.calls("BroadcastTx")) == 2


async def test_estimate_gas_adds_headroom_under_ceiling(
    client: NodeClient, chain: FakeChain, own: Wallet
) -> None:
    sender = TxSender(client, own, fee=FEE)
    msg = batch_cancel_orders_msg(own.address, [1])
    assert await sender.estimate_gas([msg], ceiling=1_000_000) == 130_000
    chain.simulate_gas = 900_000
    assert await sender.estimate_gas([msg], ceiling=1_000_000) == 1_000_000
    assert sender.sequence.sequence == 7


async def test_estimate_gas_meets_the_batch_prefill_floor(
    client: NodeClient, chain: FakeChain, own: Wallet
) -> None:
    sender = TxSender(client, own, fee=FEE)
    chain.simulate_gas = 50_000
    order = place_order_msg(own.address, _ioc_request())
    cancel = batch_cancel_orders_msg(own.address, [1, 2])
    assert await sender.estimate_gas([order], ceiling=10_000_000) == 150_000
    assert await sender.estimate_gas([cancel, order], ceiling=10_000_000) == 260_000
    assert await sender.estimate_gas([cancel, order], ceiling=200_000) == 200_000


async def test_chain_clock_follows_block_time(client: NodeClient, chain: FakeChain) -> None:
    local = [1_000 * 1_000_000_000]
    clock = ChainClock(client.node, time_ns=lambda: local[0])
    now = await clock.now_ns()
    assert now == chain.block_seconds * 1_000_000_000
    local[0] += 2_000_000_000
    assert await clock.now_ns() == (chain.block_seconds + 2) * 1_000_000_000
    assert await clock.height() == chain.height
    assert clock.status is not None
    assert clock.status.block_time == datetime.fromtimestamp(chain.block_seconds, tz=timezone.utc)


def test_fee_policy_for_trading_pays_margin_denom() -> None:
    params = OrderbookParams(
        maker_fee_rate=Decimal("0.0002"),
        taker_fee_rate=Decimal("0.0005"),
        min_order_notional=10,
        max_open_orders_per_user=500,
        rate_limit_per_block=30,
        short_term_enabled=True,
        short_term_order_ttl_blocks=20,
        short_term_per_block_limit=500,
        short_term_max_gas_wanted=1_000_000,
        trading_halted=False,
        min_gas_price=Decimal("0.005"),
        max_gas_wanted=0,
    )
    policy = FeePolicy.for_trading(params, "ibc/MARGIN")
    assert policy.denom == "ibc/MARGIN"
    assert policy.gas_price == Decimal("0.005")
    zero = FeePolicy.for_trading(replace(params, min_gas_price=Decimal(0)), "d")
    assert zero.gas_price == Decimal("0.001")


def _ioc_request() -> OrderRequest:
    return OrderRequest(
        pair="BTC/USDC",
        side=Side.BUY,
        price=Decimal(70000),
        quantity=Decimal("0.001"),
        leverage=Decimal(3),
        time_in_force=TimeInForce.IOC,
        client_id=5,
    )
