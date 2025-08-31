FROM python:3.12-slim

WORKDIR /app

# Copy and install common package first
COPY common /app/common
RUN pip install --no-cache-dir uv
RUN cd /app/common && uv pip install --no-cache .

# Copy and install service package
COPY jobs/service_update/pyproject.toml .
COPY jobs/service_update/main.py .
RUN uv pip install --no-cache .

# Set environment variables (these will be overridden by k8s)
ENV GITHUB_PAT=""
ENV GHCR_TOKEN=""
ENV PONYBOY_BASE_URL=""
ENV NOTIFY_DISCORD_USER=""

# Default to non-dry-run mode
ENV DRY_RUN="false"

CMD ["python", "main.py"]
