import copy
import unittest

from amp_completions import flake_update_candidate


BASE_LOCK = {
    "version": 7,
    "root": "root",
    "nodes": {
        "root": {
            "inputs": {
                "flake-parts": "flake-parts",
                "llm-agents": "llm-agents",
                "nixpkgs": "nixpkgs",
            }
        },
        "flake-parts": {
            "inputs": {"systems": "systems-old"},
            "locked": {"rev": "parts-old"},
        },
        "llm-agents": {
            "inputs": {"nixpkgs": "llm-nixpkgs"},
            "locked": {"rev": "amp-old"},
        },
        "llm-nixpkgs": {"locked": {"rev": "llm-old"}},
        "nixpkgs": {"locked": {"rev": "nixpkgs-old"}},
        "systems-old": {"locked": {"rev": "systems-old"}},
    },
}


class FlakeUpdateCandidateTest(unittest.TestCase):
    def test_accepts_changes_to_declared_input_closures(self) -> None:
        candidate = copy.deepcopy(BASE_LOCK)
        candidate["nodes"]["nixpkgs"]["locked"]["rev"] = "nixpkgs-new"
        candidate["nodes"]["flake-parts"]["locked"]["rev"] = "parts-new"
        candidate["nodes"]["flake-parts"]["inputs"]["systems"] = "systems-new"
        del candidate["nodes"]["systems-old"]
        candidate["nodes"]["systems-new"] = {"locked": {"rev": "systems-new"}}

        changed = flake_update_candidate.validate_lock_update(
            BASE_LOCK,
            candidate,
            ("flake-parts", "nixpkgs"),
        )

        self.assertEqual(changed, ("flake-parts", "nixpkgs"))

    def test_rejects_llm_agents_revision_change(self) -> None:
        candidate = copy.deepcopy(BASE_LOCK)
        candidate["nodes"]["nixpkgs"]["locked"]["rev"] = "nixpkgs-new"
        candidate["nodes"]["llm-agents"]["locked"]["rev"] = "amp-new"

        with self.assertRaisesRegex(ValueError, "llm-agents"):
            flake_update_candidate.validate_lock_update(
                BASE_LOCK,
                candidate,
                ("flake-parts", "nixpkgs"),
            )

    def test_rejects_llm_agents_transitive_change(self) -> None:
        candidate = copy.deepcopy(BASE_LOCK)
        candidate["nodes"]["nixpkgs"]["locked"]["rev"] = "nixpkgs-new"
        candidate["nodes"]["llm-nixpkgs"]["locked"]["rev"] = "llm-new"

        with self.assertRaisesRegex(ValueError, "llm-agents"):
            flake_update_candidate.validate_lock_update(
                BASE_LOCK,
                candidate,
                ("flake-parts", "nixpkgs"),
            )

    def test_rejects_change_outside_declared_inputs(self) -> None:
        candidate = copy.deepcopy(BASE_LOCK)
        candidate["nodes"]["llm-agents"]["locked"]["rev"] = "amp-new"

        with self.assertRaisesRegex(ValueError, "llm-agents"):
            flake_update_candidate.validate_lock_update(
                BASE_LOCK,
                candidate,
                ("flake-parts", "nixpkgs"),
            )

    def test_rejects_candidate_without_lock_changes(self) -> None:
        with self.assertRaisesRegex(ValueError, "no lock changes"):
            flake_update_candidate.validate_lock_update(
                BASE_LOCK,
                copy.deepcopy(BASE_LOCK),
                ("flake-parts", "nixpkgs"),
            )

    def test_rejects_files_other_than_flake_lock(self) -> None:
        with self.assertRaisesRegex(ValueError, "flake.nix"):
            flake_update_candidate.validate_changed_files({"flake.lock", "flake.nix"})

    def test_builds_pull_request_body(self) -> None:
        body = flake_update_candidate.build_pr_body(("flake-parts", "nixpkgs"))

        self.assertIn("flake-parts", body)
        self.assertIn("nixpkgs", body)
        self.assertIn("llm-agents", body)


if __name__ == "__main__":
    unittest.main()
