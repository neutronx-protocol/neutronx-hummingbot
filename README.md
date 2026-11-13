# neutronx-hummingbot

A [Hummingbot](https://github.com/hummingbot/hummingbot) connector for the NeutronX perpetuals
exchange, and the Python SDK it is built on.

| Directory | Contents |
|---|---|
| [`connector/`](connector/README.md) | `neutronx_perpetual`, laid out the way it lands in `hummingbot/connector/derivative/` |
| [`sdk/`](sdk/README.md) | [`neutronx-sdk`](https://pypi.org/project/neutronx-sdk/): keys and agent keys, transaction building and signing, gRPC queries, broadcasting |

## Getting started

To trade on NeutronX from Hummingbot, follow [`connector/README.md`](connector/README.md): it
installs Hummingbot with the connector and walks through `connect`.

To talk to the chain from your own Python code, install the SDK from PyPI and start with
[`sdk/README.md`](sdk/README.md):

```bash
pip install neutronx-sdk
```

## Status

The SDK is released on PyPI. The connector is installed from this
repository and has been run against the NeutronX testnet and mainnet under Hummingbot 2.17.0; see
the limitations listed in the connector README before using it with real funds.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Changes are recorded in [`CHANGELOG.md`](CHANGELOG.md).

## License

[Apache License 2.0](LICENSE). Copyright 2026 NeutronX.
