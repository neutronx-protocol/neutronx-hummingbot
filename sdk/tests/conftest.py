from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def golden() -> dict[str, Any]:
    return json.loads((FIXTURES / "golden_txs.json").read_text())
