from types import SimpleNamespace
import unittest
from unittest.mock import patch

from values_utils import find_image_updates, group_image_updates


class FindImageUpdatesTests(unittest.TestCase):
    def test_updates_immich_tag_without_an_explicit_repository(self):
        values_file = SimpleNamespace(
            path="immich/immich/values.yaml",
            sha="abc123",
            decoded_content=b"immich:\n  image:\n    tag: v2.6.3\n",
        )

        with patch(
            "values_utils.get_latest_image_tag",
            return_value="v2.6.4",
        ):
            updates = find_image_updates([values_file], set())

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].image_name, "ghcr.io/immich-app/immich-server")
        self.assertEqual(updates[0].current_tag, "v2.6.3")
        self.assertEqual(updates[0].new_tag, "v2.6.4")
        self.assertEqual(
            group_image_updates(updates)[0]["content"],
            "immich:\n  image:\n    tag: v2.6.4\n",
        )

    def test_does_not_duplicate_immich_tag_with_an_explicit_repository(self):
        values_file = SimpleNamespace(
            path="immich/immich/values.yaml",
            sha="abc123",
            decoded_content=(
                b"immich:\n"
                b"  image:\n"
                b"    repository: ghcr.io/immich-app/immich-server\n"
                b"    tag: v2.6.3\n"
            ),
        )

        with patch(
            "values_utils.get_latest_image_tag",
            return_value="v2.6.4",
        ):
            updates = find_image_updates([values_file], set())

        self.assertEqual(len(updates), 1)
