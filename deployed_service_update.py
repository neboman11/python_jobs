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

    print("Finding kustomize files in repo")
    kustomize_files: list[ContentFile.ContentFile] = []
    find_kustomize_file(argo_repo, repo_contents, kustomize_files)

    print("Checking helm chart versions for update")
    files_needing_updates = kustomize_files_find_helm_charts_with_updates(
        kustomize_files
    )

    date_string = datetime.now().strftime("%Y-%m-%d")
    new_branch_name = f"service_update/{date_string}"
    target_branch = create_branch_for_chart_updates(argo_repo, new_branch_name)

    charts_to_directly_update = list(
        filter(chart_updates_with_minor_or_patch_filter, files_needing_updates)
    )

    if len(charts_to_directly_update) > 0:
        non_major_pull_request = create_pull_request_for_updates(
            argo_repo, new_branch_name, target_branch.ref, charts_to_directly_update
        )

        non_major_pull_request.merge()

    charts_with_major_version = list(
        filter(
            lambda x: not chart_updates_with_minor_or_patch_filter(x),
            files_needing_updates,
        )
    )

    if len(charts_with_major_version) > 0:
        non_major_pull_request = create_pull_request_for_updates(
            argo_repo, new_branch_name, target_branch.ref, charts_with_major_version
        )


def create_pull_request_for_updates(
    argo_repo, new_branch_name: str, target_branch_ref: str, charts_to_update
):
    commit_updates_to_branch(argo_repo, target_branch_ref, charts_to_update)
    pull_request = argo_repo.create_pull(
        argo_repo.default_branch,
        new_branch_name,
        title="Automatic Helm chart version bump",
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

        # Send a discord message alerting of the new version
        send_discord_notification(
            f"{deployed_chart['namespace']}.{deployed_chart['releaseName']} has a new version: {remote_versions[0]}"
        )


def find_kustomize_file(
    argo_repo: Repository.Repository,
    repo_files: list[ContentFile.ContentFile],
    kustomize_file_list: list[ContentFile.ContentFile],
):
    for file in repo_files:
        if file.type == "file" and file.name == "kustomization.yaml":
            kustomize_file_list.append(file)
        if file.type == "dir" and file.name != "overlays":
            folder_contents = argo_repo.get_contents(f"/{file.path}")
            find_kustomize_file(argo_repo, folder_contents, kustomize_file_list)


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
