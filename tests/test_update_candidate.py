import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from amp_completions import update_candidate, update_policy


BASE_LOCK = {
    "version": 7,
    "root": "root",
    "nodes": {
        "root": {
            "inputs": {
                "llm-agents": "llm-agents",
                "nixpkgs": "nixpkgs",
            }
        },
        "llm-agents": {
            "inputs": {"nixpkgs": "llm-nixpkgs"},
            "locked": {"rev": "old"},
        },
        "llm-nixpkgs": {"locked": {"rev": "llm-old"}},
        "nixpkgs": {"locked": {"rev": "stable"}},
    },
}


class UpdateCandidateTest(unittest.TestCase):
    def test_review_required_candidate_is_described_for_review(self) -> None:
        outputs = self.run_main(update_policy.PolicyResult("review-required", ("blocked",)))

        self.assertIn("classification=review-required\n", outputs["output"])
        self.assertIn("unattended=false\n", outputs["output"])
        self.assertIn("## Update policy: review required", outputs["pr_body"])
        self.assertIn("- blocked", outputs["pr_body"])

    def test_unattended_candidates_are_marked_for_merge(self) -> None:
        for classification in ("safe", "compatibility-change"):
            with self.subTest(classification=classification):
                outputs = self.run_main(update_policy.PolicyResult(classification, ()))

                self.assertIn(f"classification={classification}\n", outputs["output"])
                self.assertIn("unattended=true\n", outputs["output"])

    def test_unknown_classification_writes_no_outputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "unexpected-policy"):
            self.run_main(update_policy.PolicyResult("unexpected-policy", ("unknown result",)))

    def run_main(self, result: update_policy.PolicyResult) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_lock = root / "base-lock.json"
            base_manifest = root / "base-manifest.json"
            policy_json = root / "policy.json"
            policy_markdown = root / "policy.md"
            pr_body = root / "pr-body.md"
            output = root / "output"
            base_lock.write_text(json.dumps(BASE_LOCK))
            base_manifest.write_text(json.dumps({"amp_version": "1.2.3"}))
            (root / "flake.lock").write_text(json.dumps(BASE_LOCK))
            (root / "amp-manifest.json").write_text(json.dumps({"amp_version": "1.2.4"}))

            arguments = [
                "update_candidate.py",
                "--base-lock",
                str(base_lock),
                "--base-manifest",
                str(base_manifest),
                "--expected-version",
                "1.2.4",
                "--policy-json",
                str(policy_json),
                "--policy-markdown",
                str(policy_markdown),
                "--pr-body",
                str(pr_body),
                "--output",
                str(output),
            ]
            previous_directory = Path.cwd()
            try:
                os.chdir(root)
                with (
                    mock.patch("sys.argv", arguments),
                    mock.patch.object(update_candidate, "validate_lock_update", return_value="rev"),
                    mock.patch.object(
                        update_candidate,
                        "git_output",
                        return_value="amp-manifest.json\namp.yaml\nflake.lock\n",
                    ),
                    mock.patch.object(update_candidate, "count_generated_diff_lines", return_value=1),
                    mock.patch.object(update_policy, "classify_update", return_value=result),
                ):
                    update_candidate.main()
            except ValueError:
                for path in (policy_json, policy_markdown, pr_body, output):
                    self.assertFalse(path.exists(), path)
                raise
            finally:
                os.chdir(previous_directory)

            return {"output": output.read_text(), "pr_body": pr_body.read_text()}

    def test_accepts_only_llm_agents_lock_change(self) -> None:
        candidate = copy.deepcopy(BASE_LOCK)
        candidate["nodes"]["llm-agents"]["locked"]["rev"] = "new"

        revision = update_candidate.validate_lock_update(BASE_LOCK, candidate)

        self.assertEqual(revision, "new")

    def test_rejects_other_lock_changes(self) -> None:
        candidate = copy.deepcopy(BASE_LOCK)
        candidate["nodes"]["llm-agents"]["locked"]["rev"] = "new"
        candidate["nodes"]["nixpkgs"]["locked"]["rev"] = "changed"

        with self.assertRaisesRegex(ValueError, "nixpkgs"):
            update_candidate.validate_lock_update(BASE_LOCK, candidate)

    def test_accepts_transitive_llm_agents_lock_changes(self) -> None:
        candidate = copy.deepcopy(BASE_LOCK)
        candidate["nodes"]["llm-agents"]["locked"]["rev"] = "new"
        candidate["nodes"]["llm-nixpkgs"]["locked"]["rev"] = "llm-new"

        revision = update_candidate.validate_lock_update(BASE_LOCK, candidate)

        self.assertEqual(revision, "new")

    def test_rejects_undeclared_candidate_file(self) -> None:
        with self.assertRaisesRegex(ValueError, "README.md"):
            update_candidate.validate_changed_files(
                {"amp.yaml", "amp-manifest.json", "flake.lock", "README.md"}
            )

    def test_builds_body_with_versions_policy_and_upstream_commit(self) -> None:
        body = update_candidate.build_pr_body(
            "1.2.3",
            "1.2.4",
            "abcdef",
            "## Update policy: safe\n\nSafe additive update.\n",
        )

        self.assertIn("1.2.3 → 1.2.4", body)
        self.assertIn("numtide/llm-agents.nix/commit/abcdef", body)
        self.assertIn("## Update policy: safe", body)


if __name__ == "__main__":
    unittest.main()
