FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev extras needed in containers)
RUN uv sync --frozen --no-dev

# Copy application code
COPY app/ app/
COPY workers/ workers/

# Activate the virtualenv uv created
ENV PATH="/app/.venv/bin:$PATH"
