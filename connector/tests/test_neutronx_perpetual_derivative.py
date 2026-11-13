import asyncio
import math
import re
from datetime import datetime, timezone
from decimal import Decimal
from test.hummingbot.connector.derivative.neutronx_perpetual.fixtures import (
    ACCOUNT,
    BLOCK_TIME,
    INDEXER_URL,
    NETWORK,
    FakeDataSource,
    chain_order,
    chain_position,
    fill_json,
    frame,
    order_json,
)
from test.isolated_asyncio_wrapper_test_case import IsolatedAsyncioWrapperTestCase
from typing import Any, Dict
from unittest.mock import AsyncMock, PropertyMock, patch

from aioresponses import aioresponses
from neutronx_sdk import OrderType as ChainOrderType, Side, TimeInForce
from neutronx_sdk.indexer import FillV1, StreamFrame

from hummingbot.connector.derivative.neutronx_perpetual import neutronx_perpetual_constants as CONSTANTS
from hummingbot.connector.derivative.neutronx_perpetual.data_sources.tx_queue import CancelOutcome, PlacedOrder
from hummingbot.connector.derivative.neutronx_perpetual.neutronx_perpetual_derivative import NeutronxPerpetualDerivative
from hummingbot.core.data_type.common import OrderType, PositionAction, PositionMode, PositionSide, TradeType
from hummingbot.core.data_type.in_flight_order import OrderState
from hummingbot.core.network_iterator import NetworkStatus

PAIR = "BTC-USDC"
FILLS_URL = re.compile(rf"^{INDEXER_URL}/accounts/{ACCOUNT}/fills.*")
SAFE_ENSURE_FUTURE = "hummingbot.connector.derivative.neutronx_perpetual.neutronx_perpetual_derivative.safe_ensure_future"


