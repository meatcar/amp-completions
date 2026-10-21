import re
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
WAIT_FOR_GATE = (
    '.github/scripts/wait-for-merge-gate "${{ github.repository }}" "$HEAD_SHA" "$MERGE_GATE_APP_ID"'
)


class ValidationWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (ROOT / ".github/workflows/validate.yml").read_text()

    def test_pins_actions_to_commit_shas(self) -> None:
        action_references = re.findall(r"uses:\s*([^\s]+)(?:\s+#\s+(\S+))?", self.workflow)

        self.assertTrue(action_references)
        self.assertTrue(
            all(
                re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference) and version
                for reference, version in action_references
            )
        )

    def test_uses_read_only_permissions_and_cancels_superseded_runs(self) -> None:
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertIn("cancel-in-progress: true", self.workflow)

    def test_runs_all_validation_through_the_flake(self) -> None:
        self.assertIn("run: nix flake check", self.workflow)
        self.assertNotIn("make check", self.workflow)

    def test_allows_explicit_validation_dispatch(self) -> None:
        self.assertIn("workflow_dispatch:", self.workflow)


class UpdateWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (ROOT / ".github/workflows/update-amp.yml").read_text()

    def test_runs_hourly_and_manually(self) -> None:
        self.assertRegex(self.workflow, r'cron: ["\']\d+ \* \* \* \*["\']')
        self.assertIn("workflow_dispatch:", self.workflow)

    def test_pins_actions_to_commit_shas(self) -> None:
        action_references = re.findall(r"uses:\s*([^\s]+)(?:\s+#\s+(\S+))?", self.workflow)

        self.assertTrue(action_references)
        self.assertTrue(
            all(
                re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference) and version
                for reference, version in action_references
            )
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
        self.assertIn(
            "nix build .#amp-completions --no-link --print-out-paths",
            self.workflow,
        )
        self.assertIn('cp "$generated/share/carapace/specs/amp.yaml" amp.yaml', self.workflow)
        self.assertIn(
            'cp "$generated/share/amp-completions/amp-manifest.json" amp-manifest.json',
            self.workflow,
        )
        self.assertNotIn("nix develop --command make generate", self.workflow)
        self.assertLess(self.workflow.index("nix flake check"), self.workflow.index("git push"))
        self.assertNotIn("make check", self.workflow)
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

    def test_merges_validated_update_only_against_its_checked_base(self) -> None:
        self.assertIn("gh pr edit \"$PULL_REQUEST\" --add-label amp-update", self.workflow)
        self.assertIn('if [ "$CLASSIFICATION" = safe ]; then', self.workflow)
        self.assertIn("--add-label safe-update", self.workflow)
        self.assertIn("--remove-label safe-update", self.workflow)
        self.assertIn('gh run watch "$VALIDATION_RUN" --exit-status', self.workflow)
        self.assertIn('gh pr checks "$PULL_REQUEST" --required', self.workflow)
        self.assertIn("base_sha=$(git rev-parse origin/", self.workflow)
        self.assertIn('if [ "$latest_base_sha" != "$BASE_SHA" ]; then', self.workflow)
        self.assertIn('--match-head-commit "$HEAD_SHA"', self.workflow)
        self.assertNotIn("gh pr merge \"$PULL_REQUEST\" --auto", self.workflow)
        self.assertNotIn("gh pr review", self.workflow)

    def test_requests_merge_gate_before_merging(self) -> None:
        self.assertIn("gh workflow run merge-gate.yml", self.workflow)
        self.assertLess(
            self.workflow.index(WAIT_FOR_GATE),
            self.workflow.index('gh pr checks "$PULL_REQUEST" --required'),
        )

    def test_locks_failure_issues_against_outside_comments(self) -> None:
        self.assertLess(
            self.workflow.index("--label amp-update-failure"),
            self.workflow.index('/issues/$issue/lock"'),
        )

    def test_escalates_repeated_failures_and_persists_state(self) -> None:
        self.assertIn("python3 -m amp_completions.failure_escalation", self.workflow)
        self.assertIn("amp-update-failure", self.workflow)
        self.assertIn("actions/upload-artifact@", self.workflow)
        self.assertIn("if: always()", self.workflow)


class MergeGateWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (ROOT / ".github/workflows/merge-gate.yml").read_text()

    def test_pins_actions_to_commit_shas(self) -> None:
        action_references = re.findall(r"uses:\s*([^\s]+)(?:\s+#\s+(\S+))?", self.workflow)

        self.assertTrue(action_references)
        self.assertTrue(
            all(
                re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference) and version
                for reference, version in action_references
            )
        )

    def test_runs_trusted_base_code_without_pull_request_checkout(self) -> None:
        self.assertIn("pull_request_target:", self.workflow)
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertNotRegex(self.workflow, r"\n  pull_request:")
        self.assertNotIn("ref:", self.workflow)
        self.assertNotIn("head.sha", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)

    def test_reports_with_environment_scoped_app_token(self) -> None:
        self.assertIn("permissions:\n  contents: read\n", self.workflow)
        self.assertIn("environment: merge-gate", self.workflow)
        self.assertIn("secrets.MERGE_GATE_PRIVATE_KEY", self.workflow)
        self.assertIn("GH_TOKEN: ${{ steps.app.outputs.token }}", self.workflow)
        self.assertNotIn("github.token", self.workflow)

    def test_runs_gate_script_isolated_from_repository_modules(self) -> None:
        self.assertIn("python3 -I .github/scripts/merge_gate.py", self.workflow)
        self.assertNotIn("PYTHONPATH", self.workflow)

    def test_reevaluates_when_base_branch_is_edited(self) -> None:
        self.assertIn("      - edited\n", self.workflow)


class FlakeUpdateWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (ROOT / ".github/workflows/update-flake-inputs.yml").read_text()

    def test_runs_weekly_and_manually(self) -> None:
        self.assertRegex(self.workflow, r'cron: ["\']\d+ \d+ \* \* \d["\']')
        self.assertIn("workflow_dispatch:", self.workflow)

    def test_pins_actions_to_commit_shas(self) -> None:
        action_references = re.findall(r"uses:\s*([^\s]+)(?:\s+#\s+(\S+))?", self.workflow)

        self.assertTrue(action_references)
        self.assertTrue(
            all(
                re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference) and version
                for reference, version in action_references
            )
        )

    def test_updates_only_non_amp_root_inputs(self) -> None:
        self.assertIn("BRANCH: automation/flake-update", self.workflow)
        self.assertIn(
            "nix flake update nixpkgs flake-parts flake-root treefmt-nix",
            self.workflow,
        )
        self.assertNotIn("nix flake update llm-agents", self.workflow)
        self.assertIn("python3 -m amp_completions.flake_update_candidate", self.workflow)
        self.assertIn("git add flake.lock", self.workflow)

    def test_validates_before_push_and_reuses_one_pull_request(self) -> None:
        self.assertLess(self.workflow.index("nix flake check"), self.workflow.index("git push"))
        self.assertNotIn("make check", self.workflow)
        self.assertIn("gh pr list --state open", self.workflow)
        self.assertIn("gh pr edit", self.workflow)
        self.assertIn("gh pr create", self.workflow)

    def test_serializes_runs_and_reruns_suppressed_validation(self) -> None:
        self.assertIn("group: flake-input-update", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)
        self.assertIn("action_required", self.workflow)
        self.assertIn('gh run rerun "$validation_run"', self.workflow)

    def test_merges_only_after_validation_and_merge_gate(self) -> None:
        self.assertIn("flake-update", self.workflow)
        self.assertIn("gh workflow run merge-gate.yml", self.workflow)
        self.assertLess(
            self.workflow.index('gh run watch "$VALIDATION_RUN" --exit-status'),
            self.workflow.index(WAIT_FOR_GATE),
        )
        self.assertLess(
            self.workflow.index('gh pr checks "$PULL_REQUEST" --required'),
            self.workflow.index("gh pr merge"),
        )
        self.assertIn("base_sha=$(git rev-parse origin/", self.workflow)
        self.assertLess(
            self.workflow.index('if [ "$latest_base_sha" != "$BASE_SHA" ]; then'),
            self.workflow.index("gh pr merge"),
        )
        self.assertIn('--match-head-commit "$HEAD_SHA"', self.workflow)


class RenovateConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((ROOT / "renovate.json").read_text())

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
