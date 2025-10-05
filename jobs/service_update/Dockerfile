FROM python:3.14.0rc2-alpine3.22

WORKDIR /app

RUN pip install --no-cache-dir uv

# Copy the common package first
COPY common/ common

# Copy and install service package
RUN mkdir jobs
COPY jobs/service_update/ jobs/service_update
RUN uv pip install --system --no-cache jobs/service_update

# Default to non-dry-run mode
ENV DRY_RUN="false"

CMD ["python", "jobs/service_update/main.py"]
