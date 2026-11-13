from __future__ import annotations

from typing import Any

import pytest

from neutronx_sdk import ChainTxError, TxFailure, classify_tx_failure
from neutronx_sdk.exceptions import missing_order_ids, queued_height
from neutronx_sdk.proto import new, pack_any
from neutronx_sdk.tx import (
    MsgKind,
    PrefillCounts,
    ShortTermGasEstimator,
    decode_tx_msg_data,
    is_spot_market,
    msgs_within_floor,
    orders_within_prefill_ceiling,
    parse_batch_cancel_outcome,
    parse_batch_place_outcomes,
    parse_place_order_outcomes,
    parse_short_term_place_outcomes,
    prefill_counts,
    prefill_gas_floor,
    short_term_gas_floor,
    tx_prefill_gas_floor,
)


def test_gas_floor_and_capacity() -> None:
    assert short_term_gas_floor(10, 0) == 960_000
    assert short_term_gas_floor(0, 3) == 180_000
    assert msgs_within_floor(1_000_000, MsgKind.PLACE) == 10
    assert msgs_within_floor(1_000_000, MsgKind.CANCEL) == 23
    assert short_term_gas_floor(0, 23) <= 1_000_000 < short_term_gas_floor(0, 24)
    assert msgs_within_floor(10_000, MsgKind.PLACE) == 1
    with pytest.raises(ValueError, match="negative"):
        short_term_gas_floor(-1, 0)


def test_estimator_packs_by_measured_gas() -> None:
    estimator = ShortTermGasEstimator(window=3)
    assert estimator.capacity(MsgKind.PLACE, 1_000_000) == 10
    estimator.observe(MsgKind.PLACE, 4, 500_001)
    assert estimator.per_msg(MsgKind.PLACE) == 125_001
    assert estimator.capacity(MsgKind.PLACE, 1_000_000) == 7
    estimator.observe_out_of_gas(MsgKind.PLACE, 5, 1_000_000)
    assert estimator.per_msg(MsgKind.PLACE) == 200_001
    assert estimator.capacity(MsgKind.PLACE, 1_000_000) == 4
    for _ in range(3):
        estimator.observe(MsgKind.PLACE, 1, 100_000)
    assert estimator.per_msg(MsgKind.PLACE) == 100_000
    assert estimator.per_msg(MsgKind.CANCEL) == 0
    estimator.observe(MsgKind.CANCEL, 0, 1)
    assert estimator.per_msg(MsgKind.CANCEL) == 0


def _tx_msg_data(*responses: Any) -> bytes:
    data = new("cosmos.base.abci.v1beta1.TxMsgData")
    for response in responses:
        data.msg_responses.append(pack_any(response))
    return data.SerializeToString()


def test_short_term_outcomes_keep_message_order() -> None:
    first = new("neutronx.orderbook.v1.MsgPlaceShortTermOrderResponse", order_id=1, status="open")
    second = new(
        "neutronx.orderbook.v1.MsgPlaceShortTermOrderResponse",
        order_id=2,
        status="filled",
        trades_count=1,
        replaced_order_id=9,
    )
    responses = decode_tx_msg_data(_tx_msg_data(first, second).hex())
    outcomes = parse_short_term_place_outcomes([responses[0], b"\xff\xff", responses[1]])
    assert [o.order_id for o in outcomes] == [1, 0, 2]
    assert outcomes[2].status == "FILLED"
    assert outcomes[2].replaced_order_id == 9


def test_place_and_batch_outcomes() -> None:
    single = new(
        "neutronx.orderbook.v1.MsgPlaceOrderResponse",
        order_id=5,
        status="open",
        filled="1500000000000000000",
    )
    batch = new("neutronx.orderbook.v1.MsgBatchPlaceOrdersResponse", results=[single, single])
    assert parse_place_order_outcomes([single.SerializeToString()])[0].filled == 1.5
    assert [o.order_id for o in parse_batch_place_outcomes([batch.SerializeToString()])] == [5, 5]


def test_batch_cancel_outcome() -> None:
    response = new(
        "neutronx.orderbook.v1.MsgBatchCancelOrdersResponse",
        cancelled_ids=[1, 2],
        gone_ids=[3],
        rejected_ids=[4],
    )
    outcome = parse_batch_cancel_outcome([response.SerializeToString()])
    assert outcome is not None
    assert outcome.settled_ids == (1, 2, 3)
    assert outcome.rejected_ids == (4,)
    assert parse_batch_cancel_outcome([]) is None


@pytest.mark.parametrize("data", [b"", "zz", b"\xff\xff\xff"])
def test_undecodable_msg_data_is_empty(data: bytes | str) -> None:
    assert decode_tx_msg_data(data) == []


