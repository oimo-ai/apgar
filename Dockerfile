FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY apgar ./apgar
# Kubernetes runs the image with a read-only root filesystem, where Python cannot write
# bytecode, so every start would compile each imported module again.
ENV UV_COMPILE_BYTECODE=1
RUN uv sync --frozen --no-dev \
    && .venv/bin/python -m compileall -q apgar

FROM python:3.12-slim AS runtime

# tini runs as PID 1 and forwards signals. Python as PID 1 ignores SIGTERM until it
# installs a handler, so a container stopped while it starts, or while migrate waits for
# ClickHouse, would wait for the whole grace period.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10001 apgar \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin apgar
WORKDIR /app
COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv
COPY --from=builder --chown=10001:10001 /app/apgar /app/apgar
ENV PATH="/app/.venv/bin:$PATH"
# A numeric user lets Kubernetes verify runAsNonRoot.
USER 10001:10001
ENTRYPOINT ["tini", "--", "apgar"]
CMD ["api"]
