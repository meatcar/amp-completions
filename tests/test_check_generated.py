import tempfile
import unittest
from pathlib import Path
from unittest import mock

from amp_completions import check_generated


class CheckGeneratedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        (self.root / "amp.yaml").write_text("spec\n")
        (self.root / "amp-manifest.json").write_text("manifest\n")

    def test_accepts_two_matching_generations(self) -> None:
        def generate(_root: Path, _amp: str, spec: Path, manifest: Path) -> None:
            spec.write_text("spec\n")
            manifest.write_text("manifest\n")

        with mock.patch.object(check_generated, "run_generation", side_effect=generate):
            errors = check_generated.check_generated(self.root, "amp")

        self.assertEqual(errors, [])

    def test_reports_stale_file_with_diff(self) -> None:
        def generate(_root: Path, _amp: str, spec: Path, manifest: Path) -> None:
            spec.write_text("new spec\n")
            manifest.write_text("manifest\n")

        with mock.patch.object(check_generated, "run_generation", side_effect=generate):
            errors = check_generated.check_generated(self.root, "amp")

        self.assertIn("--- checked-in/amp.yaml", errors[0])
        self.assertIn("+new spec", errors[0])

    def test_reports_nondeterministic_output_and_removes_temporary_files(self) -> None:
        generated_directories = []
        calls = 0

        def generate(_root: Path, _amp: str, spec: Path, manifest: Path) -> None:
            nonlocal calls
            calls += 1
            generated_directories.append(spec.parent.parent)
            spec.write_text(f"spec {calls}\n")
            manifest.write_text("manifest\n")

        with mock.patch.object(check_generated, "run_generation", side_effect=generate):
            errors = check_generated.check_generated(self.root, "amp")

        self.assertTrue(any("generation is not deterministic" in error for error in errors))
        self.assertTrue(all(not path.exists() for path in generated_directories))


if __name__ == "__main__":
    unittest.main()
