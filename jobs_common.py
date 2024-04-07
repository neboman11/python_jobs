import os
import requests


def send_discord_notification(message: str):
    url = f"{os.getenv("PONYBOY_BASE_URL")}/send_discord_message"
    request = {
        "user_id": int(os.getenv("NOTIFY_DISCORD_USER")),
        "message": message,
    }
    response = requests.post(url, json=request)
    if response.status_code > 299:
        print(response.text)
