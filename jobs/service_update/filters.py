def image_updates_with_minor_or_patch_filter(image_update):
    split_original_tag = image_update["current_tag"].split(".")
    split_new_tag = image_update["new_tag"].split(".")

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
