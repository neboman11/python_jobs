import base64
from datetime import datetime
import io
import os
import re
from typing import Any
import argparse

from dotenv import load_dotenv
from github import Auth
from github import ContentFile
from github import Github
from github import Repository
import github
from natsort import natsorted
import requests
import yaml

import jobs_common


def main(dry_run: bool):
    # Initialize GitHub connection
    load_dotenv()
    github_PAT = os.getenv("GITHUB_PAT")
    auth = Auth.Token(github_PAT)
    gh = Github(auth=auth)
    argo_repo = gh.get_repo("neboman11/argocd-definitions")
    repo_contents = argo_repo.get_contents("/")

    print("Finding kustomize and deployment files in repo")
    kustomize_files, deployment_files = get_files(argo_repo, repo_contents)

    print("Checking for updates")
    helm_updates = find_helm_updates(kustomize_files)
    image_updates = find_image_updates(deployment_files)

    if not (helm_updates or image_updates):
        print("Found no charts or images to update")
        return

    date_string = datetime.now().strftime("%Y-%m-%d")
    new_branch_name = f"service_update/{date_string}"

    handle_updates(
        argo_repo,
        new_branch_name,
        dry_run,
        helm_updates,
        image_updates,
    )

    if dry_run:
        print("Dry run complete. No changes were committed.")


def get_files(repo, contents):
    kustomize_files = []
    deployment_files = []
    find_kustomize_and_deployment_files(
        repo, contents, kustomize_files, deployment_files
    )
    return kustomize_files, deployment_files


def find_helm_updates(files):
    updates = kustomize_files_find_helm_charts_with_updates(files)
    return updates


def find_image_updates(files):
    updates = deployment_files_find_image_updates(files)
    return updates


def handle_updates(repo, branch_name, dry_run, helm_updates, image_updates):
    if helm_updates:
        charts_to_update = filter_updates(
            helm_updates, chart_updates_with_minor_or_patch_filter
        )
        if charts_to_update:
            handle_chart_updates(repo, branch_name, dry_run, charts_to_update)

        charts_major = filter_updates(
            helm_updates, lambda x: not chart_updates_with_minor_or_patch_filter(x)
        )
        if charts_major:
            handle_chart_updates(
                repo, branch_name, dry_run, charts_major, is_major=True
            )

    if image_updates:
        images_to_update = filter_updates(
            image_updates, image_updates_with_minor_or_patch_filter
        )
        if images_to_update:
            handle_image_updates(repo, branch_name, dry_run, images_to_update)

        images_major = filter_updates(
            image_updates, lambda x: not image_updates_with_minor_or_patch_filter(x)
        )
        if images_major:
            handle_image_updates(
                repo, branch_name, dry_run, images_major, is_major=True
            )


def filter_updates(updates, filter_func):
    return list(filter(filter_func, updates))


def handle_chart_updates(repo, branch_name, dry_run, charts, is_major=False):
    if not dry_run:
        target_branch = create_branch_for_updates(repo, branch_name)
        commit_updates_to_branch(repo, target_branch.ref, charts)
        pr = create_pull_request_for_updates(repo, branch_name)
        if not is_major:
            pr.merge()

    notification_type = "major version bumps on" if is_major else "updates for"
    send_notification(
        f"{'Created PR for' if is_major else 'Updated'} {notification_type} {', '.join([chart['release_name'] for chart in charts])}"
    )


def image_updates_with_minor_or_patch_filter(image_update):
    split_original_tag = image_update["current_tag"].split(".")
    split_new_tag = image_update["new_tag"].split(".")

    if len(split_original_tag) < 2 or len(split_new_tag) < 2:
        return False

    if split_original_tag[0] != split_new_tag[0]:
        return False

    return True


def handle_image_updates(repo, branch_name, dry_run, images, is_major=False):
    if not dry_run:
        target_branch = create_branch_for_updates(repo, branch_name)
        commit_image_updates_to_branch(repo, target_branch.ref, images)
        pr = create_pull_request_for_updates(repo, branch_name)
        if not is_major:
            pr.merge()

    notification_type = "major version bumps on" if is_major else "updates for"
    send_notification(
        f"{'Created PR for' if is_major else 'Updated'} {notification_type} {', '.join([image['image_name'] for image in images])}"
    )


