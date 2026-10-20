.PHONY: sync lint format typecheck test-unit test-integration test test-coverage ch-test-up ch-test-down docker-build up down ci ui-install ui-lint ui-typecheck ui-test ui-test-coverage ui-build e2e licenses version

COMPOSE_DEV = docker compose -f docker-compose.yml -f docker-compose.dev.yml

sync:
	uv sync --all-extras

lint:
	uv run ruff check . && uv run ruff format --check .

format:
	uv run ruff format . && uv run ruff check --fix .

typecheck:
	uv run mypy apgar tests

test-unit:
	uv run pytest tests/unit -q

test-integration:
	uv run pytest tests/integration -q -m integration

test: test-unit test-integration

test-coverage:
	APGAR_TEST_REQUIRE_CLICKHOUSE=1 uv run pytest tests/unit tests/integration -q --cov=apgar --cov-report=term-missing --cov-fail-under=90

ch-test-up:
	docker compose -f docker-compose.test.yml up -d --wait

ch-test-down:
	docker compose -f docker-compose.test.yml down -v

docker-build:
	docker build -t apgar:dev .
	docker build -t apgar-ui:dev -f ui/Dockerfile .

ui-install:
	npm ci --prefix ui

ui-lint:
	npm run lint --prefix ui && npm run lint:colors --prefix ui

ui-typecheck:
	npm run typecheck --prefix ui

ui-test:
	npm run test --prefix ui -- --run

ui-test-coverage:
	npm run test --prefix ui -- --run --coverage --coverage.thresholds.statements=95

ui-build:
	npm run build --prefix ui

e2e:
	APGAR_ALLOW_INSECURE_SLACK=1 $(MAKE) up
	set -a; . ./.env; set +a; npm run e2e --prefix ui

up:
	$(COMPOSE_DEV) up -d --build --wait

down:
	$(COMPOSE_DEV) down -v

ci:
	APGAR_TEST_REQUIRE_CLICKHOUSE=1 $(MAKE) lint typecheck ch-test-up test-coverage docker-build ui-install ui-lint ui-typecheck ui-test-coverage ui-build licenses

version:
	@test -n "$(VERSION)" || { echo "usage: make version VERSION=X.Y.Z" >&2; exit 2; }
	uv run python scripts/release_version.py set $(VERSION)

licenses:
	uv run python scripts/check_licenses.py
