import os
import re
import logging
import requests
from natsort import natsorted
from notifications import send_notification
from retry_session import RetrySession


def check_for_image_update(deployment_file: dict):
    containers = deployment_file["spec"]["template"]["spec"]["containers"]
    for container in containers:
        image_name, current_tag = parse_image(container["image"])
        new_tag = get_latest_image_tag(image_name)
        if new_tag is None:
            return None
        if new_tag != current_tag:
            logging.info(
                "Found new tag for image %s: %s -> %s", image_name, current_tag, new_tag
            )
            container["image"] = f"{image_name}:{new_tag}"
            return {
                "deployment_file": deployment_file,
                "image_name": image_name,
                "current_tag": current_tag,
                "new_tag": new_tag,
            }


def parse_image(image: str):
    if "/" not in image:
        image = f"docker.io/{image}"
    image_name, tag = image.rsplit(":", 1)
    return image_name, tag


def detect_registry_and_normalize(image_name: str):
    registry = "docker.io"
    parts = image_name.split("/")
    if len(parts) > 1 and "." in parts[0]:
        registry = parts[0]
        image_name = "/".join(parts[1:])
    else:
        image_name = "/".join(parts)
    if (
        registry == "docker.io"
        and not image_name.startswith("library/")
        and len(image_name.split("/")) == 1
    ):
        image_name = f"library/{image_name}"
    return registry, image_name


def fetch_docker_tags(image_name: str):
    url = f"https://hub.docker.com/v2/repositories/{image_name}/tags/"
    try:
        session = RetrySession()
        response = session.get(url)
        response.raise_for_status()
        tags = [tag["name"] for tag in response.json().get("results", [])]
        return tags
    except requests.RequestException as e:
        error_message = (
            f"Error pulling latest image tag from Docker for {image_name}: {e}"
        )
        logging.error(error_message)
        send_notification(error_message)
        return None


def fetch_ghcr_tags(image_name: str):
    token = os.getenv("GHCR_TOKEN")
    if image_name.startswith("ghcr.io/"):
        image_name = image_name[len("ghcr.io/") :]
    image_user = image_name.split("/")[0]
    image_repo = image_name[len(image_user) + 1 :].replace("/", "%2F")
    tags = []
    page_num = 1
    try:
        while True:
            url = f"https://api.github.com/users/{image_user}/packages/container/{image_repo}/versions?page={page_num}"
            session = RetrySession()
            response = session.get(url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
            packages = response.json()
            if not packages:
                break
            for package in packages:
                tags.extend(package["metadata"]["container"]["tags"])
            page_num += 1
        return tags
    except requests.RequestException as e:
        error_message = (
            f"Error pulling latest image tag from GHCR for {image_name}: {e}"
        )
        logging.error(error_message)
        send_notification(error_message)
        return None


def fetch_quay_tags(image_name: str):
    if image_name.startswith("quay.io/"):
        image_name = image_name[len("quay.io/") :]
    url = f"https://quay.io/api/v1/repository/{image_name}/tag/"
    try:
        session = RetrySession()
        response = session.get(url)
        response.raise_for_status()
        tags = response.json().get("tags", [])
        return tags
    except requests.RequestException as e:
        error_message = (
            f"Error pulling latest image tag from Quay for {image_name}: {e}"
        )
        logging.error(error_message)
        send_notification(error_message)
        return None


def filter_and_sort_tags(tags):
    regex = re.compile(r"^v?\d+\.\d+\.\d+(?:\.\d+)?$")
    filtered_tags = [tag for tag in tags if regex.match(tag)]
    if not filtered_tags:
        return None
    return natsorted(filtered_tags, key=lambda x: x, reverse=True)


def get_latest_image_tag(image_name: str):
    registry, normalized_name = detect_registry_and_normalize(image_name)
    if registry == "docker.io":
        tags = fetch_docker_tags(normalized_name)
    elif registry == "ghcr.io":
        tags = fetch_ghcr_tags(normalized_name)
    elif registry == "quay.io":
        tags = fetch_quay_tags(normalized_name)
    else:
        raise ValueError(f"Unsupported registry: {registry}")
    if not tags:
        logging.warning(f"No tags found for {image_name}")
        return None
    sorted_tags = filter_and_sort_tags(tags)
    if not sorted_tags:
        logging.warning("No tags matching pattern found for %s", image_name)
        return None
    return sorted_tags[0]