def send_notification(message):
    jobs_common.send_discord_notification(message)


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
    print("Creating branch to store changes in")
    main_branch = argo_repo.get_git_ref(f"heads/{argo_repo.default_branch}")
    try:
        new_branch = argo_repo.get_git_ref(f"heads/{new_branch_name}")
    except github.GithubException:
        new_branch = argo_repo.create_git_ref(
            f"refs/heads/{new_branch_name}", main_branch.object.sha
        )

    return new_branch


def commit_updates_to_branch(
    argo_repo: Repository.Repository,
    target_branch_ref: str,
    files_needing_updates: list[dict[str, Any]],
):
    print("Committing changes to update helm charts")
    for file in files_needing_updates:
        file_content_stream = io.StringIO()
        yaml.dump(file["kustomize_file"], file_content_stream)
        file_content_stream.seek(0)
        argo_repo.update_file(
            file["path"],
            f"Bump {file['release_name']} version to {file['new_version']}",
            file_content_stream.getvalue(),
            file["sha"],
            target_branch_ref,
        )


def commit_image_updates_to_branch(
    argo_repo: Repository.Repository,
    target_branch_ref: str,
    files_needing_updates: list[dict[str, Any]],
):
    print("Committing changes to update image tags")
    for file in files_needing_updates:
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


def kustomize_files_find_helm_charts_with_updates(
    kustomize_files: list[ContentFile.ContentFile],
):
    files_needing_updates: list[dict[str, Any]] = []
    for kustomize_file in kustomize_files:
        file_stream = io.BytesIO(kustomize_file.decoded_content)
        parsed_file = yaml.safe_load(file_stream)
        # Check that the file contains a helm chart
        if "helmCharts" in parsed_file:
            updated_file = check_for_helm_chart_update(parsed_file)
            if updated_file != None:
                updated_file["path"] = kustomize_file.path
                updated_file["sha"] = kustomize_file.sha
                files_needing_updates.append(updated_file)
    return files_needing_updates


def check_for_helm_chart_update(kustomize_file: dict):
    deployed_chart = kustomize_file["helmCharts"][0]
    if deployed_chart["namespace"] == "databases":
        return

    chart_repo = deployed_chart["repo"]
    if not chart_repo.endswith("/"):
        chart_repo += "/"

    # Pull the index file containing all the available charts at the repo
    response = requests.get(f"{chart_repo}index.yaml")
    if not response.ok:
        print(
            f"Error pulling latest chart index from {chart_repo} for {deployed_chart["releaseName"]}: {response.content}"
        )
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
        # Return an object containing the file object with the updated version, the old, version, and the new version
        original_version = deployed_chart["version"]
        kustomize_file["helmCharts"][0]["version"] = remote_versions[0]
        return {
            "kustomize_file": kustomize_file,
            "original_version": original_version,
            "new_version": remote_versions[0],
            "release_name": deployed_chart["releaseName"],
        }


def find_kustomize_and_deployment_files(
    argo_repo: Repository.Repository,
    repo_files: list[ContentFile.ContentFile],
    kustomize_file_list: list[ContentFile.ContentFile],
    deployment_file_list: list[ContentFile.ContentFile],
):
    for file in repo_files:
        if file.type == "file" and file.name == "kustomization.yaml":
            kustomize_file_list.append(file)
        if file.type == "file" and file.name == "deployment.yaml":
            deployment_file_list.append(file)
        if file.type == "dir" and file.name != "overlays":
            folder_contents = argo_repo.get_contents(f"/{file.path}")
            find_kustomize_and_deployment_files(
                argo_repo, folder_contents, kustomize_file_list, deployment_file_list
            )


def deployment_files_find_image_updates(
    deployment_files: list[ContentFile.ContentFile],
):
    files_needing_updates: list[dict[str, Any]] = []
    for deployment_file in deployment_files:
        file_stream = io.BytesIO(deployment_file.decoded_content)
        parsed_file = yaml.safe_load(file_stream)
        updated_file = check_for_image_update(parsed_file)
        if updated_file != None:
            updated_file["path"] = deployment_file.path
            updated_file["sha"] = deployment_file.sha
            files_needing_updates.append(updated_file)
    return files_needing_updates


