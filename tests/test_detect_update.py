import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import detect_update


class DetectUpdateTest(unittest.TestCase):
    def test_reports_no_update_without_changing_repository_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "amp-manifest.json"
            source = root / "hashes.json"
            output = root / "output"
            manifest.write_text(json.dumps({"amp_version": "1.2.3"}))
            source.write_text(json.dumps({"version": "1.2.3", "hashes": {}}))
            before = {path.name: path.read_bytes() for path in root.iterdir()}

            exit_code = detect_update.run(manifest, str(source), output)

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                output.read_text().splitlines(),
                [
                    "detector_status=no-update",
                    "update_available=false",
                    "old_version=1.2.3",
                    "new_version=1.2.3",
                ],
            )
            self.assertEqual(
                {path.name: path.read_bytes() for path in root.iterdir() if path != output},
                before,
            )

    def test_reports_version_mismatch_for_updater(self) -> None:
        result = detect_update.compare_versions(
            {"amp_version": "1.2.3"},
            {"version": "1.2.4", "hashes": {}},
        )

        self.assertEqual(
            result,
            {
                "detector_status": "update-available",
                "update_available": "true",
                "old_version": "1.2.3",
                "new_version": "1.2.4",
            },
        )

    def test_distinguishes_network_failure(self) -> None:
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            with self.assertRaisesRegex(detect_update.NetworkError, "offline"):
                detect_update.load_json("https://example.test/hashes.json")

    def test_distinguishes_parse_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "hashes.json"
            source.write_text("not json")

            with self.assertRaises(detect_update.ParseError):
                detect_update.load_json(str(source))

    def test_rejects_missing_versions(self) -> None:
        with self.assertRaises(detect_update.ParseError):
            detect_update.compare_versions({}, {"version": "1.2.4"})


if __name__ == "__main__":
    unittest.main()
