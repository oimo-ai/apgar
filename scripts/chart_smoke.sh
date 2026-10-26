#!/usr/bin/env bash
# Installs the chart on the current Kubernetes context, upgrades it, and runs
# `helm test` after each step. Expects apgar:dev and apgar-ui:dev on the nodes,
# for example loaded with `kind load docker-image`.
set -euo pipefail

NAMESPACE="${NAMESPACE:-apgar-smoke}"
CHART="$(git rev-parse --show-toplevel)/deploy/helm/apgar"

kubectl create namespace "${NAMESPACE}"
kubectl label namespace "${NAMESPACE}" pod-security.kubernetes.io/enforce=restricted
kubectl -n "${NAMESPACE}" create secret generic apgar \
  --from-literal=APGAR_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
  --from-literal=APGAR_ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(24))')" \
  --from-literal=APGAR_CLICKHOUSE_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"

release() {
  helm "$1" apgar "${CHART}" -n "${NAMESPACE}" \
    --set existingSecret=apgar \
    --set publicUrl=http://localhost:8080 \
    --set image.repository=apgar --set image.tag=dev --set image.pullPolicy=Never \
    --set uiImage.repository=apgar-ui --set uiImage.tag=dev --set uiImage.pullPolicy=Never \
    --set clickhouse.persistence.size=1Gi \
    --set env.APGAR_TELEMETRY=0 \
    "${@:2}" --wait --timeout 8m
}

# A first install must work on an empty cluster: migrations run before any schema exists.
release install
helm test apgar -n "${NAMESPACE}"

# An upgrade replaces the worker. A new worker must not wait on the old heartbeat.
release upgrade --set worker.podAnnotations.smoke=upgrade
helm test apgar -n "${NAMESPACE}"

restarts="$(kubectl -n "${NAMESPACE}" get pods -o jsonpath='{range .items[*]}{range .status.containerStatuses[*]}{.restartCount}{"\n"}{end}{end}' | sort -n | tail -1)"
kubectl -n "${NAMESPACE}" get pods
if [[ "${restarts}" != "0" ]]; then
  echo "a container restarted" >&2
  exit 1
fi
echo "chart smoke ok"
