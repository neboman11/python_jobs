def is_ignored_image(image_name: str, ignored_images: set[str]) -> bool:
    base_name = image_name.split("/")[-1]
    return base_name in ignored_images


def _image_update_value(image_update, key: str) -> str:
    if isinstance(image_update, dict):
        return image_update[key]
    return getattr(image_update, key)


def image_updates_with_minor_or_patch_filter(image_update):
    split_original_tag = _image_update_value(image_update, "current_tag").split(".")
    split_new_tag = _image_update_value(image_update, "new_tag").split(".")
    if len(split_original_tag) < 2 or len(split_new_tag) < 2:
        return False
    if split_original_tag[0] != split_new_tag[0]:
        return False
    return True


def chart_updates_with_minor_or_patch_filter(helm_chart_update):
    split_original_version = helm_chart_update["original_version"].split(".")
    split_new_version = helm_chart_update["new_version"].split(".")
    if split_original_version[0] != split_new_version[0]:
        return False
    return True
