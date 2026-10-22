import os
import re
import logging
import requests
from natsort import natsorted
from notifications import send_notification
from retry_session import RetrySession
from filters import is_ignored_image


def check_for_image_update(deployment_file: dict, ignored_images: set[str]):
    containers = deployment_file["spec"]["template"]["spec"]["containers"]
    for container in containers:
        image_name, current_tag = parse_image(container["image"])
        if is_ignored_image(image_name, ignored_images):
            logging.info("Skipping ignored image %s", image_name)
            continue
        new_tag = get_latest_image_tag(image_name, current_tag)
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
    # lscr.io is a registry that mirrors Docker Hub, use Docker Hub API instead
    if registry == "lscr.io":
        registry = "docker.io"
    if (
        registry == "docker.io"
        and not image_name.startswith("library/")
        and len(image_name.split("/")) == 1
    ):
        image_name = f"library/{image_name}"
    return registry, image_name


DOCKER_TAGS_PAGE_SIZE = 100
DOCKER_TAGS_MAX_PAGES = 10


def fetch_docker_tags(image_name: str):
    url = (
        f"https://hub.docker.com/v2/repositories/{image_name}/tags/"
        f"?page_size={DOCKER_TAGS_PAGE_SIZE}"
    )
    try:
        session = RetrySession()
        tags = []
        # Docker Hub returns the most recently pushed tags first; a single page
        # can hold only one variant family (e.g. linuxserver libtorrentv1 builds).
        for _ in range(DOCKER_TAGS_MAX_PAGES):
            response = session.get(url)
            response.raise_for_status()
            payload = response.json()
            tags.extend(tag["name"] for tag in payload.get("results", []))
            url = payload.get("next")
            if not url:
                break
        return tags
    except requests.RequestException as e:
        error_message = (
            f"Error pulling latest image tag from Docker for {image_name}: {e}"
        )
        logging.error(error_message)
        send_notification(error_message)
        return None


