import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class ValidationWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (ROOT / ".github/workflows/validate.yml").read_text()

    def test_pins_actions_to_commit_shas(self) -> None:
        action_references = re.findall(r"uses:\s*([^\s]+)", self.workflow)

        self.assertTrue(action_references)
        self.assertTrue(
            all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference) for reference in action_references)
        )

    def test_uses_read_only_permissions_and_cancels_superseded_runs(self) -> None:
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertIn("cancel-in-progress: true", self.workflow)

    def test_runs_local_validation_commands(self) -> None:
        self.assertIn("run: nix flake check", self.workflow)
        self.assertIn("run: nix develop --command make check", self.workflow)


class UpdateWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (ROOT / ".github/workflows/update-amp.yml").read_text()

    def test_runs_hourly_and_manually(self) -> None:
        self.assertRegex(self.workflow, r'cron: ["\']17 \* \* \* \*["\']')
        self.assertIn("workflow_dispatch:", self.workflow)

    def test_serializes_detector_runs(self) -> None:
        self.assertIn("group: amp-update", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)

    def test_passes_detector_output_to_later_steps(self) -> None:
        self.assertIn("id: detect", self.workflow)
        self.assertIn("--output \"$GITHUB_OUTPUT\"", self.workflow)


if __name__ == "__main__":
    unittest.main()
