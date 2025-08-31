import datetime
import os
import sys
import logging

import requests

import jobs_common


MONITORED_CITY_LATITUDE = "33.99755743650663"
MONITORED_CITY_LONGITUDE = "-96.72286077920174"
TEMPERATURE_THRESHOLD = 34


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


def get_monitored_temperature(one_week_from_today):
    url = (
        f"https://api.openweathermap.org/data/3.0/onecall/day_summary"
        f"?lat={MONITORED_CITY_LATITUDE}&lon={MONITORED_CITY_LONGITUDE}"
        f"&date={one_week_from_today}&units=imperial"
        f"&appid={os.getenv('OPEN_WEATHER_API_TOKEN')}"
    )

    logging.debug(f"Requesting weather data from: {url}")

    response = requests.get(url)
    if response.status_code > 299:
        logging.error(
            f"Failed to fetch weather data. Status: {response.status_code}, Response: {response.text}"
        )
        return None

    data = response.json()
    logging.debug(f"Received data: {data}")

    try:
        min_temp = data["temperature"]["min"]
        logging.info(f"Minimum temperature on {one_week_from_today}: {min_temp}°F")
        return min_temp
    except KeyError as e:
        logging.error(f"Unexpected response structure: {e}, data={data}")
        return None


def send_notification(next_week_min_temp, next_week_date):
    logging.warning(
        f"Temperature alert triggered. Temp={next_week_min_temp}, Date={next_week_date}"
    )
    jobs_common.send_notification(
        f"WARNING: Temperature at the cabin will be {next_week_min_temp} on {next_week_date}."
    )
    logging.info("Notification sent successfully.")


def main():
    logging.info("Starting temperature monitoring job.")

    # Validate required environment variables
    if not os.getenv("OPEN_WEATHER_API_TOKEN"):
        logging.critical("OPEN_WEATHER_API_TOKEN environment variable is required.")
        sys.exit(1)

    one_week_from_today = (
        datetime.datetime.now() + datetime.timedelta(days=7)
    ).strftime("%Y-%m-%d")
    logging.info(f"Checking temperature forecast for {one_week_from_today}.")

    next_week_min_temp = get_monitored_temperature(one_week_from_today)
    if next_week_min_temp is None:
        logging.error("No temperature data available, exiting.")
        sys.exit(1)

    if next_week_min_temp <= TEMPERATURE_THRESHOLD:
        send_notification(next_week_min_temp, one_week_from_today)
    else:
        logging.info(
            f"No alert: Minimum temperature {next_week_min_temp}°F is above threshold {TEMPERATURE_THRESHOLD}°F."
        )

    logging.info("Job completed.")


if __name__ == "__main__":
    main()
