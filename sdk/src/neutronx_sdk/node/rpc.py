from __future__ import annotations

from typing import Any

import grpc
from google.protobuf.message import Message

from neutronx_sdk.proto import method

DEFAULT_TIMEOUT = 10.0
MAX_RECEIVE_MESSAGE_LENGTH = 16 * 1024 * 1024
KEEPALIVE_OPTIONS: tuple[tuple[str, int], ...] = (
    ("grpc.keepalive_time_ms", 30_000),
    ("grpc.keepalive_timeout_ms", 10_000),
    ("grpc.keepalive_permit_without_calls", 1),
    ("grpc.http2.max_pings_without_data", 0),
    ("grpc.http2.min_time_between_pings_ms", 10_000),
    ("grpc.max_receive_message_length", MAX_RECEIVE_MESSAGE_LENGTH),
)


def create_channel(endpoint: str, *, secure: bool) -> grpc.aio.Channel:
    options = list(KEEPALIVE_OPTIONS)
    if secure:
        return grpc.aio.secure_channel(endpoint, grpc.ssl_channel_credentials(), options=options)
    return grpc.aio.insecure_channel(endpoint, options=options)


def _serialize(message: Message) -> bytes:
    return message.SerializeToString()


class RpcClient:
    __slots__ = ("_calls", "_channel", "_timeout")

    def __init__(self, channel: grpc.aio.Channel, timeout: float = DEFAULT_TIMEOUT) -> None:
        if timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")
        self._channel = channel
        self._timeout = timeout
        self._calls: dict[str, Any] = {}

    @property
    def channel(self) -> grpc.aio.Channel:
        return self._channel

    @property
    def timeout(self) -> float:
        return self._timeout

    async def call(
        self,
        service: str,
        name: str,
        request: Message | None = None,
        *,
        timeout: float | None = None,
        **fields: Any,
    ) -> Any:
        rpc = method(service, name)
        message = request if request is not None else rpc.request_type(**fields)
        call = self._calls.get(rpc.path)
        if call is None:
            call = self._channel.unary_unary(
                rpc.path,
                request_serializer=_serialize,
                response_deserializer=rpc.response_type.FromString,
            )
            self._calls[rpc.path] = call
        return await call(message, timeout=self._timeout if timeout is None else timeout)
