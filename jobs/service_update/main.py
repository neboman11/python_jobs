from datetime import datetime
from enum import Enum
import io
import logging
import os
import re
import sys
from typing import Any

from github import Auth
from github import ContentFile
from github import Github
from github import Repository
import github
from natsort import natsorted
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yaml

import jobs_common

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class UpdateType(Enum):
    KustomizeChart = 0
    Image = 1
    HelmChart = 2


def main():
    # Check required environment variables
    required_vars = ["GITHUB_PAT", "GHCR_TOKEN"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        error_message = (
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )
        logger.error(error_message)
        # Send notification on premature exit
        send_notification(f"Script terminating. Reason: {error_message}")
        sys.exit(1)

    try:
        github_PAT = os.getenv("GITHUB_PAT")
        dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

        if not github_PAT:
            error_message = "GITHUB_PAT environment variable is required"
            logger.error(error_message)
            # Send notification on premature exit
            send_notification(f"Script terminating. Reason: {error_message}")
            sys.exit(1)

        auth = Auth.Token(github_PAT)
        gh = Github(auth=auth)
        argo_repo = gh.get_repo("neboman11/argocd-definitions")
        repo_contents = argo_repo.get_contents("/")

        logger.info("Finding kustomize and deployment files in repo")
        kustomize_files, deployment_files, chart_files = get_files(
            argo_repo, repo_contents
        )

        logger.info("Checking for updates")
        helm_updates = find_helm_updates(kustomize_files)
        image_updates = find_image_updates(deployment_files)
        chart_updates = find_chart_updates(chart_files)

        if not (helm_updates or image_updates or chart_updates):
            logger.info("Found no charts or images to update")
            return

        date_string = datetime.now().strftime("%Y-%m-%d")
        new_branch_name = f"service_update/{date_string}"

        handle_all_updates(
            argo_repo,
            new_branch_name,
            dry_run,
            helm_updates,
            image_updates,
            chart_updates,
        )

        if dry_run:
            logger.info("Dry run complete. No changes were committed.")

    # Catch any unhandled exception to send a final notification
    except Exception as e:
        error_message = (
            f"An unexpected error occurred, forcing the script to terminate: {e}"
        )
        logger.error(error_message, exc_info=True)
        send_notification(error_message)
        sys.exit(1)


def get_files(repo, contents):
    kustomize_files = []
    deployment_files = []
    chart_files = []
    find_kustomize_and_deployment_files(
        repo, contents, kustomize_files, deployment_files, chart_files
    )
    return kustomize_files, deployment_files, chart_files


def find_helm_updates(files):
    updates = kustomize_files_find_helm_charts_with_updates(files)
    return updates


def find_chart_updates(files):
    updates = chart_files_find_chart_updates(files)
    return updates


def find_image_updates(files):
    updates = deployment_files_find_image_updates(files)
    return updates


def handle_all_updates(
    repo, branch_name, dry_run, kustomize_charts_updates, image_updates, chart_updates
):
    if kustomize_charts_updates:
        minor_update_charts = filter_updates(
            kustomize_charts_updates, chart_updates_with_minor_or_patch_filter
        )
        if minor_update_charts:
            handle_updates(
                repo,
                branch_name,
                dry_run,
                minor_update_charts,
                UpdateType.KustomizeChart,
            )

        major_update_charts = filter_updates(
            kustomize_charts_updates,
            lambda x: not chart_updates_with_minor_or_patch_filter(x),
        )
        if major_update_charts:
            handle_updates(
                repo,
                branch_name,
                dry_run,
                major_update_charts,
                UpdateType.KustomizeChart,
                is_major=True,
            )

    if image_updates:
        minor_update_images = filter_updates(
            image_updates, image_updates_with_minor_or_patch_filter
        )
        if minor_update_images:
            handle_updates(
                repo, branch_name, dry_run, minor_update_images, UpdateType.Image
            )

        major_update_images = filter_updates(
            image_updates, lambda x: not image_updates_with_minor_or_patch_filter(x)
        )
        if major_update_images:
            handle_updates(
                repo,
                branch_name,
                dry_run,
                major_update_images,
                UpdateType.Image,
                is_major=True,
            )

    if chart_updates:
        minor_update_charts = filter_updates(
            chart_updates, chart_updates_with_minor_or_patch_filter
        )
        if minor_update_charts:
            handle_updates(
                repo, branch_name, dry_run, minor_update_charts, UpdateType.HelmChart
            )

        major_update_charts = filter_updates(
            chart_updates, lambda x: not chart_updates_with_minor_or_patch_filter(x)
        )
        if major_update_charts:
            handle_updates(
                repo,
                branch_name,
                dry_run,
                major_update_charts,
                UpdateType.HelmChart,
                is_major=True,
            )


def filter_updates(updates, filter_func):
    return list(filter(filter_func, updates))


def handle_updates(
    repo, branch_name, dry_run, update_objects, update_type: UpdateType, is_major=False
):
    if not dry_run:
        target_branch = create_branch_for_updates(repo, branch_name)
        match update_type:
            case UpdateType.KustomizeChart:
                logger.info("Committing changes to update helm charts")
            case UpdateType.Image:
                logger.info("Committing changes to update image tags")
            case UpdateType.HelmChart:
                logger.info("Committing changes to update chart dependencies")
        commit_updates_to_branch(repo, target_branch.ref, update_objects)
        pr = create_pull_request_for_updates(repo, branch_name)
        if not is_major:
            logger.info("Merging PR automatically for minor/patch update")
            pr.merge()

    notification_type = "major version bumps on" if is_major else "versions"
    match update_type:
        case UpdateType.KustomizeChart:
            send_notification(
                f"{'Created PR for' if is_major else 'Updated'} {notification_type} {', '.join([chart['release_name'] for chart in update_objects])}"
            )
        case UpdateType.Image:
            send_notification(
                f"{'Created PR for' if is_major else 'Updated'} {notification_type} {', '.join([image['image_name'] for image in update_objects])}"
            )
        case UpdateType.HelmChart:
            send_notification(
                f"{'Created PR for' if is_major else 'Updated'} {notification_type} {', '.join([chart['chart_name'] for chart in update_objects])}"
            )


def image_updates_with_minor_or_patch_filter(image_update):
    split_original_tag = image_update["current_tag"].split(".")
    split_new_tag = image_update["new_tag"].split(".")

    if len(split_original_tag) < 2 or len(split_new_tag) < 2:
        return False

    if split_original_tag[0] != split_new_tag[0]:
        return False

    return True


def send_notification(message):
    jobs_common.send_notification(message)


def create_pull_request_for_updates(argo_repo, new_branch_name: str):
    pull_request = argo_repo.create_pull(
        argo_repo.default_branch,
        new_branch_name,
        title="Automatic Helm chart version and image tag bump",
        body="",
    )
    return pull_request


def chart_updates_with_minor_or_patch_filter(helm_chart_update):
    split_original_version = helm_chart_update["original_version"].split(".")
    split_new_version = helm_chart_update["new_version"].split(".")
    if split_original_version[0] != split_new_version[0]:
        return False
    return True


def create_branch_for_updates(argo_repo: Repository.Repository, new_branch_name):
    logger.info("Creating branch to store changes in")
    main_branch = argo_repo.get_git_ref(f"heads/{argo_repo.default_branch}")
    try:
        new_branch = argo_repo.get_git_ref(f"heads/{new_branch_name}")
        logger.debug("Branch already exists: %s", new_branch_name)
    except github.GithubException:
        logger.info("Branch does not exist, creating: %s", new_branch_name)
        new_branch = argo_repo.create_git_ref(
            f"refs/heads/{new_branch_name}", main_branch.object.sha
        )

    return new_branch


def commit_updates_to_branch(
    argo_repo: Repository.Repository,
    target_branch_ref: str,
    files_needing_updates: list[dict[str, Any]],
):
    for file in files_needing_updates:
        if "kustomize_file" in file:
            file_content_stream = io.StringIO()
            yaml.dump(file["kustomize_file"], file_content_stream)
            file_content_stream.seek(0)
            file_contents = file_content_stream.getvalue()
            argo_repo.update_file(
                file["path"],
                f"Bump {file['release_name']} version to {file['new_version']}",
                file_contents,
                file["sha"],
                target_branch_ref,
            )
        elif "deployment_file" in file:
            file_content_stream = io.StringIO()
            yaml.dump(file["deployment_file"], file_content_stream)
            file_content_stream.seek(0)
            argo_repo.update_file(
                file["path"],
                f"Bump {file['image_name']} image tag to {file['new_tag']}",
                file_content_stream.getvalue(),
                file["sha"],
                target_branch_ref,
            )
        elif "chart_file" in file:
            file_content_stream = io.StringIO()
            yaml.dump(file["chart_file"], file_content_stream)
            file_content_stream.seek(0)
            argo_repo.update_file(
                file["path"],
                f"Bump {file['chart_name']} version to {file['new_version']}",
                file_content_stream.getvalue(),
                file["sha"],
                target_branch_ref,
            )
        else:
            logger.warning("Unable to add file to commit: %s", file)


def kustomize_files_find_helm_charts_with_updates(
    kustomize_files: list[ContentFile.ContentFile],
):
    files_needing_updates: list[dict[str, Any]] = []
    for kustomize_file in kustomize_files:
        file_stream = io.BytesIO(kustomize_file.decoded_content)
        try:
            parsed_file = yaml.safe_load(file_stream)
            # Check that the file contains a helm chart
            if "helmCharts" in parsed_file:
                updated_file = check_for_helm_chart_update(parsed_file)
                if updated_file != None:
                    updated_file["path"] = kustomize_file.path
                    updated_file["sha"] = kustomize_file.sha
                    files_needing_updates.append(updated_file)
        except yaml.YAMLError as ex:
            logger.warning(
                "Unable to load yaml contents of file %s: %s", kustomize_file.path, ex
            )
            send_notification(f"Yaml parsing failed for {kustomize_file.path}")
    return files_needing_updates


def chart_files_find_chart_updates(chart_files):
    files_needing_updates: list[dict[str, Any]] = []
    for chart_file in chart_files:
        file_stream = io.BytesIO(chart_file.decoded_content)
        try:
            parsed_file = yaml.safe_load(file_stream)
            updated_file = check_for_chart_update(parsed_file)
            if updated_file is not None:
                updated_file["path"] = chart_file.path
                updated_file["sha"] = chart_file.sha
                files_needing_updates.append(updated_file)
        except yaml.YAMLError as ex:
            logger.warning(
                "Unable to load yaml contents of file %s: %s", chart_file.path, ex
            )
            send_notification(f"Yaml parsing failed for {chart_file.path}")
    return files_needing_updates


def check_for_chart_update(chart_file: dict):
    dependencies = chart_file.get("dependencies", [])
    for dependency in dependencies:
        chart_name = dependency["name"]
        chart_repo = dependency["repository"]
        if not chart_repo.endswith("/"):
            chart_repo += "/"

        try:
            response = requests.get(f"{chart_repo}index.yaml")
            response.raise_for_status()  # Raise an exception for bad status codes
        except requests.exceptions.RequestException as e:
            # On failure, notify and continue to the next dependency
            error_message = f"Failed to pull chart index from {chart_repo} for {chart_name}. Error: {e}"
            logger.error(error_message)
            send_notification(error_message)
            continue

        repository_index = yaml.safe_load(io.BytesIO(response.content))

        remote_versions = [
            chart["version"]
            for chart in repository_index["entries"].get(chart_name, [])
        ]

        remote_versions = list(
            filter(
                lambda x: "dev" not in x and "alpha" not in x and "beta" not in x,
                remote_versions,
            )
        )

        remote_versions = list(natsorted(remote_versions, reverse=True))

        if remote_versions and remote_versions[0] != dependency["version"]:
            original_version = dependency["version"]
            dependency["version"] = remote_versions[0]
            return {
                "chart_file": chart_file,
                "original_version": original_version,
                "new_version": remote_versions[0],
                "chart_name": chart_name,
            }


def find_kustomize_and_deployment_files(
    argo_repo: Repository.Repository,
    repo_files: list[ContentFile.ContentFile],
    kustomize_file_list: list[ContentFile.ContentFile],
    deployment_file_list: list[ContentFile.ContentFile],
    chart_file_list: list[ContentFile.ContentFile],
):
    for file in repo_files:
        if file.type == "file" and file.name == "kustomization.yaml":
            kustomize_file_list.append(file)
        if file.type == "file" and file.name.endswith("deployment.yaml"):
            deployment_file_list.append(file)
        if file.type == "file" and file.name == "Chart.yaml":
            chart_file_list.append(file)
        if file.type == "dir" and file.name != "overlays":
            folder_contents = argo_repo.get_contents(f"/{file.path}")
            if not isinstance(folder_contents, list):
                folder_contents = [folder_contents]
            find_kustomize_and_deployment_files(
                argo_repo,
                folder_contents,
                kustomize_file_list,
                deployment_file_list,
                chart_file_list,
            )


def deployment_files_find_image_updates(
    deployment_files: list[ContentFile.ContentFile],
):
    files_needing_updates: list[dict[str, Any]] = []
    for deployment_file in deployment_files:
        file_stream = io.BytesIO(deployment_file.decoded_content)
        try:
            parsed_file = yaml.safe_load(file_stream)
            updated_file = check_for_image_update(parsed_file)
            if updated_file is not None:
                updated_file["path"] = deployment_file.path
                updated_file["sha"] = deployment_file.sha
                files_needing_updates.append(updated_file)
        except yaml.YAMLError as ex:
            logger.warning(
                "Unable to load yaml contents of file %s: %s", deployment_file.path, ex
            )
            send_notification(f"Yaml parsing failed for {deployment_file.path}")
    return files_needing_updates


def check_for_helm_chart_update(kustomize_file: dict):
    deployed_chart = kustomize_file["helmCharts"][0]
    if deployed_chart.get("namespace") == "databases":
        return

    chart_repo = deployed_chart["repo"]
    if not chart_repo.endswith("/"):
        chart_repo += "/"

    try:
        # Pull the index file containing all the available charts at the repo
        response = requests.get(f"{chart_repo}index.yaml")
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        # On failure, notify and return to continue to the next file
        error_message = f"Failed to pull chart index from {chart_repo} for {deployed_chart.get('releaseName')}. Error: {e}"
        logger.error(error_message)
        send_notification(error_message)
        return

    repository_index = yaml.safe_load(io.BytesIO(response.content))

    # Select the available chart versions from the repo
    remote_versions = [
        chart["version"]
        for chart in repository_index["entries"][deployed_chart["name"]]
    ]

    # Filter out prerelease versions
    remote_versions = list(
        filter(
            lambda x: "dev" not in x and "alpha" not in x and "beta" not in x,
            remote_versions,
        )
    )

    # Sort the versions descending so the highest version is at the beginning
    remote_versions = list(natsorted(remote_versions, reverse=True))

    if remote_versions[0] != deployed_chart["version"]:
        # Return an object containing the file object with the updated version, the old version, and the new version
        original_version = deployed_chart["version"]
        kustomize_file["helmCharts"][0]["version"] = remote_versions[0]
        return {
            "kustomize_file": kustomize_file,
            "original_version": original_version,
            "new_version": remote_versions[0],
            "release_name": deployed_chart.get("releaseName"),
        }


def check_for_image_update(deployment_file: dict):
    containers = deployment_file["spec"]["template"]["spec"]["containers"]
    for container in containers:
        image_name, current_tag = parse_image(container["image"])
        new_tag = get_latest_image_tag(image_name)
        if new_tag is None:
            return None
        if new_tag != current_tag:
            logger.info(
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


def requests_retry_session(
    retries=3,
    backoff_factor=0.5,
    status_forcelist=(500, 502, 504),
    session=None,
):
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


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
        response = requests_retry_session().get(url)
        response.raise_for_status()
        tags = [tag["name"] for tag in response.json().get("results", [])]
        return tags
    except requests.RequestException as e:
        error_message = (
            f"Error pulling latest image tag from Docker for {image_name}: {e}"
        )
        logger.error(error_message)
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
            response = requests_retry_session().get(
                url, headers={"Authorization": f"Bearer {token}"}
            )
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
        logger.error(error_message)
        send_notification(error_message)
        return None


def fetch_quay_tags(image_name: str):
    if image_name.startswith("quay.io/"):
        image_name = image_name[len("quay.io/") :]
    url = f"https://quay.io/api/v1/repository/{image_name}/tag/"
    try:
        response = requests_retry_session().get(url)
        response.raise_for_status()
        tags = response.json().get("tags", [])
        return tags
    except requests.RequestException as e:
        error_message = (
            f"Error pulling latest image tag from Quay for {image_name}: {e}"
        )
        logger.error(error_message)
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
        logger.warning(f"No tags found for {image_name}")
        return None

    sorted_tags = filter_and_sort_tags(tags)
    if not sorted_tags:
        logger.warning("No tags matching pattern found for %s", image_name)
        return None

    return sorted_tags[0]


if __name__ == "__main__":
    main()
