import io
import yaml
import logging
import github

from filters import (
    chart_updates_with_minor_or_patch_filter,
    image_updates_with_minor_or_patch_filter,
)
from notifications import send_notification
from update_types import UpdateType


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
                logging.info("Committing changes to update helm charts")
            case UpdateType.Image:
                logging.info("Committing changes to update image tags")
            case UpdateType.HelmChart:
                logging.info("Committing changes to update chart dependencies")
        commit_updates_to_branch(repo, target_branch.ref, update_objects)
        pr = create_pull_request_for_updates(repo, branch_name)
        if not is_major:
            logging.info("Merging PR automatically for minor/patch update")
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


def create_branch_for_updates(argo_repo, new_branch_name):
    logging.info("Creating branch to store changes in")
    main_branch = argo_repo.get_git_ref(f"heads/{argo_repo.default_branch}")
    try:
        new_branch = argo_repo.get_git_ref(f"heads/{new_branch_name}")
        logging.debug("Branch already exists: %s", new_branch_name)
    except github.GithubException:
        logging.info("Branch does not exist, creating: %s", new_branch_name)
        new_branch = argo_repo.create_git_ref(
            f"refs/heads/{new_branch_name}", main_branch.object.sha
        )
    return new_branch


def commit_updates_to_branch(
    argo_repo,
    target_branch_ref,
    files_needing_updates,
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
            logging.warning("Unable to add file to commit: %s", file)


def create_pull_request_for_updates(argo_repo, new_branch_name: str):
    pull_request = argo_repo.create_pull(
        argo_repo.default_branch,
        new_branch_name,
        title="Automatic Helm chart version and image tag bump",
        body="",
    )
    return pull_request
