#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HB_TAG="${HB_TAG:-v2.17.0}"
HB_DIR="${HB_DIR:-$REPO_DIR/hummingbot}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"

command -v uv >/dev/null || { echo "uv is required" >&2; exit 1; }

[[ -d "$HB_DIR/.git" ]] || git clone -q --depth 1 --branch "$HB_TAG" https://github.com/hummingbot/hummingbot.git "$HB_DIR"
cd "$HB_DIR"
unset VIRTUAL_ENV
[[ -d .venv ]] || uv venv -q --python "$PYTHON_VERSION" .venv
export VIRTUAL_ENV="$HB_DIR/.venv"

uv pip install -q setuptools wheel "cython>=3.0.12" "numpy>=2.2.6"
uv pip install -q \
  "aiohttp>=3.8.5,<3.14" "aiomqtt>=2.0.0" appnope "asyncssh>=2.13.2" "aioprocessing>=2.0.1" "aioresponses>=0.7.4" \
  "aiounittest>=1.4.2" "aptos-sdk>=0.8.0" "async-timeout>=4.0.2,<5" "base58>=2.1.1" "bidict>=0.22.1" bip-utils \
  "Brotli>=1.2.0" "cachetools>=5.3.1" "cryptography>=41.0.2" "decibel-python-sdk==0.2.1" "eth-account>=0.13.0" \
  "injective-py==1.14.*" msgpack "numba>=0.61.2" objgraph "pandas>=2.3.2" "pandas-ta>=0.4.71b" "prompt_toolkit>=3.0.39" "psutil>=5.9.5" "ptpython>3.0.25" \
  "pydantic>=2" "pyjwt>=2.3.0" "pyperclip>=1.8.2" "requests>=2.31.0" "ruamel.yaml>=0.2.5" safe-pysha3 scalecodec \
  "scipy>=1.11.1" "six>=1.16.0" "solders>=0.19.0" "sqlalchemy>=1.4.49" "tabulate==0.9.0" "tqdm>=4.67.1" \
  "typer>=0.9.0" "ujson>=5.7.0" "urllib3>=1.26.15,<2.0" web3 "xrpl-py>=4.4.0" "PyYaml>=0.2.5" "lighter-sdk==1.0.8" \
  pytest pytest-asyncio pytest-cov flake8 isort

.venv/bin/python setup.py build_ext --inplace -j 8 > build.log 2>&1
"$REPO_DIR/connector/scripts/link_hummingbot.sh" "$HB_DIR"
.venv/bin/python -c "from hummingbot.client.settings import AllConnectorSettings as S; s = S.create_connector_settings(); assert 'neutronx_perpetual' in s; print('Hummingbot', '$HB_TAG', 'ready with neutronx_perpetual')"
