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
# Build-time SHA passthrough (deploy.yml passes --build-arg GIT_SHA=<commit>).
# Surfaced as ``build_sha`` on /status so "is the merged commit actually the
# one serving?" is a one-line curl, not an inference from an unchanged
# /health 200. Defaults to "unknown" for local builds.
ARG GIT_SHA=unknown
ENV BUILD_SHA=${GIT_SHA} \
    PATH="/opt/venv/bin:$PATH" \
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
# - 1 worker. The CMD below says "--workers", "1"; this line used to read
#   "4 workers", which was stale. It matters beyond tidiness: /status's
#   feedback_writes and feedback_lost_billed_writes are PER-PROCESS, so with more
#   than one worker a /status request samples whichever worker answered it and a
#   lost-charge signal on another worker is invisible. Raising the count means
#   moving those signals out of process memory first.
# - bind to 0.0.0.0 so Fly's proxy can reach it
# - uvicorn's own proxy handling OFF (--no-proxy-headers; its default is ON).
#   History: "*" believed X-Forwarded-For from any peer, so a client could forge
#   a fresh rate-limit bucket per request (#58, reproduced 40x200, zero 429s).
#   #58 narrowed trust to Fly's private ranges, but Fly APPENDS the app's own
#   ingress address to X-Forwarded-For and uvicorn takes the rightmost
#   untrusted entry, so every visitor was counted as the app (W30, measured in
#   production 2026-09-25). The app now reads Fly-Client-IP, which Fly's proxy
#   overwrites, only from Fly's private ranges: auth.VisitorAddressMiddleware,
#   ADR-0132, pinned by tests/security/test_trusted_proxy_ips.py.
# - timeout 60s (queries can take that long for synthesis)
# - graceful shutdown on SIGTERM (Fly's default kill signal)
CMD ["uvicorn", "product_app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--no-proxy-headers", \
     "--timeout-keep-alive", "30", \
     "--timeout-graceful-shutdown", "30"]
