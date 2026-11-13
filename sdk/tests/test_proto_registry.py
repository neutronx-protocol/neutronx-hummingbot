from __future__ import annotations

import re
from pathlib import Path

import pytest
from google.protobuf import descriptor_pool

from neutronx_sdk.proto import (
    descriptors_ref,
    message_class,
    method,
    new,
    pack_any,
    pool,
    type_url,
    unpack_any,
)


def test_descriptors_do_not_touch_the_global_pool() -> None:
    pool()
    message_class("cosmos.tx.v1beta1.TxBody")
    for name in ("cosmos/tx/v1beta1/tx.proto", "neutronx/orderbook/v1/tx.proto"):
        with pytest.raises(KeyError):
            descriptor_pool.Default().FindFileByName(name)


def test_methods_resolve_from_services() -> None:
    rpc = method("neutronx.orderbook.v1.Query", "OrderBook")
    assert rpc.path == "/neutronx.orderbook.v1.Query/OrderBook"
    assert rpc.request_type.DESCRIPTOR.full_name == "neutronx.orderbook.v1.QueryOrderBookRequest"
    assert rpc.response_type.DESCRIPTOR.full_name == "neutronx.orderbook.v1.QueryOrderBookResponse"


def test_any_round_trip() -> None:
    extension = new("neutronx.agentkeys.v1.TxExtension", key_id=9)
    packed = pack_any(extension)
    assert packed.type_url == "/neutronx.agentkeys.v1.TxExtension"
    assert type_url(extension) == packed.type_url
    assert unpack_any(packed, "neutronx.agentkeys.v1.TxExtension").key_id == 9
    with pytest.raises(ValueError, match="expected"):
        unpack_any(packed, "cosmos.auth.v1beta1.BaseAccount")


def _source() -> str:
    package = Path(__file__).parent.parent / "src" / "neutronx_sdk"
    return "\n".join(path.read_text() for path in sorted(package.rglob("*.py")))


def _called_methods() -> set[tuple[str, str]]:
    source = _source()
    constants = dict(re.findall(r'^([A-Z_]+) = "((?:cosmos|neutronx)\.[\w.]+)"$', source, re.M))
    calls = re.findall(r'\.call\(\s*([A-Z_]+),\s*"(\w+)"', source)
    return {(constants[constant], name) for constant, name in calls}


def test_every_proto_name_in_the_source_is_in_the_descriptors() -> None:
    names = set(re.findall(r'"((?:cosmos|neutronx|google)\.[A-Za-z0-9_.]+)"', _source()))
    services = {service for service, _ in _called_methods()}
    assert len(names) > 30
    for name in sorted(names - services):
        assert message_class(name).DESCRIPTOR.full_name == name
    for name in sorted(services):
        assert pool().FindServiceByName(name).full_name == name


def test_descriptors_carry_exactly_the_methods_the_sdk_calls() -> None:
    called = _called_methods()
    shipped = {
        (service, rpc.name)
        for service in {service for service, _ in called}
        for rpc in pool().FindServiceByName(service).methods
    }
    assert len(called) > 15
    assert shipped == called
    for service, name in called:
        assert method(service, name).path == f"/{service}/{name}"


def test_descriptors_leave_out_what_the_sdk_does_not_use() -> None:
    for name in (
        "neutronx.perps.v1.Msg",
        "neutronx.orderbook.v1.Msg",
        "neutronx.oracle.v1.Msg",
        "neutronx.perps.v1.MsgUpdateParams",
        "neutronx.oracle.v1.MsgSubmitPrice",
    ):
        with pytest.raises(KeyError):
            pool().FindFileContainingSymbol(name)


def test_descriptors_name_their_chain_release() -> None:
    tag, sdk_label, sdk_version = descriptors_ref().split()
    assert tag.startswith("v")
    assert sdk_label == "cosmos-sdk"
    assert sdk_version.startswith("v0.")


@pytest.mark.parametrize(
    ("service", "name"),
    [
        ("cosmos.auth.v1beta1.Query", "Account"),
        ("cosmos.bank.v1beta1.Query", "AllBalances"),
        ("cosmos.base.node.v1beta1.Service", "Status"),
        ("cosmos.tx.v1beta1.Service", "BroadcastTx"),
        ("cosmos.tx.v1beta1.Service", "GetTx"),
        ("cosmos.tx.v1beta1.Service", "Simulate"),
        ("neutronx.orderbook.v1.Query", "UserOrders"),
        ("neutronx.orderbook.v1.Query", "FeeTier"),
        ("neutronx.perps.v1.Query", "Markets"),
        ("neutronx.perps.v1.Query", "SubaccountEquity"),
        ("neutronx.oracle.v1.Query", "AllPrices"),
        ("neutronx.agentkeys.v1.Query", "AgentKey"),
    ],
)
def test_every_rpc_the_sdk_calls_is_described(service: str, name: str) -> None:
    assert method(service, name).path == f"/{service}/{name}"
