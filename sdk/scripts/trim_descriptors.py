from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

from google.protobuf import descriptor_pb2
from google.protobuf.message import Message as ProtoMessage

KEEP_MESSAGES = (
    "cosmos.auth.v1beta1.BaseAccount",
    "cosmos.base.abci.v1beta1.TxMsgData",
    "cosmos.crypto.secp256k1.PubKey",
    "cosmos.tx.v1beta1.SignDoc",
    "cosmos.tx.v1beta1.TxRaw",
    "neutronx.agentkeys.v1.TxExtension",
    "neutronx.orderbook.v1.MsgBatchCancelOrders",
    "neutronx.orderbook.v1.MsgBatchCancelOrdersResponse",
    "neutronx.orderbook.v1.MsgBatchPlaceOrders",
    "neutronx.orderbook.v1.MsgBatchPlaceOrdersResponse",
    "neutronx.orderbook.v1.MsgCancelOrder",
    "neutronx.orderbook.v1.MsgCancelShortTermOrder",
    "neutronx.orderbook.v1.MsgPlaceOrder",
    "neutronx.orderbook.v1.MsgPlaceOrderResponse",
    "neutronx.orderbook.v1.MsgPlaceShortTermOrder",
    "neutronx.orderbook.v1.MsgPlaceShortTermOrderResponse",
    "neutronx.orderbook.v1.MsgReplaceOrder",
    "neutronx.perps.v1.MsgClosePosition",
    "neutronx.perps.v1.MsgDepositToSubaccount",
    "neutronx.perps.v1.MsgWithdrawFromSubaccount",
)

KEEP_METHODS = {
    "cosmos.auth.v1beta1.Query": ("Account",),
    "cosmos.bank.v1beta1.Query": ("AllBalances",),
    "cosmos.base.node.v1beta1.Service": ("Status",),
    "cosmos.tx.v1beta1.Service": ("BroadcastTx", "GetTx", "Simulate"),
    "neutronx.agentkeys.v1.Query": ("AgentKey", "Params"),
    "neutronx.oracle.v1.Query": ("AllPrices", "Price"),
    "neutronx.orderbook.v1.Query": ("FeeTier", "Order", "OrderBook", "Params", "UserOrders"),
    "neutronx.perps.v1.Query": (
        "Market",
        "Markets",
        "Params",
        "Positions",
        "SubaccountBalance",
        "SubaccountEquity",
    ),
}

Message = descriptor_pb2.DescriptorProto
File = descriptor_pb2.FileDescriptorProto


def _qualified(file: File, name: str) -> str:
    return f"{file.package}.{name}" if file.package else name


def _nested(message: Message) -> Iterator[Message]:
    yield message
    for child in message.nested_type:
        yield from _nested(child)


def _referenced(message: Message) -> Iterator[str]:
    for part in _nested(message):
        for field in part.field:
            if field.type_name:
                yield field.type_name.lstrip(".")


def _top_level(name: str, owners: dict[str, str]) -> str:
    while name not in owners:
        name, _, _ = name.rpartition(".")
        if not name:
            raise KeyError("type is not in the descriptor set")
    return name


def _drop_empty_options(node: ProtoMessage) -> None:
    for field, value in node.ListFields():
        if field.type != field.TYPE_MESSAGE:
            continue
        if field.name == "options":
            if not value.ByteSize():
                node.ClearField("options")
            continue
        for child in (value,) if isinstance(value, ProtoMessage) else value:
            _drop_empty_options(child)


def trim(file_set: descriptor_pb2.FileDescriptorSet) -> descriptor_pb2.FileDescriptorSet:
    owners: dict[str, str] = {}
    messages: dict[str, Message] = {}
    for file in file_set.file:
        for message in file.message_type:
            owners[_qualified(file, message.name)] = file.name
            messages[_qualified(file, message.name)] = message
        for enum in file.enum_type:
            owners[_qualified(file, enum.name)] = file.name

    queue: list[str] = list(KEEP_MESSAGES)
    for file in file_set.file:
        for service in file.service:
            wanted = KEEP_METHODS.get(_qualified(file, service.name), ())
            for method in service.method:
                if method.name in wanted:
                    queue += [method.input_type.lstrip("."), method.output_type.lstrip(".")]

    kept: set[str] = set()
    while queue:
        name = _top_level(queue.pop(), owners)
        if name in kept:
            continue
        kept.add(name)
        if name in messages:
            queue.extend(_referenced(messages[name]))

    trimmed = descriptor_pb2.FileDescriptorSet()
    for file in file_set.file:
        for service in list(file.service):
            wanted = KEEP_METHODS.get(_qualified(file, service.name), ())
            methods = [method for method in service.method if method.name in wanted]
            if not methods:
                file.service.remove(service)
                continue
            del service.method[:]
            service.method.extend(methods)
        for message in list(file.message_type):
            if _qualified(file, message.name) not in kept:
                file.message_type.remove(message)
        for enum in list(file.enum_type):
            if _qualified(file, enum.name) not in kept:
                file.enum_type.remove(enum)
        if not (file.message_type or file.enum_type or file.service):
            continue

        used = {
            owners[_top_level(name, owners)] for m in file.message_type for name in _referenced(m)
        }
        for service in file.service:
            for method in service.method:
                used.add(owners[_top_level(method.input_type.lstrip("."), owners)])
                used.add(owners[_top_level(method.output_type.lstrip("."), owners)])
        used.discard(file.name)
        del file.dependency[:]
        file.dependency.extend(sorted(used))
        del file.public_dependency[:]
        del file.weak_dependency[:]
        del file.extension[:]
        file.ClearField("options")
        file.DiscardUnknownFields()
        _drop_empty_options(file)
        trimmed.file.append(file)

    missing = set(KEEP_MESSAGES) - kept
    if missing:
        raise KeyError(f"not in the descriptor set: {sorted(missing)}")
    return trimmed


if __name__ == "__main__":
    target = Path(sys.argv[1])
    before = descriptor_pb2.FileDescriptorSet.FromString(target.read_bytes())
    files = len(before.file)
    after = trim(before)
    target.write_bytes(after.SerializeToString(deterministic=True))
    print(f"kept {len(after.file)} of {files} files in {target}")
