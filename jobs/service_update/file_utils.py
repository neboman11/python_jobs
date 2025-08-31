import io
import yaml

from chart_utils import check_for_helm_chart_update, check_for_chart_update
from image_utils import check_for_image_update


def get_files(repo, contents):
    kustomize_files = []
    deployment_files = []
    chart_files = []
    find_kustomize_and_deployment_files(
        repo, contents, kustomize_files, deployment_files, chart_files
    )
    return kustomize_files, deployment_files, chart_files


def find_kustomize_and_deployment_files(
    argo_repo,
    repo_files,
    kustomize_file_list,
    deployment_file_list,
    chart_file_list,
):
    for file in repo_files:
        if file.type == "file" and file.name == "kustomization.yaml":
            kustomize_file_list.append(file)
        if file.type == "file" and file.name.endswith("deployment.yaml"):
            deployment_file_list.append(file)
        if file.type == "file" and file.name == "Chart.yaml":
            chart_file_list.append(file)
        if file.type == "dir" and file.name != "overlays":
            folder_contents = argo_repo.get_contents(f"/{file.path}")
            if not isinstance(folder_contents, list):
                folder_contents = [folder_contents]
            find_kustomize_and_deployment_files(
                argo_repo,
                folder_contents,
                kustomize_file_list,
                deployment_file_list,
                chart_file_list,
            )


def find_helm_updates(files):
    updates = kustomize_files_find_helm_charts_with_updates(files)
    return updates


def find_chart_updates(files):
    updates = chart_files_find_chart_updates(files)
    return updates


def find_image_updates(files):
    updates = deployment_files_find_image_updates(files)
    return updates


def kustomize_files_find_helm_charts_with_updates(kustomize_files):
    files_needing_updates = []
    for kustomize_file in kustomize_files:
        file_stream = io.BytesIO(kustomize_file.decoded_content)
        try:
            parsed_file = yaml.safe_load(file_stream)
            if "helmCharts" in parsed_file:
                updated_file = check_for_helm_chart_update(parsed_file)
                if updated_file is not None:
                    updated_file["path"] = kustomize_file.path
                    updated_file["sha"] = kustomize_file.sha
                    files_needing_updates.append(updated_file)
        except yaml.YAMLError:
            pass
    return files_needing_updates


def chart_files_find_chart_updates(chart_files):
    files_needing_updates = []
    for chart_file in chart_files:
        file_stream = io.BytesIO(chart_file.decoded_content)
        try:
            parsed_file = yaml.safe_load(file_stream)
            updated_file = check_for_chart_update(parsed_file)
            if updated_file is not None:
                updated_file["path"] = chart_file.path
                updated_file["sha"] = chart_file.sha
                files_needing_updates.append(updated_file)
        except yaml.YAMLError:
            pass
    return files_needing_updates


def deployment_files_find_image_updates(deployment_files):
    files_needing_updates = []
    for deployment_file in deployment_files:
        file_stream = io.BytesIO(deployment_file.decoded_content)
        try:
            parsed_file = yaml.safe_load(file_stream)
            updated_file = check_for_image_update(parsed_file)
            if updated_file is not None:
                updated_file["path"] = deployment_file.path
                updated_file["sha"] = deployment_file.sha
                files_needing_updates.append(updated_file)
        except yaml.YAMLError:
            pass
    return files_needing_updates
