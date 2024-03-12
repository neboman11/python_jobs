import base64
import io
import os

from github import Github
from github import Auth
from natsort import natsorted
import requests
import yaml


def main():
    discord_user = os.getenv("NOTIFY_DISCORD_USER")
    github_PAT = os.getenv("GITHUB_PAT")

    # using an access token
    auth = Auth.Token(github_PAT)

    # First create a Github instance:
    # Public Web Github
    gh = Github(auth=auth)

    argo_repo = gh.get_repo("neboman11/argocd-definitions")
    repo_contents = argo_repo.get_contents("/")

    kustomize_files = []
    find_kustomize_file(argo_repo, repo_contents, kustomize_files)

    print(kustomize_files)
    for kustomize_file in kustomize_files:
        file_stream = io.BytesIO(base64.b64decode(kustomize_file.content))
        parsed_file = yaml.safe_load(file_stream)
        check_for_helm_chart_update(parsed_file)


def check_for_helm_chart_update(kustomize_file):
    # Check that the file contains a helm chart
    if "helmCharts" in kustomize_file:
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
        print(remote_versions[0])

        if remote_versions[0] != deployed_chart["version"]:
            # Send a discord message alerting of the new version
            print(
                f"{deployed_chart['namespace']}.{deployed_chart['releaseName']} has a new version: {remote_versions[0]}"
            )


def find_kustomize_file(argo_repo, repo_files, kustomize_file_list):
    for file in repo_files:
        if file.type == "file" and file.name == "kustomization.yaml":
            kustomize_file_list.append(file)
        if file.type == "dir" and file.name != "overlays":
            folder_contents = argo_repo.get_contents(f"/{file.path}")
            find_kustomize_file(argo_repo, folder_contents, kustomize_file_list)


if __name__ == "__main__":
    main()
