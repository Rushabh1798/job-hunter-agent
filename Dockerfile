# Stage 1: builder — install dependencies and project
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ libffi-dev git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first for layer caching
COPY pyproject.toml uv.lock .python-version ./

# Install dependencies only (cached unless manifests change)
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project itself
COPY src/ src/
RUN uv sync --frozen --no-dev


# Stage 2: runtime — minimal image with only what's needed
FROM python:3.12-slim AS runtime

# Playwright Chromium runtime dependencies + curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    libenchant-2-2 \
    libsecret-1-0 \
    libmanette-0.2-0 \
    libgles2 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -g 1000 appuser && useradd -m -u 1000 -g appuser appuser

WORKDIR /app

# Copy virtual env, source, and config from builder
COPY --from=builder /app/.venv .venv/
COPY --from=builder /app/src src/
COPY --from=builder /app/pyproject.toml pyproject.toml

ENV PATH="/app/.venv/bin:$PATH"

# Install Playwright Chromium to a shared location accessible by appuser
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.browsers
RUN playwright install chromium \
    && chown -R appuser:appuser /app/.browsers

# Create output directories and set ownership
RUN mkdir -p /app/output/checkpoints && chown -R appuser:appuser /app/output

# Switch to non-root user
USER appuser

# Runtime configuration
ENV JH_OUTPUT_DIR=/app/output
ENV JH_CHECKPOINT_DIR=/app/output/checkpoints

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "from job_hunter_cli.main import app; print('ok')" || exit 1

ENTRYPOINT ["job-hunter"]
CMD ["--help"]
