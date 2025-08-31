FROM python:3.12-slim

WORKDIR /app

# Copy and install common package first
COPY common /app/common
RUN pip install --no-cache-dir uv
RUN cd /app/common && uv pip install --no-cache .

# Copy and install service package
COPY jobs/cabin_temp_notif/pyproject.toml .
COPY jobs/cabin_temp_notif/main.py .
RUN uv pip install --no-cache .

# Set environment variables (these will be overridden by k8s)
ENV OPEN_WEATHER_API_TOKEN=""
ENV PONYBOY_BASE_URL=""
ENV NOTIFY_DISCORD_USER=""

CMD ["python", "main.py"]
