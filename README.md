# Apgar

Apgar watches the first hours of every release of an LLM agent and reports whether the agent started behaving worse than it did on the previous release: more tool errors, retries and loops, fewer tool calls, shorter answers, higher cost per turn. It computes this from the traces the team already collects, on all traffic, with no LLM judge, no dataset, and no stored prompt or completion text. One Slack message per release, one page to watch.

Apgar is not a dashboard, an evaluation harness, or a rollout controller. It compares a release with the previous one, says where the change is concentrated, and leaves the decision to the team and its tooling.

The name refers to the Apgar score, a standardized health check performed on a newborn immediately after birth. Apgar performs the equivalent check on a release immediately after deployment.

## Install

Apgar runs on one host with Docker Compose: ClickHouse, the API, the worker, and the UI. It needs Docker with Compose v2, `curl`, and `openssl`.

```bash
mkdir apgar && cd apgar
curl -fsSLO https://github.com/oimo-ai/apgar/releases/latest/download/docker-compose.yml
cat > .env <<EOF
APGAR_SECRET_KEY=$(openssl rand -hex 32)
APGAR_ADMIN_TOKEN=$(openssl rand -hex 16)
CLICKHOUSE_PASSWORD=$(openssl rand -hex 16)
APGAR_PUBLIC_URL=http://localhost:8080
EOF
docker compose up -d --wait
```

Open http://localhost:8080 and sign in with the value of `APGAR_ADMIN_TOKEN` in `.env`. While no agent exists, the Agents page offers demo data to explore.

On a server, set `APGAR_PUBLIC_URL` to the address people and exporters use, and terminate TLS in a reverse proxy in front of port 8080.

### Kubernetes

The Helm chart runs the same services, with ClickHouse in the release or your own. Create the Secret first; the chart never generates these values:

```bash
kubectl create namespace apgar
kubectl -n apgar create secret generic apgar \
  --from-literal=APGAR_SECRET_KEY=$(openssl rand -hex 32) \
  --from-literal=APGAR_ADMIN_TOKEN=$(openssl rand -hex 16) \
  --from-literal=APGAR_CLICKHOUSE_PASSWORD=$(openssl rand -hex 16)
helm install apgar oci://ghcr.io/oimo-ai/charts/apgar -n apgar \
  --set existingSecret=apgar --set publicUrl=https://apgar.example.com
```

[Kubernetes](https://docs.useapgar.dev/self-hosting/kubernetes) covers ingress, external ClickHouse, and upgrades.

## Use with a coding agent

Give Claude Code, Cursor, Codex, or another coding agent the Apgar skill before it sets up an integration:

```bash
npx skills add https://docs.useapgar.dev
```

Then copy and paste this prompt to the agent:

```text
Use the Apgar skill. Look at this codebase and tell me what has to change so that every release of this agent can be compared in Apgar: the traces, the release attribute, and anything the instrumentation leaves out. Do not change code until I agree.
```

[Use with AI agents](https://docs.useapgar.dev/ai-agents) also covers the docs MCP server.

## Upgrade

Every release attaches a `docker-compose.yml` that pins its images. Read the release notes and back up the ClickHouse volume, then replace the Compose file and start the new version:

```bash
curl -fsSLO https://github.com/oimo-ai/apgar/releases/latest/download/docker-compose.yml
docker compose pull
docker compose up -d --wait
```

On Kubernetes, `helm upgrade` applies the migrations before the new API starts.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
