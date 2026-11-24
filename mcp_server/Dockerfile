# syntax=docker/dockerfile:1
FROM python:3.11-slim
# Same pinned uv as harvey_api, so builds resolve the same way every time.
COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies come from uv.lock, never from the latest releases on PyPI.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

COPY src ./src
RUN uv sync --frozen --no-editable

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8085

CMD ["python", "-m", "pricing_mcp.mcp_server"]
