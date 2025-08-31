import io
import yaml
import logging
import requests
from natsort import natsorted
from notifications import send_notification


def check_for_chart_update(chart_file: dict):
    dependencies = chart_file.get("dependencies", [])
    for dependency in dependencies:
        chart_name = dependency["name"]
        chart_repo = dependency["repository"]
        if not chart_repo.endswith("/"):
            chart_repo += "/"
        try:
            response = requests.get(f"{chart_repo}index.yaml")
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            error_message = f"Failed to pull chart index from {chart_repo} for {chart_name}. Error: {e}"
            logging.error(error_message)
            send_notification(error_message)
            continue
        repository_index = yaml.safe_load(io.BytesIO(response.content))
        remote_versions = [
            chart["version"]
            for chart in repository_index["entries"].get(chart_name, [])
        ]
        remote_versions = list(
            filter(
                lambda x: "dev" not in x and "alpha" not in x and "beta" not in x,
                remote_versions,
            )
        )
        remote_versions = list(natsorted(remote_versions, reverse=True))
        if remote_versions and remote_versions[0] != dependency["version"]:
            original_version = dependency["version"]
            dependency["version"] = remote_versions[0]
            return {
                "chart_file": chart_file,
                "original_version": original_version,
                "new_version": remote_versions[0],
                "chart_name": chart_name,
            }


def check_for_helm_chart_update(kustomize_file: dict):
    deployed_chart = kustomize_file["helmCharts"][0]
    if deployed_chart.get("namespace") == "databases":
        return
    chart_repo = deployed_chart["repo"]
    if not chart_repo.endswith("/"):
        chart_repo += "/"
    try:
        response = requests.get(f"{chart_repo}index.yaml")
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        error_message = f"Failed to pull chart index from {chart_repo} for {deployed_chart.get('releaseName')}. Error: {e}"
        logging.error(error_message)
        send_notification(error_message)
        return
    repository_index = yaml.safe_load(io.BytesIO(response.content))
    remote_versions = [
        chart["version"]
        for chart in repository_index["entries"][deployed_chart["name"]]
    ]
    remote_versions = list(
        filter(
            lambda x: "dev" not in x and "alpha" not in x and "beta" not in x,
            remote_versions,
        )
    )
    remote_versions = list(natsorted(remote_versions, reverse=True))
    if remote_versions[0] != deployed_chart["version"]:
        original_version = deployed_chart["version"]
        kustomize_file["helmCharts"][0]["version"] = remote_versions[0]
        return {
            "kustomize_file": kustomize_file,
            "original_version": original_version,
            "new_version": remote_versions[0],
            "release_name": deployed_chart.get("releaseName"),
        }
