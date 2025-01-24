import base64
from datetime import datetime
import io
import os
from typing import Any

from dotenv import load_dotenv
from github import Auth
from github import ContentFile
from github import Github
from github import Repository
from natsort import natsorted
import requests
import yaml

import jobs_common


def main():
    load_dotenv()
    github_PAT = os.getenv("GITHUB_PAT")

    # using an access token
    auth = Auth.Token(github_PAT)

    # First create a Github instance:
    # Public Web Github
    gh = Github(auth=auth)

    argo_repo = gh.get_repo("neboman11/argocd-definitions")
    repo_contents = argo_repo.get_contents("/")

    print("Finding kustomize and deployment files in repo")
    kustomize_files: list[ContentFile.ContentFile] = []
    deployment_files: list[ContentFile.ContentFile] = []
    find_kustomize_and_deployment_files(
        argo_repo, repo_contents, kustomize_files, deployment_files
    )

    print("Checking helm chart versions for update")
    files_needing_updates = kustomize_files_find_helm_charts_with_updates(
        kustomize_files
    )

    print("Checking image tags for update")
    image_files_needing_updates = deployment_files_find_image_updates(deployment_files)

    if len(files_needing_updates) > 0 or len(image_files_needing_updates) > 0:
        date_string = datetime.now().strftime("%Y-%m-%d")
        new_branch_name = f"service_update/{date_string}"
        target_branch = create_branch_for_chart_updates(argo_repo, new_branch_name)

        charts_to_directly_update = list(
            filter(chart_updates_with_minor_or_patch_filter, files_needing_updates)
        )

        if len(charts_to_directly_update) > 0:
            commit_updates_to_branch(
                argo_repo, target_branch.ref, charts_to_directly_update
            )
            non_major_pull_request = create_pull_request_for_updates(
                argo_repo, new_branch_name, target_branch.ref, charts_to_directly_update
            )

            non_major_pull_request.merge()

            jobs_common.send_discord_notification(
                "Updated versions for "
                + ", ".join(
                    [chart["release_name"] for chart in charts_to_directly_update]
                )
            )

        charts_with_major_version = list(
            filter(
                lambda x: not chart_updates_with_minor_or_patch_filter(x),
                files_needing_updates,
            )
        )

        if len(charts_with_major_version) > 0:
            commit_updates_to_branch(
                argo_repo, target_branch.ref, charts_with_major_version
            )
            non_major_pull_request = create_pull_request_for_updates(
                argo_repo, new_branch_name, target_branch.ref, charts_with_major_version
            )

            jobs_common.send_discord_notification(
                "Created PR for major version bumps on "
                + ", ".join(
                    [chart["release_name"] for chart in charts_with_major_version]
                )
            )

        if len(image_files_needing_updates) > 0:
            commit_image_updates_to_branch(
                argo_repo, target_branch.ref, image_files_needing_updates
            )
            image_pull_request = create_pull_request_for_updates(
                argo_repo,
                new_branch_name,
                target_branch.ref,
                image_files_needing_updates,
            )

            jobs_common.send_discord_notification(
                "Updated image tags for "
                + ", ".join(
                    [image["image_name"] for image in image_files_needing_updates]
                )
            )

    else:
        print("Found no charts or images to update")


def create_pull_request_for_updates(
    argo_repo, new_branch_name: str, target_branch_ref: str, files_to_update
):
    commit_updates_to_branch(argo_repo, target_branch_ref, files_to_update)
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


def create_branch_for_chart_updates(argo_repo: Repository.Repository, new_branch_name):
    print("Creating branch to store changes in")
    main_branch = argo_repo.get_git_ref(f"heads/{argo_repo.default_branch}")
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
        print(response.content)
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
        if not tags:
            return None
        latest_tag = tags[0]["name"]
        return latest_tag

    elif registry == "ghcr.io":
        if image_name.startswith("ghcr.io/"):
            image_name = image_name[len("ghcr.io/") :]
        response = requests.get(
            f"https://ghcr.io/v2/{image_name}/tags/list",
            headers={
                "Authorization": f"Bearer {base64.b64encode(f"neboman11:{os.getenv("GHCR_TOKEN")}")}"
            },
        )
        if not response.ok:
            print(
                f"Error pulling latest image tag from GHCR for {image_name}: {response.content}"
            )
            return None
        tags = response.json().get("tags", [])
        if not tags:
            return None
        latest_tag = tags[0]
        return latest_tag

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
        latest_tag = tags[0]["name"]
        return latest_tag

    else:
        raise ValueError(f"Unsupported registry: {registry}")


def send_discord_notification(message):
    url = f"{os.getenv('PONYBOY_BASE_URL')}/send_discord_message"
    request = {
        "user_id": int(os.getenv("NOTIFY_DISCORD_USER")),
        "message": message,
    }
    response = requests.post(url, json=request)
    if response.status_code > 299:
        print(response.text)


if __name__ == "__main__":
    main()
