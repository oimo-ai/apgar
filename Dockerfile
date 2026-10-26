FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY apgar ./apgar
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

RUN groupadd --gid 10001 apgar \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin apgar
WORKDIR /app
COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv
COPY --from=builder --chown=10001:10001 /app/apgar /app/apgar
ENV PATH="/app/.venv/bin:$PATH"
# A numeric user lets Kubernetes verify runAsNonRoot.
USER 10001:10001
ENTRYPOINT ["apgar"]
CMD ["api"]
