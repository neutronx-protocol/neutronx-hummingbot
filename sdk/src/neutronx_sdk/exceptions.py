from __future__ import annotations

import re
from enum import Enum

CODE_TX_IN_MEMPOOL_CACHE = 19
_QUEUED_HEIGHT = re.compile(r"queued for height (\d+)")
_MISSING_ORDER = re.compile(r"order (\d+): order not found")


class TxFailure(str, Enum):
    DUPLICATE = "duplicate"
    CLIENT_ID_CONFLICT = "client_id_conflict"
    REPLACE_GTB_DOWNGRADE = "replace_gtb_downgrade"
    ORDER_GONE = "order_gone"
    MARKET_PAUSED = "market_paused"
    GAS_FLOOR = "gas_floor"
    AGENT_KEY = "agent_key"
    SIGNER_BUDGET = "signer_budget"
    OUT_OF_GAS = "out_of_gas"
    COLLATERAL = "collateral"
    SEQUENCE_MISMATCH = "sequence_mismatch"
    STALE_GOOD_TIL_BLOCK = "stale_good_til_block"
    UNKNOWN = "unknown"


_CODE_FAILURES = {CODE_TX_IN_MEMPOOL_CACHE: TxFailure.DUPLICATE}

_MARKER_FAILURES = (
    ("agent key", TxFailure.AGENT_KEY),
    ("unordered", TxFailure.AGENT_KEY),
    ("replace requires good_til_block", TxFailure.REPLACE_GTB_DOWNGRADE),
    ("already in use", TxFailure.CLIENT_ID_CONFLICT),
    ("order not found", TxFailure.ORDER_GONE),
    ("not found", TxFailure.ORDER_GONE),
    ("http 404", TxFailure.ORDER_GONE),
    ("is paused", TxFailure.MARKET_PAUSED),
    ("below the floor", TxFailure.GAS_FLOOR),
    ("per-block rate limit exceeded", TxFailure.SIGNER_BUDGET),
    ("out of gas", TxFailure.OUT_OF_GAS),
    ("collateral insufficient", TxFailure.COLLATERAL),
    ("account sequence mismatch", TxFailure.SEQUENCE_MISMATCH),
    ("good_til_block in the past", TxFailure.STALE_GOOD_TIL_BLOCK),
)

EXPECTED_TX_FAILURES = frozenset(
    {
        TxFailure.DUPLICATE,
        TxFailure.CLIENT_ID_CONFLICT,
        TxFailure.REPLACE_GTB_DOWNGRADE,
        TxFailure.ORDER_GONE,
        TxFailure.MARKET_PAUSED,
    }
)


def classify_tx_failure(code: int | None, raw_log: str) -> TxFailure:
    if code is not None and code in _CODE_FAILURES:
        return _CODE_FAILURES[code]
    text = raw_log.lower()
    for marker, failure in _MARKER_FAILURES:
        if marker in text:
            return failure
    return TxFailure.UNKNOWN


def queued_height(raw_log: str) -> int | None:
    match = _QUEUED_HEIGHT.search(raw_log)
    return int(match.group(1)) if match else None


def missing_order_ids(raw_log: str) -> tuple[int, ...]:
    return tuple(int(order_id) for order_id in _MISSING_ORDER.findall(raw_log))


class NeutronXError(Exception):
    pass


class ChainTxError(NeutronXError):
    def __init__(
        self,
        code: int,
        raw_log: str,
        *,
        tx_hash: str = "",
        height: int = 0,
        check_tx: bool = False,
    ) -> None:
        super().__init__(f"tx failed code={code} hash={tx_hash} raw_log={raw_log}")
        self.code = code
        self.raw_log = raw_log
        self.tx_hash = tx_hash
        self.height = height
        self.check_tx = check_tx

    @property
    def failure(self) -> TxFailure:
        return classify_tx_failure(self.code, self.raw_log)

    @property
    def expected(self) -> bool:
        return self.failure in EXPECTED_TX_FAILURES

    @property
    def queued_height(self) -> int | None:
        return queued_height(self.raw_log)

    @property
    def missing_order_ids(self) -> tuple[int, ...]:
        return missing_order_ids(self.raw_log)


class TxConfirmationTimeoutError(NeutronXError):
    def __init__(self, tx_hash: str, timeout: float) -> None:
        super().__init__(f"tx {tx_hash} not committed within {timeout}s")
        self.tx_hash = tx_hash
        self.timeout = timeout
