import unittest

import update_policy


BASE_MANIFEST = {
    "amp_version": "1.2.3",
    "command_paths": ["amp", "amp threads"],
    "flag_paths": ["amp --help", "amp threads --limit"],
}


def candidate(**changes: object) -> dict[str, object]:
    manifest = {
        "amp_version": "1.2.4",
        "command_paths": ["amp", "amp threads", "amp threads list"],
        "flag_paths": [
            "amp --help",
            "amp threads --limit",
            "amp threads list --json",
        ],
    }
    manifest.update(changes)
    return manifest


class UpdatePolicyTest(unittest.TestCase):
    def test_accepts_additive_deterministic_generated_update(self) -> None:
        result = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(),
            changed_files=update_policy.ALLOWED_UPDATE_FILES,
            generated_diff_lines=update_policy.MAX_GENERATED_DIFF_LINES,
        )

        self.assertEqual(result.as_dict(), {"classification": "safe", "reasons": []})

    def test_rejects_command_removal(self) -> None:
        result = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(command_paths=["amp"]),
        )

        self.assertEqual(result.classification, "review-required")
        self.assertIn("removed command path: amp threads", result.reasons)

    def test_rejects_flag_removal(self) -> None:
        result = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(flag_paths=["amp --help"]),
        )

        self.assertIn("removed flag path: amp threads --limit", result.reasons)

    def test_rejects_parser_incompatibility(self) -> None:
        result = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(),
            parser_compatible=False,
        )

        self.assertIn("Amp help output is incompatible with the parser", result.reasons)

    def test_rejects_nondeterministic_generation(self) -> None:
        result = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(),
            deterministic=False,
        )

        self.assertIn("generation is not deterministic", result.reasons)

    def test_rejects_undeclared_file(self) -> None:
        result = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(),
            changed_files={"amp.yaml", "README.md"},
        )

        self.assertIn("update changes undeclared file: README.md", result.reasons)

    def test_generated_diff_limit_boundary(self) -> None:
        accepted = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(),
            generated_diff_lines=update_policy.MAX_GENERATED_DIFF_LINES,
        )
        rejected = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(),
            generated_diff_lines=update_policy.MAX_GENERATED_DIFF_LINES + 1,
        )

        self.assertEqual(accepted.classification, "safe")
        self.assertIn(
            f"generated diff exceeds {update_policy.MAX_GENERATED_DIFF_LINES} lines",
            rejected.reasons,
        )


if __name__ == "__main__":
    unittest.main()
