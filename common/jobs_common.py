import os
import requests


def send_discord_notification(message: str):
    try:
        user_id = os.getenv("NOTIFY_DISCORD_USER")
        base_url = os.getenv("PONYBOY_BASE_URL")
        if not user_id or not base_url:
            print("Missing required environment variables for Discord notification")
            return

        url = f"{base_url}/send_discord_message"
        request = {
            "user_id": int(user_id),
            "message": message,
        }
        response = requests.post(url, json=request)
        if not response.ok:
            print(
                f"Failure sending Discord message: {response.status_code} - {response.text}"
            )
    except Exception as e:
        print(f"Failure sending Discord message: {e}")
