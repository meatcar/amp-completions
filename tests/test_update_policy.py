import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from amp_completions import update_policy


BASE_MANIFEST = {
    "amp_version": "1.2.3",
    "command_aliases": {"amp threads": ["t"]},
    "command_paths": ["amp", "amp threads"],
    "flag_paths": ["amp --help", "amp threads --limit"],
    "manifest_version": 1,
    "persistent_flag_paths": ["amp --help"],
}


def candidate(**changes: object) -> dict[str, object]:
    manifest = {
        "amp_version": "1.2.4",
        "command_aliases": {"amp threads": ["t"]},
        "command_paths": ["amp", "amp threads", "amp threads list"],
        "flag_paths": [
            "amp --help",
            "amp threads --limit",
            "amp threads list --json",
        ],
        "manifest_version": 1,
        "persistent_flag_paths": ["amp --help"],
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

    def test_rejects_alias_removal(self) -> None:
        result = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(command_aliases={}),
        )

        self.assertIn("removed command alias: amp threads -> t", result.reasons)

    def test_rejects_persistent_flag_removal(self) -> None:
        result = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(persistent_flag_paths=[]),
        )

        self.assertIn("removed persistent flag path: amp --help", result.reasons)

    def test_rejects_version_rollback(self) -> None:
        result = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(amp_version="1.2.2"),
        )

        self.assertIn("Amp version rolls back from 1.2.3 to 1.2.2", result.reasons)

    def test_rejects_command_and_flag_count_drops(self) -> None:
        result = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(command_paths=["amp"], flag_paths=["amp --help"]),
        )

        self.assertIn("command count dropped from 2 to 1", result.reasons)
        self.assertIn("flag count dropped from 2 to 1", result.reasons)

    def test_rejects_malformed_manifest(self) -> None:
        result = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(command_paths="amp"),
        )

        self.assertIn("candidate manifest command_paths must be a list of unique strings", result.reasons)

    def test_rejects_unknown_manifest_field(self) -> None:
        result = update_policy.classify_update(
            BASE_MANIFEST,
            candidate(unrecognized=True),
        )

        self.assertIn("candidate manifest has unknown field: unrecognized", result.reasons)

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

    def test_renders_concise_markdown(self) -> None:
        result = update_policy.classify_update(BASE_MANIFEST, candidate(command_paths=["amp"]))

        report = update_policy.render_markdown(result)

        self.assertIn("## Update policy: review required", report)
        self.assertIn("Are these compatibility changes expected for this Amp release?", report)
        self.assertIn("- removed command path: amp threads", report)

    def test_cli_emits_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.json"
            current = root / "current.json"
            report = root / "report.md"
            base.write_text(json.dumps(BASE_MANIFEST))
            current.write_text(json.dumps(candidate()))
            with mock.patch(
                "sys.argv",
                [
                    "update_policy.py",
                    str(base),
                    str(current),
                    "--markdown-output",
                    str(report),
                ],
            ), mock.patch("sys.stdout") as stdout:
                exit_code = update_policy.main()

            self.assertIn("## Update policy: safe", report.read_text())

        self.assertEqual(exit_code, 0)
        emitted = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertEqual(json.loads(emitted)["classification"], "safe")


if __name__ == "__main__":
    unittest.main()
