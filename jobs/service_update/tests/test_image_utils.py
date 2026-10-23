import unittest
from unittest.mock import MagicMock, patch

from image_utils import fetch_docker_tags, get_latest_image_tag


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

    QBT_TAGS = [
        "5.3.0-libtorrentv1",
        "libtorrentv1-version-5.3.0_v2.0.15",
        "libtorrentv1-5.3.0_v2.0.15-ls139",
        "arm64v8-libtorrentv1-version-5.3.0_v2.0.15",
        "amd64-libtorrentv1-version-5.3.0_v2.0.15",
        "version-5.3.0_v2.1.2",
        "5.3.0",
        "version-5.2.1_v2.1.2",
    ]

    def test_keeps_build_flavour_prefix_of_current_tag(self):
        latest = self._docker_tags(
            "lscr.io/linuxserver/qbittorrent", "version-5.3.0_v2.1.2", self.QBT_TAGS
        )
        self.assertEqual(latest, "version-5.3.0_v2.1.2")

    def test_libtorrent_v1_tag_only_updates_within_its_flavour(self):
        latest = self._docker_tags(
            "lscr.io/linuxserver/qbittorrent",
            "libtorrentv1-version-5.2.0_v2.0.14",
            self.QBT_TAGS,
        )
        self.assertEqual(latest, "libtorrentv1-version-5.3.0_v2.0.15")

    def test_partial_registry_results_never_downgrade_current_version(self):
        latest = self._docker_tags(
            "lscr.io/linuxserver/qbittorrent",
            "version-5.3.0_v2.1.2",
            ["version-5.2.1_v2.1.2"],
        )
        self.assertEqual(latest, "version-5.3.0_v2.1.2")

    def test_stable_flavour_still_accepts_new_releases(self):
        latest = self._docker_tags(
            "lscr.io/linuxserver/qbittorrent",
            "version-5.2.1_v2.1.2",
            self.QBT_TAGS,
        )
        self.assertEqual(latest, "version-5.3.0_v2.1.2")

    def test_suffix_flavour_numbers_remain_distinct(self):
        latest = self._docker_tags(
            "lscr.io/linuxserver/qbittorrent",
            "5.2.0-libtorrentv1",
            ["5.3.0-libtorrentv1", "5.4.0-libtorrentv2"],
        )
        self.assertEqual(latest, "5.3.0-libtorrentv1")

    def test_timestamp_build_updates_remain_enabled(self):
        with patch(
            "image_utils.fetch_ghcr_tags", return_value=["12.2.20261006-010203"]
        ):
            latest = get_latest_image_tag(
                "ghcr.io/jellyfin/jellyfin", "12.2.20261005-225228"
            )
        self.assertEqual(latest, "12.2.20261006-010203")

    def test_calendar_version_is_not_replaced_by_legacy_v_prefixed_tag(self):
        self.assertEqual(
            self._docker_tags("docker.io/pihole/pihole", "2026.10.0",
                              ["v5.8.1", "2026.10.0", "2026.09.0"]),
            "2026.10.0",
        )

    def test_partial_legacy_results_cannot_downgrade_calendar_version(self):
        self.assertEqual(
            self._docker_tags("pihole/pihole", "2026.10.0", ["v5.8.1"]),
            "2026.10.0",
        )

    def test_calendar_release_updates_remain_enabled(self):
        self.assertEqual(
            self._docker_tags("pihole/pihole", "2026.10.0",
                              ["v5.8.1", "2026.11.0"]),
            "2026.11.0",
        )

    def test_ntfy_rejects_known_sigill_release_on_amd64(self):
        self.assertEqual(
            self._docker_tags("docker.io/binwiederhier/ntfy", "v2.32.0-amd64",
                              ["v2.33.0-amd64", "v2.32.0-amd64"]),
            "v2.32.0-amd64",
        )

    def test_ntfy_accepts_cpu_compatibility_fix(self):
        self.assertEqual(
            self._docker_tags("docker.io/binwiederhier/ntfy", "v2.33.0-amd64",
                              ["v2.33.0-amd64", "v2.33.1-amd64"]),
            "v2.33.1-amd64",
        )

    def test_docker_tags_follow_pagination(self):
        pages = [
            {"results": [{"name": "libtorrentv1-version-5.3.0_v2.0.15"}], "next": "https://hub/p2"},
            {"results": [{"name": "version-5.3.0_v2.1.2"}], "next": None},
        ]
        responses = []
        for page in pages:
            response = MagicMock()
            response.json.return_value = page
            responses.append(response)
        with patch("image_utils.RetrySession") as session:
            session.return_value.get.side_effect = responses
            tags = fetch_docker_tags("linuxserver/qbittorrent")
        self.assertEqual(
            tags, ["libtorrentv1-version-5.3.0_v2.0.15", "version-5.3.0_v2.1.2"]
        )


if __name__ == "__main__":
    unittest.main()