def check_for_image_update(deployment_file: dict):
    containers = deployment_file["spec"]["template"]["spec"]["containers"]
    for container in containers:
        image_name, current_tag = parse_image(container["image"])
        new_tag = get_latest_image_tag(image_name)
        if new_tag == None:
            return None
        if new_tag != current_tag:
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


def get_latest_image_tag(image_name: str):
    # Default registry
    registry = "docker.io"

    # Split the image name to check for registry
    parts = image_name.split("/")

    # Check if the first part is a registry
    if len(parts) > 1 and "." in parts[0]:
        registry = parts[0]
        image_name = "/".join(parts[1:])
    else:
        image_name = "/".join(parts)

    if registry == "docker.io":
        if image_name.startswith("docker.io/"):
            image_name = image_name[len("docker.io/") :]
        parts = image_name.split("/")
        if len(parts) == 1:
            image_name = f"library/{parts[0]}"
        else:
            image_name = "/".join(parts)

        response = requests.get(
            f"https://hub.docker.com/v2/repositories/{image_name}/tags/"
        )
        if not response.ok:
            print(
                f"Error pulling latest image tag from Docker for {image_name}: {response.content}"
            )
            return None
        tags = response.json().get("results", [])
        tags = [tag["name"] for tag in tags]
        if not tags:
            return None
    elif registry == "ghcr.io":
        if image_name.startswith("ghcr.io/"):
            image_name = image_name[len("ghcr.io/") :]
        image_user = image_name.split("/")[0]
        image_repo = image_name[len(image_user) + 1 :].replace("/", "%2F")
        tags = []
        response = requests.get(
            f"https://api.github.com/users/{image_user}/packages/container/{image_repo}/versions",
            headers={"Authorization": f"Bearer {os.getenv('GHCR_TOKEN')}"},
        )
        if not response.ok:
            print(
                f"Error pulling latest image tag from GHCR for {image_name}: {response.content}"
            )
            return None

        packages = response.json()
        page_num = 1
        # Pull version tags for every page
        while len(packages) > 0:
            [
                tags.append(tag)
                for package in packages
                for tag in package["metadata"]["container"]["tags"]
            ]
            page_num += 1
            response = requests.get(
                f"https://api.github.com/users/{image_user}/packages/container/{image_repo}/versions?page={page_num}",
                headers={"Authorization": f"Bearer {os.getenv('GHCR_TOKEN')}"},
            )
            if not response.ok:
                print(
                    f"Error pulling image tag page {page_num} from GHCR for {image_name}: {response.content}"
                )
                return None
            packages = response.json()

        if not tags:
            return None
    elif registry == "quay.io":
        if image_name.startswith("quay.io/"):
            image_name = image_name[len("quay.io/") :]
        response = requests.get(f"https://quay.io/api/v1/repository/{image_name}/tag/")
        if not response.ok:
            print(
                f"Error pulling latest image tag from Quay for {image_name}: {response.content}"
            )
            return None
        tags = response.json().get("tags", [])
        if not tags:
            return None
    else:
        raise ValueError(f"Unsupported registry: {registry}")

    # Filter tags to match the regex pattern
    regex = re.compile(r"^v?\d+\.\d+\.\d+(?:\.\d+)?$")
    filtered_tags = [tag for tag in tags if regex.match(tag)]

    if not filtered_tags:
        print(f"No tags found matching the pattern for {image_name}")
        return None

    # Sort the tags using natsorted
    sorted_tags = natsorted(filtered_tags, key=lambda x: x, reverse=True)

    # Get the latest tag
    latest_tag = sorted_tags[0]
    return latest_tag


def send_discord_notification(message):
    url = f"{os.getenv('PONYBOY_BASE_URL')}/send_discord_message"
    request = {
        "user_id": int(os.getenv("NOTIFY_DISCORD_USER")),
        "message": message,
    }
    response = requests.post(url, json=request)
    if not response.ok:
        print(f"Error sending discord message to ponyboy: {response.content}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deployed service update script")
    parser.add_argument(
        "--dry-run", "-d", action="store_true", help="Run the script in dry run mode"
    )
    args = parser.parse_args()
    main(args.dry_run)
