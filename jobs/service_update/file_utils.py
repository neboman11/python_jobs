from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import yaml

from chart_utils import check_for_chart_update, check_for_helm_chart_update
from values_utils import find_image_updates


@dataclass(frozen=True)
class RepositoryFile:
    path: str
    sha: str
    decoded_content: bytes


def get_files(argo_repo):
    """Fetch only updater inputs with one recursive tree request."""
    kustomize_files = []
    values_files = []
    chart_files = []

    tree = argo_repo.get_git_tree(argo_repo.default_branch, recursive=True)
    for entry in tree.tree:
        if entry.type != "blob":
            continue

        target = None
        if entry.path.endswith("kustomization.yaml"):
            target = kustomize_files
        elif entry.path.endswith("values.yaml"):
            target = values_files
        elif entry.path.endswith("Chart.yaml"):
            target = chart_files

        if target is None:
            continue

        blob = argo_repo.get_git_blob(entry.sha)
        target.append(
            RepositoryFile(
                path=entry.path,
                sha=entry.sha,
                decoded_content=base64.b64decode(blob.content),
            )
        )

    return kustomize_files, values_files, chart_files


def find_helm_updates(kustomize_files, ignored_images: set[str]):
    files_needing_updates = []

    for kustomize_file in kustomize_files:
        try:
            parsed_file = yaml.safe_load(io.BytesIO(kustomize_file.decoded_content))
        except yaml.YAMLError:
            continue

        if not parsed_file or "helmCharts" not in parsed_file:
            continue

        updated_file = check_for_helm_chart_update(parsed_file, ignored_images)
        if updated_file is None:
            continue

        updated_file["path"] = kustomize_file.path
        updated_file["sha"] = kustomize_file.sha
        files_needing_updates.append(updated_file)

    return files_needing_updates


def find_chart_updates(chart_files, ignored_images: set[str]):
    files_needing_updates = []

    for chart_file in chart_files:
        try:
            parsed_file = yaml.safe_load(io.BytesIO(chart_file.decoded_content))
        except yaml.YAMLError:
            continue

        updated_file = check_for_chart_update(parsed_file, ignored_images)
        if updated_file is None:
            continue

        updated_file["path"] = chart_file.path
        updated_file["sha"] = chart_file.sha
        files_needing_updates.append(updated_file)

    return files_needing_updates
