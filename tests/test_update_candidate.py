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
    def test_allows_only_unattended_policy_classifications(self) -> None:
        update_candidate.require_unattended(update_policy.PolicyResult("safe", ()))
        update_candidate.require_unattended(
            update_policy.PolicyResult("compatibility-change", ("removed command",))
        )

        with self.assertRaisesRegex(ValueError, "unexpected-policy"):
            update_candidate.require_unattended(
                update_policy.PolicyResult("unexpected-policy", ("unknown result",))
            )

    def test_blocked_candidate_writes_no_outputs(self) -> None:
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
                    mock.patch.object(
                        update_policy,
                        "classify_update",
                        return_value=update_policy.PolicyResult(
                            "review-required", ("blocked",)
                        ),
                    ),
                ):
                    with self.assertRaisesRegex(ValueError, "review-required"):
                        update_candidate.main()
            finally:
                os.chdir(previous_directory)

            self.assertFalse(policy_json.exists())
            self.assertFalse(policy_markdown.exists())
            self.assertFalse(pr_body.exists())
            self.assertFalse(output.exists())

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
