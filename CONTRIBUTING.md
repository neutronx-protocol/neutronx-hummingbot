# Contributing

Bug reports and pull requests are welcome.

## Reporting a problem

Open an issue with the Hummingbot version, the network (mainnet or testnet), what you did, what
you expected and what happened. Log lines from the connector help; remove keys and addresses you
do not want public.

Report security problems privately to the maintainers rather than in a public issue.

## Working on the SDK

```bash
cd sdk
uv sync
uv run pytest
uv run ruff check
uv run ruff format --check
uv run pyright
```

`uv run pytest -m live` reads the public testnet and needs network access.

## Working on the connector

```bash
connector/scripts/setup_hummingbot.sh
cd hummingbot
.venv/bin/python -m pytest test/hummingbot/connector/derivative/neutronx_perpetual
.venv/bin/flake8 --config .flake8 hummingbot/connector/derivative/neutronx_perpetual
.venv/bin/isort --settings-path pyproject.toml --check-only hummingbot/connector/derivative/neutronx_perpetual
```

The setup script clones Hummingbot into `hummingbot/` and links the connector and its tests into
it, so edits under `connector/` are picked up without copying.

## Releasing the SDK

Releases are published to PyPI by the `publish-sdk` workflow when a tag named `sdk-v<version>` is
pushed. A published version cannot be replaced, so every change ships as a new version.

1. Set the new version in `sdk/pyproject.toml` and run `uv lock` in `sdk/`.
2. Move the entries under `Unreleased` in `CHANGELOG.md` to a section for the version and date.
3. Merge to `main` and wait for CI to pass.
4. Tag that commit and push the tag:

   ```bash
   git tag -a sdk-v0.1.1 -m "neutronx-sdk 0.1.1"
   git push origin sdk-v0.1.1
   ```

The workflow refuses a tag that does not match the version in `sdk/pyproject.toml`.

## Pull requests

- Keep a change to one purpose and add tests for the behaviour it changes.
- Run the checks above; they are the same ones CI runs for the SDK.
- Chain rules belong in the SDK, Hummingbot types in the connector.
- Describe user-visible changes in `CHANGELOG.md` under `Unreleased`.
- Never commit keys, mnemonics or `.env` files.
