import copy
import unittest

import update_candidate


BASE_LOCK = {
    "version": 7,
    "root": "root",
    "nodes": {
        "llm-agents": {"locked": {"rev": "old"}},
        "nixpkgs": {"locked": {"rev": "stable"}},
    },
}


class UpdateCandidateTest(unittest.TestCase):
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
