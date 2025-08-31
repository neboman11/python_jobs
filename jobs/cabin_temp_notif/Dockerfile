FROM python:3.12-slim

WORKDIR /app

# Copy the common package first
COPY common/ common

# Copy and install service package
RUN mkdir jobs
COPY jobs/cabin_temp_notif/ jobs/cabin_temp_notif
RUN uv pip install --system --no-cache jobs/cabin_temp_notif
RUN uv pip install --no-cache .

CMD ["python", "main.py"]
