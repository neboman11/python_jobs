import base64
from datetime import datetime
import io
import os

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

    kustomize_files: list[ContentFile.ContentFile] = []
    find_kustomize_file(argo_repo, repo_contents, kustomize_files)

    files_needing_updates = []
    for kustomize_file in kustomize_files:
        file_stream = io.BytesIO(kustomize_file.decoded_content)
        parsed_file = yaml.safe_load(file_stream)
        # Check that the file contains a helm chart
        if "helmCharts" in kustomize_file:
            updated_file = check_for_helm_chart_update(parsed_file)
            if updated_file != None:
                updated_file["path"] = kustomize_file.path
                updated_file["sha"] = kustomize_file.sha
                files_needing_updates.append(updated_file)

    # date_string = datetime.now().strftime("%Y-%m-%d")
    # main_branch = argo_repo.get_git_ref(f"heads/{argo_repo.default_branch}")
    # new_branch = argo_repo.create_git_ref(
    #     f"refs/heads/service_update/{date_string}", main_branch.object.sha
    # )

    # for file in files_needing_updates:
    #     file_content_stream = io.StringIO()
    #     yaml.dump(file["kustomize_file"], file_content_stream)
    #     argo_repo.update_file(
    #         file["path"],
    #         f"Bump version to {file['new_version']}",
    #         base64.b64encode(file_content_stream),
    #         file["sha"],
    #         new_branch.ref,
    #     )


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
        # return {
        #     "kustomize_file": kustomize_file,
        #     "original_version": original_version,
        #     "new_version": remote_versions[0],
        # }

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
