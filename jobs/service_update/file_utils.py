from __future__ import annotations

import io

import yaml

from chart_utils import check_for_chart_update, check_for_helm_chart_update
from values_utils import find_image_updates


def get_files(argo_repo):
    """Collect updater inputs through the Contents API supported by this token."""
    kustomize_files = []
    values_files = []
    chart_files = []

    def collect(contents):
        for file in contents:
            if file.type == "dir":
                collect(argo_repo.get_contents(file.path))
                continue

            if file.type != "file":
                continue

            target = None
            if file.name == "kustomization.yaml":
                target = kustomize_files
            elif file.name == "values.yaml":
                target = values_files
            elif file.name == "Chart.yaml":
                target = chart_files

            if target is not None:
                target.append(argo_repo.get_contents(file.path))

    collect(argo_repo.get_contents("/"))
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