def fetch_ghcr_tags(image_name: str):
    if image_name.startswith("ghcr.io/"):
        image_name = image_name[len("ghcr.io/") :]

    token = os.getenv("GHCR_TOKEN")
    image_user = image_name.split("/")[0]
    image_repo = image_name[len(image_user) + 1 :].replace("/", "%2F")
    url = (
        f"https://api.github.com/users/{image_user}/packages/container/"
        f"{image_repo}/versions?per_page=100"
    )

    try:
        session = RetrySession()
        response = session.get(url, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()

        tags = []
        for package in response.json():
            tags.extend(package["metadata"]["container"]["tags"])
        return tags
    except requests.RequestException as error:
        error_message = f"Error pulling latest image tag GHCR {image_name}: {error}"
        logging.error(error_message)
        send_notification(error_message)
        return None

def fetch_quay_tags(image_name: str):
    if image_name.startswith("quay.io/"):
        image_name = image_name[len("quay.io/") :]
    url = (
        f"https://quay.io/api/v1/repository/{image_name}/tag/"
        "?onlyActiveTags=true&limit=100"
    )
    try:
        session = RetrySession()
        response = session.get(url)
        response.raise_for_status()
        tags = [tag["name"] for tag in response.json().get("tags", [])]
        return tags
    except requests.RequestException as e:
        error_message = (
            f"Error pulling latest image tag from Quay for {image_name}: {e}"
        )
        logging.error(error_message)
        send_notification(error_message)
        return None

PRE_RELEASE_KEYWORDS = ("rc", "alpha", "beta")
ARCHITECTURE_SUFFIXES = {
    "amd64": ("-amd64", "-x86_64", "-x86-64"),
    "386": ("-386", "-i386", "-i686"),
    "arm64": ("-arm64", "-arm64v8", "-aarch64"),
    "armv7": ("-armv7", "-armhf", "-arm32v7"),
    "armv6": ("-armv6", "-armel", "-arm32v6"),
    "ppc64le": ("-ppc64le",),
    "riscv64": ("-riscv64",),
    "s390x": ("-s390x",),
}


def tag_architecture(tag: str):
    """Return the architecture named by a tag's suffix, or None for multi-arch tags."""
    tag_lower = tag.lower()
    for arch, suffixes in ARCHITECTURE_SUFFIXES.items():
        if tag_lower.endswith(suffixes):
            return arch
    return None


SEMVER_REGEX = re.compile(r"v?\d+\.\d+\.\d+(?:\.\d+)?")


def tag_variant(tag: str):
    """Return the non-version shape of a tag: text before the first version
    plus the text after it with versions, numeric build fields and LS builds normalised.

    `version-5.3.0_v2.1.2` becomes ("version-", "_#"); numeric flavour
    identifiers such as `-libtorrentv1` remain distinct from `-libtorrentv2`,
    so different build flavours of one image never replace each other.
    """
    match = SEMVER_REGEX.search(tag)
    if not match:
        return None
    suffix = tag[match.end():]
    arch = tag_architecture(tag)
    if arch:
        for arch_suffix in ARCHITECTURE_SUFFIXES[arch]:
            if suffix.lower().endswith(arch_suffix):
                suffix = suffix[: -len(arch_suffix)]
                break
    suffix = SEMVER_REGEX.sub("#", suffix)
    suffix = re.sub(r"(?<=-ls)\d+", "#", suffix)
    suffix = re.sub(r"(?<![A-Za-z0-9])\d+(?![A-Za-z0-9])", "#", suffix)
    return tag[: match.start()], suffix


def filter_and_sort_tags(tags, architecture=None, current_tag=None):
    # Match semantic version anywhere in tag (e.g., v1.2.3, release-v1.2.3, 1.2.3-build)
    # Also allow optional build metadata with + or -
    regex = SEMVER_REGEX
    current_variant = tag_variant(current_tag) if current_tag else None
    filtered_tags = []
    for tag in tags:
        # Check if tag contains a semver pattern
        if not regex.search(tag):
            logging.debug(f"Tag {tag} rejected: no semver pattern")
            continue
        # Filter out pre-release versions
        if any(kw in tag.lower() for kw in PRE_RELEASE_KEYWORDS):
            logging.debug(f"Tag {tag} rejected: prerelease keyword")
            continue
        # Also exclude "latest", "main", "develop" and other unstable tags
        if any(unstable in tag.lower() for unstable in ("latest", "main", "develop", "master", "nightly", "snapshot", "dev")):
            logging.debug(f"Tag {tag} rejected: unstable keyword")
            continue
        # Keep the architecture variant of the current tag; untagged means multi-arch only
        if tag_architecture(tag) != architecture:
            logging.debug(f"Tag {tag} rejected: architecture differs from {architecture}")
            continue
        # Keep the build flavour of the current tag (prefix/suffix around the version)
        if current_variant is not None and tag_variant(tag) != current_variant:
            logging.debug(f"Tag {tag} rejected: variant differs from {current_tag}")
            continue
        logging.debug(f"Tag {tag} accepted")
        filtered_tags.append(tag)

    if not filtered_tags:
        return None
    return natsorted(filtered_tags, key=lambda x: x, reverse=True)


def fetch_immich_tags_from_github():
    """Fetch immich tags from GitHub releases API instead of ghcr.io"""
    token = os.getenv("GITHUB_PAT")
    url = "https://api.github.com/repos/immich-app/immich/releases"
    try:
        session = RetrySession()
        headers = {"Authorization": f"token {token}"} if token else {}
        response = session.get(url, headers=headers)
        response.raise_for_status()
        releases = response.json()
        logging.debug(f"GitHub API returned {len(releases)} releases")
        tags = [r["tag_name"] for r in releases if not r.get("prerelease", False)]
        logging.debug(f"After prerelease filter: {tags}")
        return tags
    except requests.RequestException as e:
        error_message = f"Error fetching immich tags from GitHub: {e}"
        logging.error(error_message)
        send_notification(error_message)
        return None


def get_latest_image_tag(image_name: str, current_tag: str | None = None):
    # Special case: immich uses GitHub releases, not ghcr.io tags
    if "immich-app/immich-server" in image_name:
        tags = fetch_immich_tags_from_github()
    else:
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
    sorted_tags = filter_and_sort_tags(
        tags,
        tag_architecture(current_tag) if current_tag else None,
        current_tag,
    )
    if not sorted_tags:
        logging.warning("No tags matching pattern found for %s", image_name)
        return None
    newest = sorted_tags[0]
    if current_tag and natsorted([current_tag, newest], reverse=True)[0] == current_tag:
        return current_tag
    return newest
