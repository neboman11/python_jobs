import os
import requests


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

        response = requests.post(url, headers=headers, data=message)
        if not response.ok:
            print(
                f"Failure sending ntfy message: {response.status_code} - {response.text}"
            )
    except Exception as e:
        print(f"Failure sending ntfy message: {e}")
