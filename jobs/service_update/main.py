from datetime import datetime
import os
import sys
import logging
from github import Auth, Github

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from notifications import send_notification
from file_utils import (
    get_files,
    find_helm_updates,
    find_image_updates,
    find_chart_updates,
)
from update_handlers import handle_all_updates


def main():
    required_vars = ["GITHUB_PAT", "GHCR_TOKEN"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        error_message = (
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )
        logger.error(error_message)
        send_notification(f"Script terminating. Reason: {error_message}")
        sys.exit(1)

    try:
        github_PAT = os.getenv("GITHUB_PAT")
        dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

        if not github_PAT:
            error_message = "GITHUB_PAT environment variable is required"
            logger.error(error_message)
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

    except Exception as e:
        error_message = (
            f"An unexpected error occurred, forcing the script to terminate: {e}"
        )
        logger.error(error_message, exc_info=True)
        send_notification(error_message)
        sys.exit(1)


if __name__ == "__main__":
    main()
