import os
import requests


def send_discord_notification(message: str):
    try:
        url = f"{os.getenv("PONYBOY_BASE_URL")}/send_discord_message"
        request = {
            "user_id": int(os.getenv("NOTIFY_DISCORD_USER")),
            "message": message,
        }
        response = requests.post(url, json=request)
        if not response.ok:
            print(f"Failure sending Discord message: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Failure sending Discord message: {e}")
