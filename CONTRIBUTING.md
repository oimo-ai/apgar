# Contributing

## Development stack

`docker-compose.yml` runs the published images. `docker-compose.dev.yml` builds the images from this checkout instead, and publishes ClickHouse on port 8123 and the API on port 8000 for the scripts in `scripts/`. The Make targets use both files.

```bash
cp .env.example .env
make up
```

Fill the three secrets in `.env` before `make up`. The UI runs at http://localhost:8080. `make down` stops the stack and deletes its data.

For other Compose commands against the development stack, add this line to `.env`:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml
```

## Checks

| Command | Runs |
| --- | --- |
| `make sync` | Installs the Python environment |
| `make lint typecheck` | `ruff` and `mypy --strict` |
| `make test-unit` | Unit tests, no services needed |
| `make ch-test-up test-integration` | Integration tests against a ClickHouse on port 18123 |
| `make ui-install ui-lint ui-typecheck ui-test` | UI checks and Vitest |
| `make e2e` | Playwright against the development stack |
| `make ci` | Everything CI runs, with coverage gates |

## Releases

1. Set the version in `pyproject.toml`, `apgar/__init__.py`, `ui/package.json`, and both image tags in `docker-compose.yml`. Then run `uv lock` and, in `ui/`, `npm version X.Y.Z --no-git-tag-version`. `tests/unit/test_release_version.py` fails until all of them agree.
2. Merge the change, then tag the commit on `main` and push the tag:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

3. `.github/workflows/release.yml` checks the tag with `scripts/release_version.py`, pushes `ghcr.io/oimo-ai/apgar` and `ghcr.io/oimo-ai/apgar-ui` tagged `X.Y.Z`, `X.Y`, and `latest`, and publishes a GitHub release with the Compose file attached.

A tag with a suffix, such as `vX.Y.Z-rc.1`, is a prerelease. The version files keep `X.Y.Z`. Its images are tagged only `X.Y.Z-rc.1`, its attached Compose file points at them, and the GitHub release is marked as a prerelease, so `releases/latest` keeps pointing at the last stable release.

When a release changes `.env`, the Compose file, or needs a step before it starts, add upgrade notes to the release text.
