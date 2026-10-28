#!/usr/bin/env bash
# Installs the chart on the current Kubernetes context, upgrades it, and runs
# `helm test` after each step. Expects apgar:dev and apgar-ui:dev on the nodes,
# for example loaded with `kind load docker-image`.
set -Eeuo pipefail

NAMESPACE="${NAMESPACE:-apgar-smoke}"
CHART="$(git rev-parse --show-toplevel)/deploy/helm/apgar"

# Prints the state of the release when a step fails, so a CI log shows the cause.
diagnose() {
  trap - ERR
  kubectl -n "${NAMESPACE}" get pods -o wide || true
  kubectl -n "${NAMESPACE}" get events --sort-by=.lastTimestamp | tail -n 30 || true
  for pod in $(kubectl -n "${NAMESPACE}" get pods -o name); do
    kubectl -n "${NAMESPACE}" logs "${pod}" --all-containers --prefix --tail=40 || true
  done
}
trap diagnose ERR

kubectl create namespace "${NAMESPACE}"
kubectl label namespace "${NAMESPACE}" pod-security.kubernetes.io/enforce=restricted
kubectl -n "${NAMESPACE}" create secret generic apgar \
  --from-literal=APGAR_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
  --from-literal=APGAR_ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(24))')" \
  --from-literal=APGAR_CLICKHOUSE_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"

# CI runners have two CPUs, fewer than the default requests of the chart need.
release() {
  helm "$1" apgar "${CHART}" -n "${NAMESPACE}" \
    --set api.resources.requests.cpu=100m \
    --set worker.resources.requests.cpu=100m \
    --set clickhouse.resources.requests.cpu=100m \
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

# A worker that never becomes ready must not block the upgrade that corrects its values.
# The memory limit kills the migrate init container, so the worker never gets ready.
helm upgrade apgar "${CHART}" -n "${NAMESPACE}" --reuse-values \
  --set worker.resources.requests.memory=24Mi --set worker.resources.limits.memory=24Mi
for _ in $(seq 1 60); do
  update="$(kubectl -n "${NAMESPACE}" get statefulset apgar-worker -o jsonpath='{.status.updateRevision}')"
  worker="$(kubectl -n "${NAMESPACE}" get pod apgar-worker-0 \
    -o jsonpath='{.metadata.labels.controller-revision-hash} {.status.conditions[?(@.type=="Ready")].status}' \
    2>/dev/null || true)"
  [[ "${worker}" == "${update} False" ]] && break
  sleep 2
done
if [[ "${worker}" != "${update} False" ]]; then
  echo "the broken worker did not start: ${worker}" >&2
  exit 1
fi
release upgrade
helm test apgar -n "${NAMESPACE}"

restarts="$(kubectl -n "${NAMESPACE}" get pods -o jsonpath='{range .items[*]}{range .status.containerStatuses[*]}{.restartCount}{"\n"}{end}{end}' | sort -n | tail -1)"
kubectl -n "${NAMESPACE}" get pods
if [[ "${restarts}" != "0" ]]; then
  echo "a container restarted" >&2
  exit 1
fi
echo "chart smoke ok"
