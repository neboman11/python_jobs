import logging
import os

from notifications import send_notification
from retry_session import RetrySession

CONFIG_SERVICE_URL = os.getenv(
    "CONFIG_SERVICE_URL",
    "http://configuration-setting-service.application.svc.cluster.local:8080",
)


def get_setting(section: str, name: str) -> str | None:
    url = f"{CONFIG_SERVICE_URL}/configuration_setting/{section}/{name}"
    try:
        session = RetrySession()
        response = session.get(url)
        response.raise_for_status()
        return response.json()["value"]
    except Exception as e:
        error_message = f"Error fetching config setting {section}/{name}: {e}"
        logging.error(error_message)
        send_notification(error_message)
        return None


def get_ignored_images() -> set[str]:
    value = get_setting("service_update", "ignored_images")
    if not value:
        return set()
    return {img.strip() for img in value.split(",") if img.strip()}
