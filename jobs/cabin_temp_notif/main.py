import datetime
import os
import sys

import requests

import jobs_common


MONITORED_CITY_LATITUDE = "33.99755743650663"
MONITORED_CITY_LONGITUDE = "-96.72286077920174"
TEMPERATURE_THRESHOLD = 34


def get_monitored_temperature(one_week_from_today):
    url = f"https://api.openweathermap.org/data/3.0/onecall/day_summary?lat={MONITORED_CITY_LATITUDE}&lon={MONITORED_CITY_LONGITUDE}&date={one_week_from_today}&units=imperial&appid={os.getenv('OPEN_WEATHER_API_TOKEN')}"
    response = requests.get(url)
    if response.status_code > 299:
        print(response.text)
        return None
    return response.json()["temperature"]["min"]


def send_discord_notification(next_week_min_temp, next_week_date):
    jobs_common.send_discord_notification(
        f"WARNING: Temperature at the cabin will be {next_week_min_temp} on {next_week_date}.",
    )


def main():
    # Validate required environment variables
    if not os.getenv("OPEN_WEATHER_API_TOKEN"):
        print("Error: OPEN_WEATHER_API_TOKEN environment variable is required")
        sys.exit(1)

    one_week_from_today = (
        datetime.datetime.now() + datetime.timedelta(days=7)
    ).strftime("%Y-%m-%d")

    next_week_min_temp = get_monitored_temperature(one_week_from_today)
    if next_week_min_temp is None:
        sys.exit(1)

    if next_week_min_temp <= TEMPERATURE_THRESHOLD:
        send_discord_notification(next_week_min_temp, one_week_from_today)


if __name__ == "__main__":
    main()
