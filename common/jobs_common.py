import os
import requests
from requests.adapters import HTTPAdapter, Retry


def send_notification(message: str):
    try:
        base_url = os.getenv("NTFY_BASE_URL")
        topic = os.getenv("NTFY_TOPIC")
        api_key = os.getenv("NTFY_API_KEY")

        if not all([base_url, topic, api_key]):
            print("Missing required environment variables for ntfy notification")
            return

        url = f"{base_url}/{topic}"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "text/plain"}

        # Configure retries
        retries = Retry(
            total=3,  # Total number of retries
            backoff_factor=2,  # Exponential backoff factor (2, 4, 8…)
            status_forcelist=[
                500,
                502,
                503,
                504,
                522,
            ],  # Retry on these HTTP status codes
            allowed_methods=["POST"],  # Retry only POST requests
        )

        session = requests.Session()
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        response = session.post(url, headers=headers, data=message)
        if not response.ok:
            print(
                f"Failed sending ntfy message: {response.status_code} - {response.text}"
            )

    except Exception as e:
        print(f"Failure sending ntfy message: {e}")