class NeutronxPerpetualDerivativeTests(IsolatedAsyncioWrapperTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.data_source = FakeDataSource()
        self.connector = NeutronxPerpetualDerivative(
            neutronx_perpetual_account_address=ACCOUNT,
            trading_pairs=[PAIR],
            trading_required=True,
            network=NETWORK,
            data_source=self.data_source,
        )
        await self.connector._update_trading_rules()

    @staticmethod
    async def _settle():
        for _ in range(5):
            await asyncio.sleep(0)

    @staticmethod
    def _requests(mock: aioresponses) -> int:
        return sum(len(calls) for calls in mock.requests.values())

    def _track(self, client_id: str, exchange_id: str = "555", amount: str = "0.01", order_type=OrderType.LIMIT):
        self.connector.start_tracking_order(
            order_id=client_id,
            exchange_order_id=exchange_id,
            trading_pair=PAIR,
            trade_type=TradeType.BUY,
            price=Decimal(65000),
            amount=Decimal(amount),
            order_type=order_type,
            position_action=PositionAction.OPEN,
            leverage=Decimal(3),
        )
        return self.connector.in_flight_orders[client_id]

    async def test_trading_rules_and_symbols_cover_active_markets(self):
        self.assertEqual({"BTC-USDC", "ETH-USDC"}, set(self.connector.trading_rules))
        self.assertEqual("BTC/USDC", await self.connector.exchange_symbol_associated_to_pair(PAIR))
        self.assertEqual(PAIR, self.connector.trading_pair_for_indexer("BTCUSDC"))
        self.assertEqual("USDC", self.connector.get_buy_collateral_token(PAIR))
        self.assertEqual(Decimal(10), self.connector.trading_rules[PAIR].min_notional_size)
        self.assertEqual(Decimal("0.0045"), self.connector.quantize_order_amount(PAIR, Decimal("0.0045")))

    async def test_trading_starts_after_the_base_restart(self):
        def discard(coroutine):
            coroutine.close()

        with patch.object(self.connector.order_book_tracker, "start"), \
                patch.object(self.connector._perpetual_trading, "start"), \
                patch("hummingbot.connector.exchange_py_base.safe_ensure_future", side_effect=discard), \
                patch("hummingbot.connector.perpetual_derivative_py_base.safe_ensure_future", side_effect=discard), \
                patch.object(self.connector, "_create_user_stream_tracker_task", return_value=None):
            await self.connector.start_network()
            self.assertTrue(self.data_source.started)
            await self.connector.stop_network()
        self.assertFalse(self.data_source.started)

    async def test_network_outage_keeps_trading_until_the_clock_stops(self):
        def discard(coroutine):
            coroutine.close()

        status = PropertyMock(return_value=NetworkStatus.NOT_CONNECTED)
        with patch.object(self.connector.order_book_tracker, "start"), \
                patch.object(self.connector._perpetual_trading, "start"), \
                patch("hummingbot.connector.exchange_py_base.safe_ensure_future", side_effect=discard), \
                patch("hummingbot.connector.perpetual_derivative_py_base.safe_ensure_future", side_effect=discard), \
                patch.object(self.connector, "_create_user_stream_tracker_task", return_value=None), \
                patch.object(NeutronxPerpetualDerivative, "network_status", new_callable=lambda: status):
            await self.connector.start_network()
            await self.connector.stop_network()
            self.assertTrue(self.data_source.started)
            status.return_value = NetworkStatus.CONNECTED
            await self.connector.start_network()
            self.assertEqual(1, self.data_source.start_calls)
            status.return_value = NetworkStatus.STOPPED
            await self.connector.stop_network()
        self.assertFalse(self.data_source.started)

    def test_order_request_shapes(self):
        self.connector._perpetual_trading.set_leverage(PAIR, 50)
        limit = self.connector._order_request(
            "101", PAIR, Decimal("0.01"), TradeType.BUY, OrderType.LIMIT, Decimal("65000.7"), PositionAction.OPEN
        )
        self.assertEqual((Side.BUY, Decimal("65000.5"), TimeInForce.GTC), (limit.side, limit.price, limit.time_in_force))
        self.assertEqual((Decimal(10), False, False, 101), (limit.leverage, limit.post_only, limit.reduce_only, limit.client_id))
        maker = self.connector._order_request(
            "102", PAIR, Decimal("0.01"), TradeType.SELL, OrderType.LIMIT_MAKER, Decimal("65000.2"), PositionAction.CLOSE
        )
        self.assertEqual((Decimal("65000.5"), True, True), (maker.price, maker.post_only, maker.reduce_only))
        with patch.object(self.connector, "get_mid_price", return_value=Decimal(100)):
            market = self.connector._order_request(
                "103", PAIR, Decimal("0.01"), TradeType.BUY, OrderType.MARKET, Decimal("NaN"), PositionAction.OPEN
            )
        self.assertEqual((ChainOrderType.LIMIT, TimeInForce.IOC, Decimal(105)), (market.order_type, market.time_in_force, market.price))
        sell = self.connector._market_order_price(PAIR, TradeType.SELL, Decimal(200))
        self.assertEqual(Decimal(190), sell)
        with patch.object(self.connector, "get_mid_price", return_value=Decimal("NaN")):
            with self.assertRaises(ValueError):
                self.connector._market_order_price(PAIR, TradeType.BUY, Decimal("NaN"))

    async def test_create_order_tracks_the_chain_order_id(self):
        order_id = self.connector.buy(PAIR, Decimal("0.01"), OrderType.LIMIT, Decimal(65000))
        await self.connector._create_order(
            trade_type=TradeType.BUY,
            order_id="900",
            trading_pair=PAIR,
            amount=Decimal("0.01"),
            order_type=OrderType.LIMIT,
            price=Decimal(65000),
            position_action=PositionAction.OPEN,
        )
        await self._settle()
        self.assertTrue(order_id.isdigit())
        order = self.connector.in_flight_orders["900"]
        self.assertEqual(("555", OrderState.OPEN), (order.exchange_order_id, order.current_state))
        self.assertEqual({int(order_id), 900}, {request.client_id for request in self.data_source.placed})

    async def test_born_cancelled_post_only_order_is_cancelled(self):
        self.data_source.place_result = PlacedOrder(order_id=556, status="CANCELLED", filled=Decimal(0))
        self.data_source.client_ids.seed([901])
        await self.connector._create_order(
            trade_type=TradeType.SELL,
            order_id="901",
            trading_pair=PAIR,
            amount=Decimal("0.01"),
            order_type=OrderType.LIMIT_MAKER,
            price=Decimal(65000),
            position_action=PositionAction.OPEN,
        )
        await self._settle()
        self.assertNotIn("901", self.connector.in_flight_orders)
        self.assertNotIn(901, self.data_source.client_ids)

    async def test_cancel_outcomes(self):
        self._track("101", "555")
        self.data_source.orders[555] = chain_order(555, "CANCELLED")
        self.assertTrue(await self.connector._place_cancel("101", self.connector.in_flight_orders["101"]))
        self.assertEqual([555], self.data_source.cancelled)
        self.assertNotIn("101", self.connector._settling)
        self.data_source.cancel_outcome = CancelOutcome.REJECTED
        with self.assertRaises(IOError) as raised:
            await self.connector._place_cancel("101", self.connector.in_flight_orders["101"])
        self.assertTrue(self.connector._is_order_not_found_during_cancelation_error(raised.exception))
        self.data_source.cancel_outcome = CancelOutcome.GONE
        self.data_source.orders[555] = chain_order(555, "FILLED")
        with patch("hummingbot.connector.derivative.neutronx_perpetual.neutronx_perpetual_derivative.safe_ensure_future") as future:
            self.assertFalse(await self.connector._place_cancel("101", self.connector.in_flight_orders["101"]))
        future.assert_called_once()
        future.call_args.args[0].close()

    async def test_outage_refuses_new_orders_and_keeps_cancelling(self):
        order = self._track("101", "555")
        self.data_source.orders[555] = chain_order(555, "CANCELLED")
        with patch.object(NeutronxPerpetualDerivative, "network_status", new_callable=PropertyMock,
                          return_value=NetworkStatus.NOT_CONNECTED):
            with self.assertRaises(IOError):
                await self.connector._place_order_and_process_update(order)
            with self.assertRaises(IOError):
                await self.connector._place_order("102", PAIR, Decimal("0.01"), TradeType.BUY, OrderType.LIMIT, Decimal(65000))
            self.assertTrue(await self.connector._place_cancel("101", order))
        self.assertEqual([], self.data_source.placed)
        self.assertEqual([555], self.data_source.cancelled)

    async def test_status_reconciliation_uses_chain_then_indexer(self):
        open_order = self._track("101", "555")
        open_order.creation_timestamp = 0
        gone = self._track("102", "556")
        gone.creation_timestamp = 0
        self.data_source.open_orders_result = (chain_order(555, "PARTIALLY_FILLED"),)
        self.data_source.orders[556] = chain_order(556, "CANCELLED")
        with patch.object(NeutronxPerpetualDerivative, "current_timestamp", 1000.0):
            await self.connector._update_order_status()
            await self._settle()
        self.assertEqual(OrderState.PARTIALLY_FILLED, open_order.current_state)
        self.assertNotIn("102", self.connector.in_flight_orders)

    async def test_status_falls_back_to_indexer_history(self):
        order = self._track("101", "557")
        with aioresponses() as mock:
            mock.get(
                re.compile(rf"^{INDEXER_URL}/accounts/{ACCOUNT}/orders.*"),
                payload={"items": [order_json(557, "FILLED", "0.01")], "next_cursor": None},
            )
            mock.get(
                re.compile(rf"^{INDEXER_URL}/accounts/{ACCOUNT}/fills.*"),
                payload={"items": [fill_json("301:1", 557)], "next_cursor": None},
            )
            update = await self.connector._request_order_status(order)
        self.assertIs(OrderState.FILLED, update.new_state)
        self.assertEqual(Decimal("0.01"), order.executed_amount_base)
        unknown = self._track("102", "558")
        with aioresponses() as mock:
            mock.get(re.compile(rf"^{INDEXER_URL}/accounts/.*"), payload={"items": [], "next_cursor": None})
            with self.assertRaises(IOError) as raised:
                await self.connector._request_order_status(unknown)
        self.assertTrue(self.connector._is_order_not_found_during_status_update_error(raised.exception))

    async def test_finished_order_waits_for_its_fills(self):
        order = self._track("101", "555", amount="0.02")
        self.data_source.orders[555] = chain_order(555, "FILLED", quantity="0.02", filled="0.02")
        with aioresponses() as mock, patch.object(self.connector, "_time", return_value=1000.0) as clock:
            mock.get(FILLS_URL, payload={"items": [fill_json("401:1", 555)], "next_cursor": None})
            waiting = await self.connector._request_order_status(order)
            self.assertIs(OrderState.PARTIALLY_FILLED, waiting.new_state)
            self.assertIn("101", self.connector._settling)
            await self.connector._request_order_status(order)
            self.assertEqual(1, self._requests(mock))
            clock.return_value = 1000.0 + CONSTANTS.FILL_BACKFILL_INTERVAL
            mock.get(FILLS_URL, payload={"items": [fill_json("401:2", 555), fill_json("401:1", 555)], "next_cursor": None})
            done = await self.connector._request_order_status(order)
        self.assertIs(OrderState.FILLED, done.new_state)
        self.assertEqual(Decimal("0.02"), order.executed_amount_base)
        self.assertNotIn("101", self.connector._settling)
        lookups = len(self.data_source.order_lookups)
        self.assertIs(done, await self.connector._request_order_status(order))
        self.assertEqual(lookups, len(self.data_source.order_lookups))

    async def test_fills_that_never_come_release_the_order_after_the_timeout(self):
        order = self._track("101", "555", amount="0.02")
        self.data_source.orders[555] = chain_order(555, "FILLED", quantity="0.02", filled="0.02")
        with aioresponses() as mock, patch.object(self.connector, "_time", return_value=1000.0) as clock:
            mock.get(FILLS_URL, payload={"items": [], "next_cursor": None}, repeat=True)
            self.assertIs(OrderState.OPEN, (await self.connector._request_order_status(order)).new_state)
            clock.return_value = 1000.0 + CONSTANTS.FILL_SETTLE_TIMEOUT
            released = await self.connector._request_order_status(order)
        self.assertIs(OrderState.FILLED, released.new_state)
        self.assertNotIn("101", self.connector._settling)

    async def test_reduce_only_order_shrunk_by_the_chain_ends_cancelled_with_its_fills(self):
        order = self._track("101", "555", amount="0.02")
        self.data_source.orders[555] = chain_order(555, "FILLED", quantity="0.01", filled="0.01")
        with aioresponses() as mock:
            mock.get(FILLS_URL, payload={"items": [fill_json("402:1", 555)], "next_cursor": None})
            update = await self.connector._request_order_status(order)
        self.assertIs(OrderState.CANCELED, update.new_state)
        self.assertEqual(Decimal("0.01"), order.executed_amount_base)

    async def test_cancel_reports_the_fills_made_before_it(self):
        order = self._track("101", "555", amount="0.02")
        self.data_source.orders[555] = chain_order(555, "CANCELLED", quantity="0.02", filled="0.01")
        with aioresponses() as mock:
            mock.get(FILLS_URL, payload={"items": [fill_json("403:1", 555)], "next_cursor": None})
            self.assertTrue(await self.connector._place_cancel("101", order))
        self.assertEqual(Decimal("0.01"), order.executed_amount_base)
        self.assertNotIn("101", self.connector._settling)

    async def test_cancel_with_late_fills_waits_and_sends_no_second_tx(self):
        order = self._track("101", "555", amount="0.02")
        self.data_source.orders[555] = chain_order(555, "CANCELLED", quantity="0.02", filled="0.01")
        with aioresponses() as mock:
            mock.get(FILLS_URL, payload={"items": [], "next_cursor": None})
            self.assertFalse(await self.connector._place_cancel("101", order))
        self.assertIn("101", self.connector._settling)
        with patch(SAFE_ENSURE_FUTURE) as future:
            self.assertFalse(await self.connector._place_cancel("101", order))
        future.call_args.args[0].close()
        self.assertEqual([555], self.data_source.cancelled)
        with patch(SAFE_ENSURE_FUTURE) as future:
            self.connector._process_fills([FillV1.from_json(fill_json("404:1", 555))])
        await future.call_args.args[0]
        await self._settle()
        self.assertIs(OrderState.CANCELED, order.current_state)
        self.assertEqual(Decimal("0.01"), order.executed_amount_base)
        self.assertNotIn("101", self.connector.in_flight_orders)

    async def test_history_scan_stops_at_the_order_creation(self):
        order = self._track("101", "559")
        order.creation_timestamp = datetime.fromisoformat(BLOCK_TIME).timestamp() + 3600
        with aioresponses() as mock:
            mock.get(
                re.compile(rf"^{INDEXER_URL}/accounts/{ACCOUNT}/orders.*"),
                payload={"items": [order_json(1, "FILLED", "0.01")], "next_cursor": "100:1"},
                repeat=True,
            )
            with self.assertRaises(IOError):
                await self.connector._request_order_status(order)
            self.assertEqual(1, self._requests(mock))

    async def test_final_frame_from_the_stream_waits_for_the_fills(self):
        order = self._track("101", "555", amount="0.02")
        cancelled = order_json(555, "CANCELLED", "0.01", quantity="0.02")
        with aioresponses() as mock:
            mock.get(FILLS_URL, payload={"items": [fill_json("405:1", 555)], "next_cursor": None})
            self.connector._process_orders_frame(StreamFrame.from_json(frame("orders", [cancelled], "update")))
            for _ in range(50):
                if not order.is_open:
                    break
                await asyncio.sleep(0.01)
        self.assertIs(OrderState.CANCELED, order.current_state)
        self.assertEqual(Decimal("0.01"), order.executed_amount_base)

    async def test_user_stream_orders_and_fills(self):
        order = self._track("101", "555", amount="0.02")
        orders_frame = frame("orders", [order_json(555, "PARTIALLY_FILLED", "0.01")])
        self.connector._process_orders_frame(StreamFrame.from_json(orders_frame))
        await self._settle()
        self.assertEqual(OrderState.PARTIALLY_FILLED, order.current_state)
        fills = StreamFrame.from_json(frame("fills", [fill_json("101:1", 555), fill_json("101:1", 555), fill_json("102:1", 999)]))
        self.connector._process_fills(FillV1.from_json(row) for row in fills.rows())
        self.assertEqual(Decimal("0.01"), order.executed_amount_base)
        self.connector._process_fills([FillV1.from_json(fill_json("103:1", 555))])
        await self._settle()
        self.assertNotIn("101", self.connector.in_flight_orders)

    async def test_user_stream_listener_dispatches_frames(self):
        order = self._track("101", "555")
        self.data_source.client_ids.seed([101])
        self.connector._user_stream_tracker._user_stream.put_nowait(frame("fills", [fill_json("104:1", 555)], "update"))
        self.connector._user_stream_tracker._user_stream.put_nowait(
            frame("positions", [{"id": 1, "pair": "BTCUSDC", "side": "LONG", "quantity": "0.1", "entry_price": "1"}])
        )
        self.connector._user_stream_tracker._user_stream.put_nowait({"type": "update", "channel": "fills", "data": [{}]})
        listener = self.local_event_loop.create_task(self.connector._user_stream_event_listener())
        for _ in range(50):
            if PAIR in self.connector.account_positions:
                break
            await asyncio.sleep(0.01)
        listener.cancel()
        self.assertEqual(OrderState.FILLED, order.current_state)
        self.assertNotIn(101, self.data_source.client_ids)
        self.assertEqual(Decimal("0.1"), self.connector.account_positions[PAIR].amount)

    async def test_orders_snapshot_refreshes_orders_that_vanished(self):
        order = self._track("101", "555")
        order.creation_timestamp = 0
        with patch.object(NeutronxPerpetualDerivative, "current_timestamp", 1000.0), \
                patch("hummingbot.connector.derivative.neutronx_perpetual.neutronx_perpetual_derivative.safe_ensure_future") as future:
            self.connector._process_orders_frame(StreamFrame.from_json(frame("orders", [])))
        future.assert_called_once()
        future.call_args.args[0].close()

    async def test_positions_and_balances(self):
        self.data_source.positions_result = (chain_position(side="SHORT"),)
        await self.connector._update_positions()
        position = self.connector.account_positions[PAIR]
        self.assertEqual((PositionSide.SHORT, Decimal("-0.2")), (position.position_side, position.amount))
        self.connector._apply_positions(self.connector._indexer_positions([]))
        self.assertEqual({}, self.connector.account_positions)
        await self.connector._update_balances()
        self.assertEqual(Decimal(1000), self.connector.get_balance("USDC"))
        self.assertEqual(Decimal(900), self.connector.get_available_balance("USDC"))

    async def test_fees_follow_the_fee_tier(self):
        default = self.connector._get_fee("BTC", "USDC", OrderType.LIMIT, TradeType.BUY, PositionAction.OPEN, Decimal(1))
        self.assertEqual(Decimal("0.0005"), default.percent)
        await self.connector._update_trading_fees()
        maker = self.connector._get_fee("BTC", "USDC", OrderType.LIMIT_MAKER, TradeType.BUY, PositionAction.OPEN, Decimal(1))
        taker = self.connector._get_fee("BTC", "USDC", OrderType.LIMIT, TradeType.BUY, PositionAction.OPEN, Decimal(1))
        self.assertEqual((Decimal(0), Decimal("0.0004")), (maker.percent, taker.percent))

    async def test_leverage_and_position_mode(self):
        self.assertEqual((True, ""), await self.connector._set_trading_pair_leverage(PAIR, 5))
        self.assertFalse((await self.connector._set_trading_pair_leverage(PAIR, 11))[0])
        self.assertFalse((await self.connector._set_trading_pair_leverage("XYZ-USDC", 1))[0])
        self.assertEqual((True, ""), await self.connector._trading_pair_position_mode_set(PositionMode.ONEWAY, PAIR))
        self.assertFalse((await self.connector._trading_pair_position_mode_set(PositionMode.HEDGE, PAIR))[0])

    async def test_leverage_set_before_trading_rules_load_them(self):
        connector = NeutronxPerpetualDerivative(
            neutronx_perpetual_account_address=ACCOUNT,
            trading_pairs=[PAIR],
            trading_required=True,
            network=NETWORK,
            data_source=FakeDataSource(),
        )
        self.assertEqual({}, connector.trading_rules)
        await connector._execute_set_leverage(PAIR, 5)
        self.assertEqual(5, connector.get_leverage(PAIR))
        self.assertIn(PAIR, connector.trading_rules)

    async def test_leverage_reports_a_market_load_failure(self):
        connector = NeutronxPerpetualDerivative(
            neutronx_perpetual_account_address=ACCOUNT,
            trading_pairs=[PAIR],
            trading_required=True,
            network=NETWORK,
            data_source=FakeDataSource(),
        )
        with patch.object(connector._data_source, "markets", side_effect=IOError("node down")):
            success, message = await connector._set_trading_pair_leverage(PAIR, 5)
        self.assertFalse(success)
        self.assertIn("node down", message)

    async def test_network_check_gates_on_indexer_lag(self):
        with aioresponses() as mock:
            mock.get(f"{INDEXER_URL}/status", payload=self._status(1))
            await self.connector._make_network_check_request()
            mock.get(f"{INDEXER_URL}/status", payload=self._status(CONSTANTS.MAX_INDEXER_LAG_BLOCKS + 1))
            with self.assertRaises(IOError):
                await self.connector._make_network_check_request()
        self.assertEqual(1, self.data_source.node_checks)

    async def test_last_traded_prices_share_one_tickers_request(self):
        tickers = [{"pair": "BTCUSDC", "last_price": "65001"}, {"pair": "ETHUSDC", "mark_price": "2500"}]
        with aioresponses() as mock:
            mock.get(f"{INDEXER_URL}/markets/tickers", payload=tickers)
            prices = await asyncio.gather(*(self.connector._get_last_traded_price(pair) for pair in (PAIR, "ETH-USDC", "SOL-USDC")))
            self.assertEqual(1, self._requests(mock))
        self.assertEqual([65001.0, 2500.0], prices[:2])
        self.assertTrue(math.isnan(prices[2]))

    def test_shared_limits_keep_room_for_every_network_check(self):
        shared = NeutronxPerpetualDerivative(
            rate_limits_share_pct=Decimal(10),
            neutronx_perpetual_account_address=ACCOUNT,
            trading_required=False,
            network=NETWORK,
            data_source=FakeDataSource(),
        )
        limits = shared._throttler._id_to_limit_map
        self.assertEqual(11, limits[CONSTANTS.INDEXER_REST_LIMIT_ID].limit)
        self.assertGreaterEqual(limits[CONSTANTS.INDEXER_STATUS_LIMIT_ID].limit, CONSTANTS.NETWORK_CHECKS_PER_MINUTE)

    async def test_network_check_survives_one_failure(self):
        check = AsyncMock(side_effect=[IOError("blip"), IOError("down"), None, IOError("blip")])
        status = PropertyMock(return_value=NetworkStatus.CONNECTED)
        with patch.object(self.connector, "_make_network_check_request", check), \
                patch.object(NeutronxPerpetualDerivative, "network_status", new_callable=lambda: status):
            self.assertIs(NetworkStatus.CONNECTED, await self.connector.check_network())
            self.assertIs(NetworkStatus.NOT_CONNECTED, await self.connector.check_network())
            status.return_value = NetworkStatus.NOT_CONNECTED
            self.assertIs(NetworkStatus.CONNECTED, await self.connector.check_network())
            status.return_value = NetworkStatus.CONNECTED
            self.assertIs(NetworkStatus.CONNECTED, await self.connector.check_network())
        status.return_value = NetworkStatus.NOT_CONNECTED
        with patch.object(self.connector, "_make_network_check_request", AsyncMock(side_effect=IOError("down"))), \
                patch.object(NeutronxPerpetualDerivative, "network_status", new_callable=lambda: status):
            self.assertIs(NetworkStatus.NOT_CONNECTED, await self.connector.check_network())

    async def test_network_check_times_out_on_its_own(self):
        async def slow():
            await asyncio.sleep(10)

        with patch.object(self.connector, "_make_network_check_request", slow), \
                patch.object(CONSTANTS, "NETWORK_CHECK_TIMEOUT", 0.01):
            self.assertIs(NetworkStatus.NOT_CONNECTED, await self.connector.check_network())

    async def test_rate_limited_status_still_means_reachable(self):
        with aioresponses() as mock:
            mock.get(f"{INDEXER_URL}/status", status=429, headers={"Retry-After": "2"}, body="{}")
            await self.connector._make_network_check_request()
        self.assertEqual(1, self.data_source.node_checks)
        self.assertGreater(self.connector._indexer_backoff.remaining, 1)
        with patch.object(self.connector, "_api_get", AsyncMock(return_value=self._status(1))) as api_get:
            await self.connector._make_network_check_request()
        self.assertEqual(CONSTANTS.INDEXER_STATUS_LIMIT_ID, api_get.call_args.kwargs["limit_id"])

    async def test_funding_payments_of_every_pair_come_from_one_request(self):
        payments = {"items": [
            {"position_id": 2, "subaccount_id": 0, "pair": "ETHUSDC", "side": "LONG", "quantity": "1", "amount": "0.5",
             "rate": "0.0002", "mark_price": "2500", "block_height": 8, "time": "2026-11-10T12:00:00+00:00"},
        ], "next_cursor": None}
        with aioresponses() as mock:
            mock.get(re.compile(rf"^{INDEXER_URL}/accounts/{ACCOUNT}/funding.*"), payload=payments)
            btc, eth = await asyncio.gather(self.connector._fetch_last_fee_payment(PAIR),
                                            self.connector._fetch_last_fee_payment("ETH-USDC"))
            self.assertEqual(1, self._requests(mock))
        self.assertEqual((0, Decimal(-1), Decimal(-1)), btc)
        self.assertEqual((Decimal("0.0002"), Decimal("0.5")), eth[1:])

    async def test_trade_history_pages_and_deduplicates(self):
        order = self._track("101", "555", amount="0.03")
        page_one = {"items": [fill_json("201:1", 555), fill_json("201:2", 777)], "next_cursor": "201:2"}
        page_two = {"items": [fill_json("202:1", 555)], "next_cursor": None}
        with aioresponses() as mock:
            mock.get(re.compile(rf"^{INDEXER_URL}/accounts/{ACCOUNT}/fills\?limit=200&pair=.*"), payload=page_one)
            mock.get(re.compile(rf"^{INDEXER_URL}/accounts/{ACCOUNT}/fills\?cursor=201.*"), payload=page_two)
            updates = await self.connector._all_trade_updates_for_order(order)
        self.assertEqual(["201:1", "202:1"], [u.trade_id for u in updates])
        with aioresponses() as mock:
            mock.get(re.compile(rf"^{INDEXER_URL}/accounts/{ACCOUNT}/fills\?limit=200$"), payload=page_one, repeat=True)
            await self.connector._update_trade_history()
            await self.connector._update_trade_history()
        self.assertEqual(Decimal("0.01"), order.executed_amount_base)

    async def test_trade_history_skips_when_nothing_is_tracked(self):
        with aioresponses():
            await self.connector._update_trade_history()

    async def test_lost_orders_are_checked_before_any_cancel_tx(self):
        open_lost = self._track("101", "555")
        gone_lost = self._track("102", "556")
        for order in (open_lost, gone_lost):
            self.connector._order_tracker._lost_orders[order.client_order_id] = order
        self.data_source.open_orders_result = (chain_order(555),)
        self.data_source.orders[556] = chain_order(556, "CANCELLED")
        await self.connector._cancel_lost_orders()
        self.assertEqual([555], self.data_source.cancelled)

    async def test_polling_cycle_reads_everything(self):
        with patch.object(self.connector, "_update_trade_history") as history:
            await self.connector._status_polling_loop_fetch_updates()
        history.assert_awaited_once()
        self.assertEqual(Decimal(1000), self.connector.get_balance("USDC"))

    async def test_funding_payment_comes_from_the_indexer(self):
        payments = {
            "items": [
                {"position_id": 1, "subaccount_id": 3, "pair": "BTCUSDC", "side": "LONG", "quantity": "1",
                 "amount": "9", "rate": "0.1", "mark_price": "1", "block_height": 9, "time": "2026-11-10T13:00:00+00:00"},
                {"position_id": 2, "subaccount_id": 0, "pair": "BTCUSDC", "side": "LONG", "quantity": "1",
                 "amount": "-0.25", "rate": "0.0001", "mark_price": "65000", "block_height": 8,
                 "time": "2026-11-10T12:00:00+00:00"},
            ],
            "next_cursor": None,
        }
        with aioresponses() as mock:
            mock.get(re.compile(rf"^{INDEXER_URL}/accounts/{ACCOUNT}/funding.*"), payload=payments)
            timestamp, rate, amount = await self.connector._fetch_last_fee_payment(PAIR)
            mock.get(re.compile(rf"^{INDEXER_URL}/accounts/{ACCOUNT}/funding.*"), payload={"items": [], "next_cursor": None})
            empty = await self.connector._fetch_last_fee_payment(PAIR)
        self.assertEqual((Decimal("0.0001"), Decimal("-0.25")), (rate, amount))
        self.assertEqual(datetime(2026, 11, 10, 12, tzinfo=timezone.utc).timestamp(), timestamp)
        self.assertEqual((0, Decimal(-1), Decimal(-1)), empty)

    async def test_final_status_from_the_stream_frees_the_client_id(self):
        order = self._track("101", "555")
        self.data_source.client_ids.seed([101])
        cancelled = {**order_json(555, "CANCELLED", client_id=101), "cancel_reason": "user_cancelled"}
        self.connector._process_orders_frame(StreamFrame.from_json(frame("orders", [cancelled])))
        await self._settle()
        self.assertNotIn("101", self.connector.in_flight_orders)
        self.assertNotIn(101, self.data_source.client_ids)
        self.assertIs(OrderState.CANCELED, order.current_state)

    def test_indexer_api_key_raises_limits(self):
        keyed = NeutronxPerpetualDerivative(
            neutronx_perpetual_account_address=ACCOUNT,
            neutronx_perpetual_indexer_api_key=" nx_key ",
            trading_required=False,
            network=NETWORK,
            data_source=FakeDataSource(),
        )
        self.assertEqual(("nx_key", 200, 594), (keyed.api_key, keyed.max_subscriptions, keyed.rate_limits_rules[0].limit))
        self.assertEqual((None, 50, 114), (self.connector.api_key, self.connector.max_subscriptions,
                                           self.connector.rate_limits_rules[0].limit))

    @staticmethod
    def _status(lag: int) -> Dict[str, Any]:
        return {"indexed_height": 10, "chain_height": 10 + lag, "lag_blocks": lag, "indexed_age_seconds": 1.0}
