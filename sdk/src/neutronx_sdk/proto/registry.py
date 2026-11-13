from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import Message

DESCRIPTORS_RESOURCE = "descriptors.binpb"
DESCRIPTORS_REF_RESOURCE = "descriptors.ref"
TYPE_URL_PREFIX = "/"
_PACKAGE = __name__.rpartition(".")[0]


@dataclass(frozen=True)
class Method:
    path: str
    request_type: type[Message]
    response_type: type[Message]


@cache
def pool() -> descriptor_pool.DescriptorPool:
    data = resources.files(_PACKAGE).joinpath(DESCRIPTORS_RESOURCE).read_bytes()
    file_set = descriptor_pb2.FileDescriptorSet.FromString(data)
    private_pool = descriptor_pool.DescriptorPool()
    for file_proto in file_set.file:
        private_pool.AddSerializedFile(file_proto.SerializeToString())
    return private_pool


@cache
def descriptors_ref() -> str:
    return resources.files(_PACKAGE).joinpath(DESCRIPTORS_REF_RESOURCE).read_text().strip()


@cache
def message_class(full_name: str) -> type[Message]:
    return message_factory.GetMessageClass(pool().FindMessageTypeByName(full_name))


@cache
def method(service: str, name: str) -> Method:
    descriptor = pool().FindServiceByName(service).FindMethodByName(name)
    return Method(
        path=f"/{service}/{name}",
        request_type=message_class(descriptor.input_type.full_name),
        response_type=message_class(descriptor.output_type.full_name),
    )


def new(full_name: str, **fields: Any) -> Any:
    return message_class(full_name)(**fields)


def parse(full_name: str, data: bytes) -> Any:
    return message_class(full_name).FromString(data)


def type_url(message: Message) -> str:
    return TYPE_URL_PREFIX + message.DESCRIPTOR.full_name


def pack_any(message: Message) -> Any:
    return new("google.protobuf.Any", type_url=type_url(message), value=message.SerializeToString())


def unpack_any(packed: Any, full_name: str) -> Any:
    expected = TYPE_URL_PREFIX + full_name
    if packed.type_url != expected:
        raise ValueError(f"expected {expected}, got {packed.type_url}")
    return message_class(full_name).FromString(packed.value)
