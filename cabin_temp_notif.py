import datetime
import os

from dotenv import load_dotenv
import requests

import jobs_common


monitored_city_latitude = "33.99755743650663"
monitored_city_longitude = "-96.72286077920174"
temperature_threshold = 34


def get_monitored_temperature(one_week_from_today):
    global monitored_city_latitude
    global monitored_city_longitude

    url = f"https://api.openweathermap.org/data/3.0/onecall/day_summary?lat={monitored_city_latitude}&lon={monitored_city_longitude}&date={one_week_from_today}&units=imperial&appid={os.getenv('OPEN_WEATHER_API_TOKEN')}"
    response = requests.get(url)
    if response.status_code > 299:
        print(response.text)
    return response.json()["temperature"]["min"]


def send_discord_notification(next_week_min_temp, next_week_date):
    jobs_common.send_discord_notification(
        f"WARNING: Temperature at the cabin will be {next_week_min_temp} on {next_week_date}.",
    )


def main():
    global temperature_threshold

    load_dotenv()
    one_week_from_today = (
        datetime.datetime.now() + datetime.timedelta(days=7)
    ).strftime("%Y-%m-%d")
    next_week_min_temp = get_monitored_temperature(one_week_from_today)
    if next_week_min_temp <= temperature_threshold:
        send_discord_notification(next_week_min_temp, one_week_from_today)


if __name__ == "__main__":
    main()
