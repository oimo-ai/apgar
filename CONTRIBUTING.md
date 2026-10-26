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
| `make chart-lint` | `helm lint --strict` with each file in `deploy/helm/apgar/ci/` |
| `make chart-smoke` | Installs, upgrades, and tests the chart on the current Kubernetes context. Load `apgar:dev` and `apgar-ui:dev` onto the nodes first, for example with `kind load docker-image` |
| `make ci` | Everything CI runs, with coverage gates |

## Helm chart

The chart in `deploy/helm/apgar` uses no Helm hooks, so a first install, an upgrade, `helm template | kubectl apply`, Argo CD, and Flux all run the same way. The worker runs `apgar migrate --timeout` in an init container, and the API runs `apgar wait-for-schema` in one. Exactly one worker runs, as a StatefulSet, so a replacement worker reclaims the heartbeat of the pod it replaces. Pods set `enableServiceLinks: false`, because a Service named `apgar-api` would otherwise inject `APGAR_API_PORT` into every container. The chart never generates or defaults `APGAR_SECRET_KEY` or the other secrets.

## Releases

1. Set the version on a branch:

   ```bash
   make version VERSION=X.Y.Z
   ```

   It writes `X.Y.Z` to `pyproject.toml`, `apgar/__init__.py`, `ui/package.json`, `ui/package-lock.json`, `uv.lock`, both image tags in `docker-compose.yml`, and `version` and `appVersion` in `deploy/helm/apgar/Chart.yaml`, and prints the tag to push. `tests/unit/test_release_version.py` fails while these places disagree.
2. Merge the change, then tag the commit on `main` and push the tag:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

3. `.github/workflows/release.yml` checks the tag with `scripts/release_version.py`, pushes `ghcr.io/oimo-ai/apgar` and `ghcr.io/oimo-ai/apgar-ui` tagged `X.Y.Z`, `X.Y`, and `latest`, pushes the chart to `oci://ghcr.io/oimo-ai/charts/apgar` with version `X.Y.Z`, and publishes a GitHub release with the Compose file attached.

A tag with a suffix, such as `vX.Y.Z-rc.1`, is a prerelease. Its images are tagged only `X.Y.Z-rc.1`, its attached Compose file points at them, and the GitHub release is marked as a prerelease, so `releases/latest` keeps pointing at the last stable release. The version files keep `X.Y.Z`: `make version VERSION=X.Y.Z-rc.1` writes `X.Y.Z` and prints the tag `vX.Y.Z-rc.1`.

When a release changes `.env`, the Compose file, or needs a step before it starts, add upgrade notes to the release text.
