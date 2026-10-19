FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY apgar ./apgar
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin apgar
WORKDIR /app
COPY --from=builder --chown=apgar:apgar /app/.venv /app/.venv
COPY --from=builder --chown=apgar:apgar /app/apgar /app/apgar
ENV PATH="/app/.venv/bin:$PATH"
USER apgar
ENTRYPOINT ["apgar"]
CMD ["api"]
