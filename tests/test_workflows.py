import re
import json
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

    def test_allows_explicit_validation_dispatch(self) -> None:
        self.assertIn("workflow_dispatch:", self.workflow)


class UpdateWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (ROOT / ".github/workflows/update-amp.yml").read_text()

    def test_runs_hourly_and_manually(self) -> None:
        self.assertRegex(self.workflow, r'cron: ["\']17 \* \* \* \*["\']')
        self.assertIn("workflow_dispatch:", self.workflow)

    def test_pins_actions_to_commit_shas(self) -> None:
        action_references = re.findall(r"uses:\s*([^\s]+)", self.workflow)

        self.assertTrue(action_references)
        self.assertTrue(
            all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference) for reference in action_references)
        )

    def test_serializes_detector_runs(self) -> None:
        self.assertIn("group: amp-update", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)

    def test_passes_detector_output_to_later_steps(self) -> None:
        self.assertIn("id: detect", self.workflow)
        self.assertIn("--output \"$GITHUB_OUTPUT\"", self.workflow)

    def test_updates_one_reused_branch_after_validation(self) -> None:
        self.assertIn("BRANCH: automation/amp-update", self.workflow)
        self.assertIn("nix flake update llm-agents", self.workflow)
        self.assertLess(self.workflow.index("nix develop --command make check"), self.workflow.index("git push"))
        self.assertIn("gh pr list --state open", self.workflow)
        self.assertIn("gh pr edit", self.workflow)
        self.assertIn("gh pr create", self.workflow)

    def test_grants_write_only_to_update_workflow(self) -> None:
        self.assertIn("actions: write", self.workflow)
        self.assertIn("contents: write", self.workflow)
        self.assertIn("pull-requests: write", self.workflow)

    def test_reruns_suppressed_validation_for_bot_pull_requests(self) -> None:
        self.assertIn("--event pull_request", self.workflow)
        self.assertIn("action_required", self.workflow)
        self.assertIn('gh run rerun "$validation_run"', self.workflow)
        self.assertNotIn('gh workflow run validate.yml --ref "$BRANCH"', self.workflow)

    def test_labels_every_update_and_auto_merges_only_safe_updates(self) -> None:
        self.assertIn("gh pr edit \"$PULL_REQUEST\" --add-label amp-update", self.workflow)
        self.assertIn('if [ "$CLASSIFICATION" = safe ]; then', self.workflow)
        self.assertIn("--add-label safe-update", self.workflow)
        self.assertIn("gh pr merge \"$PULL_REQUEST\" --auto --squash", self.workflow)
        self.assertIn("--remove-label safe-update", self.workflow)
        self.assertNotIn("gh pr review", self.workflow)

    def test_escalates_repeated_failures_and_persists_state(self) -> None:
        self.assertIn("failure_escalation.py", self.workflow)
        self.assertIn("amp-update-failure", self.workflow)
        self.assertIn("actions/upload-artifact@", self.workflow)
        self.assertIn("if: always()", self.workflow)


class FlakeUpdateWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (ROOT / ".github/workflows/update-flake-inputs.yml").read_text()

    def test_runs_weekly_and_manually(self) -> None:
        self.assertRegex(self.workflow, r'cron: ["\']37 5 \* \* 1["\']')
        self.assertIn("workflow_dispatch:", self.workflow)

    def test_pins_actions_to_commit_shas(self) -> None:
        action_references = re.findall(r"uses:\s*([^\s]+)", self.workflow)

        self.assertTrue(action_references)
        self.assertTrue(
            all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference) for reference in action_references)
        )

    def test_updates_only_non_amp_root_inputs(self) -> None:
        self.assertIn("BRANCH: automation/flake-update", self.workflow)
        self.assertIn(
            "nix flake update nixpkgs flake-parts flake-root treefmt-nix",
            self.workflow,
        )
        self.assertNotIn("nix flake update llm-agents", self.workflow)
        self.assertIn("flake_update_candidate.py", self.workflow)
        self.assertIn("git add flake.lock", self.workflow)

    def test_validates_before_push_and_reuses_one_pull_request(self) -> None:
        self.assertLess(self.workflow.index("nix develop --command make check"), self.workflow.index("git push"))
        self.assertIn("gh pr list --state open", self.workflow)
        self.assertIn("gh pr edit", self.workflow)
        self.assertIn("gh pr create", self.workflow)

    def test_serializes_runs_and_reruns_suppressed_validation(self) -> None:
        self.assertIn("group: flake-input-update", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)
        self.assertIn("action_required", self.workflow)
        self.assertIn('gh run rerun "$validation_run"', self.workflow)

    def test_labels_but_does_not_merge_updates(self) -> None:
        self.assertIn("flake-update", self.workflow)
        self.assertNotIn("gh pr merge", self.workflow)


class RenovateConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((ROOT / ".renovate.json").read_text())

    def test_updates_only_github_actions(self) -> None:
        self.assertEqual(self.config["enabledManagers"], ["github-actions"])
        self.assertNotIn("nix", self.config)

    def test_disables_lock_maintenance_and_automerge(self) -> None:
        self.assertEqual(self.config["lockFileMaintenance"], {"enabled": False})
        self.assertFalse(
            any(rule.get("automerge") for rule in self.config.get("packageRules", []))
        )


if __name__ == "__main__":
    unittest.main()
