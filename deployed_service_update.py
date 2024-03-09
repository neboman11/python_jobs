import os

from github import Github
from github import Auth


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

    find_kustomize_file(argo_repo, repo_contents)


def find_kustomize_file(argo_repo, repo_files):
    for file in repo_files:
        if file.type == "file" and file.name == "kustomization.yaml":
            return file
        if file.type == "dir":
            folder_contents = argo_repo.get_contents(f"/{file.path}")
            print(folder_contents)


if __name__ == "__main__":
    main()
