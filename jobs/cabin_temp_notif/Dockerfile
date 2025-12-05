FROM python:3.14.1-alpine3.22

WORKDIR /app

RUN pip install --no-cache-dir uv

# Copy the common package first
COPY common/ common

# Copy and install service package
RUN mkdir jobs
COPY jobs/cabin_temp_notif/ jobs/cabin_temp_notif
RUN uv pip install --system --no-cache jobs/cabin_temp_notif

CMD ["python", "jobs/cabin_temp_notif/main.py"]
