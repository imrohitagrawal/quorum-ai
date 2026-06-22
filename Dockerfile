# Multi-stage Dockerfile for Quorum-AI
# Stage 1: Build dependencies in a clean venv
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app

# Copy only the dependency manifest first to leverage layer caching.
# This layer is invalidated only when pyproject.toml or uv.lock changes.
COPY pyproject.toml uv.lock ./
RUN uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python --no-cache .

# Copy the application source
COPY src ./src

# Stage 2: Runtime image - minimal, non-root, production-ready
FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Tell uv where the venv lives (matches builder stage)
    UV_SYSTEM_PYTHON=1 \
    # Make the in-container Python importable from /app/src.
    # The source tree is copied to /app/src in the builder stage.
    # Without this, uvicorn fails with ModuleNotFoundError: No module named 'product_app'.
    PYTHONPATH="/app/src"

WORKDIR /app

# Copy the prebuilt venv from the builder
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src ./src

# Create a non-root user and chown the app directory.
# Running as root inside a container is a security anti-pattern.
RUN useradd --create-home --shell /bin/bash --uid 1000 quorum \
    && chown -R quorum:quorum /app

USER quorum
EXPOSE 8000

# Production uvicorn settings:
# - 4 workers (single instance, but each handles requests in parallel)
# - bind to 0.0.0.0 so Fly's proxy can reach it
# - proxy headers enabled so we get the real client IP from Fly's edge
# - timeout 60s (queries can take that long for synthesis)
# - graceful shutdown on SIGTERM (Fly's default kill signal)
CMD ["uvicorn", "product_app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--timeout-keep-alive", "30", \
     "--timeout-graceful-shutdown", "30"]
