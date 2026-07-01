# Stage 1: Build dependencies
FROM python:3.10-slim AS builder

WORKDIR /app

# Install build dependencies if needed (e.g. gcc, build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install requirements to user directory
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Final lightweight image
FROM python:3.10-slim AS runner

WORKDIR /app

# Copy user installed python packages from builder stage
COPY --from=builder /root/.local /root/.local

# Ensure packages installed to user directory are accessible on PATH
ENV PATH=/root/.local/bin:$PATH

# Copy codebase
COPY . .

# NOTE: Playwright browser binaries are EXPLICITLY excluded from this Docker image
# to keep the footprint lightweight. If browser automation is required at runtime,
# run: `playwright install chromium` inside the container or update the Dockerfile.

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
