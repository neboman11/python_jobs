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


if __name__ == "__main__":
    unittest.main()
