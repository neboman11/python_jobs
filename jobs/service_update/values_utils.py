from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import logging

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

from filters import is_ignored_image
from image_utils import get_latest_image_tag, parse_image


@dataclass(frozen=True)
class ValuesImageUpdate:
    path: str
    sha: str
    content: str
    image_name: str
    current_tag: str
    new_tag: str
    start: int
    end: int
    replacement: str


def _render_scalar(value: str, node: ScalarNode) -> str:
    if node.style == "'":
        return "'" + value.replace("'", "''") + "'"
    if node.style == '"':
        return f'"{value}"'
    return value


def _image_nodes(node):
    if isinstance(node, MappingNode):
        values = {
            key.value: value
            for key, value in node.value
            if isinstance(key, ScalarNode)
        }
        repository = values.get("repository")
        tag = values.get("tag")
        if (
            isinstance(repository, ScalarNode)
            and isinstance(tag, ScalarNode)
            and repository.value
            and tag.value
        ):
            yield repository.value, tag.value, tag, _render_scalar

        for key, value in node.value:
            if (
                isinstance(key, ScalarNode)
                and key.value == "image"
                and isinstance(value, ScalarNode)
                and ":" in value.value
                and "@" not in value.value
            ):
                try:
                    image_name, tag_value = parse_image(value.value)
                except ValueError:
                    pass
                else:
                    if tag_value:
                        yield image_name, tag_value, value, _render_scalar

            yield from _image_nodes(value)

    elif isinstance(node, SequenceNode):
        for item in node.value:
            yield from _image_nodes(item)


def find_image_updates(values_files, ignored_images: set[str]):
    candidates = []
    latest_tags = {}

    for values_file in values_files:
        content = values_file.decoded_content.decode("utf-8")
        try:
            document = yaml.compose(content)
        except yaml.YAMLError as error:
            logging.warning("Skipping invalid YAML in %s: %s", values_file.path, error)
            continue

        if document is None:
            continue

        for image_name, current_tag, node, render_scalar in _image_nodes(document):
            if is_ignored_image(image_name, ignored_images):
                logging.info("Skipping ignored image %s", image_name)
                continue

            if image_name not in latest_tags:
                try:
                    latest_tags[image_name] = get_latest_image_tag(image_name)
                except ValueError as error:
                    logging.warning("Skipping image %s: %s", image_name, error)
                    latest_tags[image_name] = None

            new_tag = latest_tags[image_name]
            if not new_tag or new_tag == current_tag:
                continue

            replacement = (
                render_scalar(f"{image_name}:{new_tag}", node)
                if ":" in node.value and "/" in node.value
                else render_scalar(new_tag, node)
            )
            candidates.append(
                ValuesImageUpdate(
                    path=values_file.path,
                    sha=values_file.sha,
                    content=content,
                    image_name=image_name,
                    current_tag=current_tag,
                    new_tag=new_tag,
                    start=node.start_mark.index,
                    end=node.end_mark.index,
                    replacement=replacement,
                )
            )

    return candidates


def group_image_updates(image_updates):
    grouped = defaultdict(list)
    for image_update in image_updates:
        grouped[(image_update.path, image_update.sha, image_update.content)].append(
            image_update
        )

    values_updates = []
    for (path, sha, content), updates in grouped.items():
        updated_content = content
        for update in sorted(updates, key=lambda item: item.start, reverse=True):
            updated_content = (
                updated_content[: update.start]
                + update.replacement
                + updated_content[update.end :]
            )

        values_updates.append(
            {
                "path": path,
                "sha": sha,
                "content": updated_content,
                "image_updates": [
                    {
                        "image_name": update.image_name,
                        "current_tag": update.current_tag,
                        "new_tag": update.new_tag,
                    }
                    for update in updates
                ],
            }
        )

    return values_updates