@pytest.mark.parametrize(
    ("code", "raw_log", "failure"),
    [
        (19, "tx already exists in cache", TxFailure.DUPLICATE),
        (5, "agent key not found", TxFailure.AGENT_KEY),
        (18, "unordered tx timeout too far", TxFailure.AGENT_KEY),
        (5, "order not found: 42", TxFailure.ORDER_GONE),
        (5, "client_id 7 already in use", TxFailure.CLIENT_ID_CONFLICT),
        (5, "replace requires good_til_block >= 10", TxFailure.REPLACE_GTB_DOWNGRADE),
        (26, "market BTC/USDC is paused", TxFailure.MARKET_PAUSED),
        (41, "gas wanted 100 below the floor 130000", TxFailure.GAS_FLOOR),
        (25, "queued for height 900: per-block rate limit exceeded", TxFailure.SIGNER_BUDGET),
        (11, "out of gas in location", TxFailure.OUT_OF_GAS),
        (28, "collateral insufficient for order", TxFailure.COLLATERAL),
        (32, "account sequence mismatch, expected 5, got 4", TxFailure.SEQUENCE_MISMATCH),
        (40, "good_til_block in the past", TxFailure.STALE_GOOD_TIL_BLOCK),
        (1, "something else", TxFailure.UNKNOWN),
    ],
)
def test_failure_classification(code: int, raw_log: str, failure: TxFailure) -> None:
    assert classify_tx_failure(code, raw_log) is failure


def test_chain_tx_error_properties() -> None:
    err = ChainTxError(25, "queued for height 900: per-block rate limit exceeded", tx_hash="AB")
    assert err.failure is TxFailure.SIGNER_BUDGET
    assert err.queued_height == 900
    assert not err.expected
    assert ChainTxError(19, "").expected
    assert queued_height("nothing") is None


def test_missing_orders_named_by_an_ante_rejection() -> None:
    owner = "neutronx1g0glgcqqku228typcvnl8s3mjgqspnp8c9c446"
    err = ChainTxError(10, f"ante cancel {owner} order 4242: order not found", tx_hash="1A")
    assert err.failure is TxFailure.ORDER_GONE
    assert err.missing_order_ids == (4242,)
    assert missing_order_ids("order 7: order not found; order 9: order not found") == (7, 9)
    assert missing_order_ids("agent key not found") == ()


def test_prefill_floor_follows_the_chain_count() -> None:
    perp = new("neutronx.orderbook.v1.MsgPlaceOrder", pair="BTC/USDC")
    spot = new("neutronx.orderbook.v1.MsgPlaceOrder", pair="SPOT:ATOM/USDC")
    batch = new("neutronx.orderbook.v1.MsgBatchPlaceOrders", orders=[perp, perp, spot])
    by_ids = new("neutronx.orderbook.v1.MsgBatchCancelOrders", order_ids=[1, 2], pair="BTC/USDC")
    by_id = new("neutronx.orderbook.v1.MsgCancelOrder", order_id=3, pair="BTC/USDC")
    replace = new("neutronx.orderbook.v1.MsgReplaceOrder", pair="BTC/USDC")
    short_term = new("neutronx.orderbook.v1.MsgCancelShortTermOrder", pair="BTC/USDC")
    spot_short_term = new("neutronx.orderbook.v1.MsgCancelShortTermOrder", pair="SPOT:ATOM/USDC")
    counts = prefill_counts([batch, by_ids, by_id, replace, short_term, spot_short_term])
    assert counts == PrefillCounts(orders=4, cancels=6, spot_orders=1, spot_cancels=4)
    assert prefill_gas_floor(counts) == 60_000 + 4 * 90_000 + 6 * 40_000 + 30_000 + 4 * 15_000
    assert prefill_counts([new("neutronx.perps.v1.MsgClosePosition")]) == PrefillCounts()
    assert is_spot_market("SPOT:ATOM/USDC")
    assert not is_spot_market("BTC/USDC")
    with pytest.raises(ValueError, match="negative"):
        prefill_gas_floor(PrefillCounts(orders=-1))


def test_regular_tx_floor_charges_cancels_by_id_and_skips_cancel_only_txs() -> None:
    ioc = new("neutronx.orderbook.v1.MsgPlaceOrder", pair="ETH/USDC")
    cancels = new("neutronx.orderbook.v1.MsgBatchCancelOrders", order_ids=[1, 2])
    assert tx_prefill_gas_floor([cancels, ioc]) == 260_000
    assert tx_prefill_gas_floor([ioc]) == 150_000
    assert tx_prefill_gas_floor([cancels]) == 0


def test_orders_within_prefill_ceiling() -> None:
    cancels = new("neutronx.orderbook.v1.MsgBatchCancelOrders", order_ids=list(range(1, 51)))
    assert orders_within_prefill_ceiling(6_000_000) == 66
    assert orders_within_prefill_ceiling(6_000_000, [cancels]) == 35
    fits = PrefillCounts(orders=35, cancels=50, spot_cancels=50)
    over = PrefillCounts(orders=36, cancels=50, spot_cancels=50)
    assert prefill_gas_floor(fits) <= 6_000_000 < prefill_gas_floor(over)
    assert orders_within_prefill_ceiling(100_000) == 0
