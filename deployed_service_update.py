import io
import os

from github import Github
from github import Auth
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
        file_stream = io.StringIO(kustomize_file.content)
        parsed_file = yaml.safe_load(file_stream)
        print(parsed_file)


def find_kustomize_file(argo_repo, repo_files, kustomize_file_list):
    for file in repo_files:
        if file.type == "file" and file.name == "kustomization.yaml":
            kustomize_file_list.append(file)
        if file.type == "dir" and file.name != "overlays":
            folder_contents = argo_repo.get_contents(f"/{file.path}")
            find_kustomize_file(argo_repo, folder_contents, kustomize_file_list)


if __name__ == "__main__":
    main()
