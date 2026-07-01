FROM python:3.14-slim@sha256:8e4071294d046d45b31a902e02a8560a45c351898513b66ec659ca39fd30d170

WORKDIR /app

RUN pip install --no-cache-dir uv

# Copy the common package first
COPY common/ common

# Copy and install service package
RUN mkdir jobs
COPY jobs/cabin_temp_notif/ jobs/cabin_temp_notif
RUN uv pip install --system --no-cache jobs/cabin_temp_notif

CMD ["python", "jobs/cabin_temp_notif/main.py"]
