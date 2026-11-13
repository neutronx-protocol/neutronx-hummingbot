from importlib.metadata import PackageNotFoundError, version

from neutronx_sdk.client_ids import ClientIdAllocator
from neutronx_sdk.crypto import PrivateKey, PublicKey
from neutronx_sdk.exceptions import (
    ChainTxError,
    NeutronXError,
    TxConfirmationTimeoutError,
    TxFailure,
    classify_tx_failure,
)
from neutronx_sdk.network import MAINNET, TESTNET, Network
from neutronx_sdk.node import AccountSequence, ChainClock, NodeClient, TxSender
from neutronx_sdk.orders import OrderRequest, OrderType, Side, TimeInForce
from neutronx_sdk.tx import FeePolicy, SignedTx, TxBuilder, UnorderedNonce
from neutronx_sdk.wallet import Wallet

try:
    __version__ = version("neutronx-sdk")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "MAINNET",
    "TESTNET",
    "AccountSequence",
    "ChainClock",
    "ChainTxError",
    "ClientIdAllocator",
    "FeePolicy",
    "Network",
    "NeutronXError",
    "NodeClient",
    "OrderRequest",
    "OrderType",
    "PrivateKey",
    "PublicKey",
    "Side",
    "SignedTx",
    "TimeInForce",
    "TxBuilder",
    "TxConfirmationTimeoutError",
    "TxFailure",
    "TxSender",
    "UnorderedNonce",
    "Wallet",
    "__version__",
    "classify_tx_failure",
]
