#!/usr/bin/env bash
# Fresh-clone smoke test. Reaches a FAIL verdict on demo data and, when Node
# is installed, runs the Playwright smoke.
set -euo pipefail

REPO="${1:-$(git rev-parse --show-toplevel)}"
WORK="$(mktemp -d)"
START="$(date +%s)"

cleanup() {
  local status=$?
  if [[ -d "${WORK}/apgar" ]]; then
    (cd "${WORK}/apgar" && docker compose down -v) || true
  fi
  rm -rf "${WORK}"
  exit "${status}"
}
trap cleanup EXIT

python3 - <<'PY'
import socket
import sys

for port in (8000, 8080):
    probe = socket.socket()
    probe.settimeout(0.5)
    try:
        busy = probe.connect_ex(("127.0.0.1", port)) == 0
    finally:
        probe.close()
    if busy:
        print(f"port {port} is in use", file=sys.stderr)
        sys.exit(1)
PY

git clone --quiet "${REPO}" "${WORK}/apgar"
cd "${WORK}/apgar"
export COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml

SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
ADMIN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
CLICKHOUSE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(16))')"
cat > .env <<EOF
APGAR_SECRET_KEY=${SECRET}
APGAR_ADMIN_TOKEN=${ADMIN}
CLICKHOUSE_PASSWORD=${CLICKHOUSE}
APGAR_TELEMETRY=0
APGAR_PUBLIC_URL=http://localhost:8080
EOF

export SMOKE_START="${START}"
python3 - <<'PY'
import subprocess
import sys

try:
    subprocess.run(
        ["docker", "compose", "up", "-d", "--build", "--wait"],
        check=True,
        timeout=480,
    )
except subprocess.TimeoutExpired:
    print("docker compose up exceeded 480 s", file=sys.stderr)
    sys.exit(1)
PY

docker compose run --rm apgar-worker demo seed --days 14 --turns-per-day 300

export APGAR_ADMIN_TOKEN="${ADMIN}"
python3 - <<'PY'
import json
import os
import sys
import time
import urllib.error
import urllib.request

token = os.environ["APGAR_ADMIN_TOKEN"]
deadline = int(os.environ["SMOKE_START"]) + 600
url = "http://localhost:8000/api/v1/agents/billing-copilot/releases/fp-8e2f0c6a1b93"
while time.time() < deadline:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        time.sleep(5)
        continue
    if isinstance(body, dict) and body.get("state") == "FAIL":
        sys.exit(0)
    time.sleep(5)
print("verdict did not reach FAIL within 600 s of start", file=sys.stderr)
sys.exit(1)
PY

if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  (
    cd ui
    npm ci
    npx playwright install chromium
    APGAR_ADMIN_TOKEN="${ADMIN}" APGAR_SMOKE=1 npx playwright test --project smoke
  )
  echo "playwright smoke passed"
else
  echo "warning: Node is not available; skipping Playwright smoke"
fi

elapsed="$(( $(date +%s) - START ))"
echo "smoke ok in ${elapsed} s"
if (( elapsed > 600 )); then
  echo "smoke exceeded 600 s" >&2
  exit 1
fi
