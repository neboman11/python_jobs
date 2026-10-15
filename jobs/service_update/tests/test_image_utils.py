import unittest
from unittest.mock import MagicMock, patch

from image_utils import get_latest_image_tag


class GetLatestImageTagTests(unittest.TestCase):
    def test_reads_tag_names_from_quay_tag_objects(self):
        response = MagicMock()
        response.json.return_value = {
            "tags": [
                {"name": "master"},
                {"name": "v0.27.0"},
                {"name": "v0.28.0"},
            ]
        }

        with patch("image_utils.RetrySession") as session:
            session.return_value.get.return_value = response
            latest = get_latest_image_tag("quay.io/prometheus/blackbox-exporter")

        self.assertEqual(latest, "v0.28.0")

    def _docker_tags(self, image_name, current_tag, tags):
        with patch("image_utils.fetch_docker_tags", return_value=tags):
            return get_latest_image_tag(image_name, current_tag)

    def test_keeps_architecture_variant_of_current_tag(self):
        tags = ["v2.30.0-armv7", "v2.30.0-amd64", "v2.30.0-arm64v8", "v2.30.0-armv6", "v2.30.0", "v2.29.0-amd64"]
        latest = self._docker_tags("binwiederhier/ntfy", "v2.29.0-amd64", tags)
        self.assertEqual(latest, "v2.30.0-amd64")

    def test_multi_arch_current_tag_rejects_arch_specific_tags(self):
        tags = ["v2.31.0-armv7", "v2.31.0-amd64", "v2.30.0-armv6", "v2.30.0-arm64v8", "v2.30.0"]
        latest = self._docker_tags("binwiederhier/ntfy", "v2.29.0", tags)
        self.assertEqual(latest, "v2.30.0")


if __name__ == "__main__":
    unittest.main()
