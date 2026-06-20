FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
COPY pyproject.toml ./
RUN uv venv /opt/venv && uv pip install --python /opt/venv/bin/python -e .
COPY . .

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH"     PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY src ./src
# Create a non-root user and chown the app directory so the
# process does not run as root inside the container.
RUN useradd --create-home --shell /bin/bash --uid 1000 quorum \
    && chown -R quorum:quorum /app
USER quorum
EXPOSE 8000
CMD ["uvicorn", "product_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
