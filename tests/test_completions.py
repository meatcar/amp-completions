import unittest

from amp_completions import completions, help_model
from test_generate import tree


def visibility(description: str) -> completions.Resolution:
    option = help_model.parse_option("--visibility <visibility>", description)
    return completions.resolve(help_model.Command("amp", options=[option]))


class ResolveTest(unittest.TestCase):
    def test_reports_fields_without_rules(self) -> None:
        resolution = completions.resolve(tree(("future", ["--widget <widget>"], ["<gadget>"])))

        self.assertIn("no completion rule: amp future --widget", resolution.diagnostics)
        self.assertIn("no completion rule: amp future <gadget>", resolution.diagnostics)

    def test_exempt_fields_are_covered_without_completion(self) -> None:
        resolution = completions.resolve(tree(("threads search", ["--limit <number>"], ["<query>"])))

        self.assertFalse(any("no completion rule" in d for d in resolution.diagnostics))
        self.assertIsInstance(
            resolution.completions[("amp", "threads", "search", "<query>")], completions.Exempt
        )

    def test_rules_whose_field_disappeared_are_stale_not_blocking(self) -> None:
        resolution = completions.resolve(
            tree(("threads color", [], ["<thread>"]), ("plugins add", ["--target"], []))
        )

        self.assertIn(
            "rule targets no value-taking field: amp threads color <color>",
            resolution.stale_rules,
        )
        self.assertIn(
            "rule targets no value-taking field: amp plugins add --target",
            resolution.stale_rules,
        )
        self.assertNotIn(
            "rule targets no value-taking field: amp threads color <thread>",
            resolution.stale_rules,
        )
        self.assertFalse(
            any("rule targets" in d or "unused" in d for d in resolution.diagnostics),
            resolution.diagnostics,
        )

    def test_documented_values_follow_help_text(self) -> None:
        resolution = visibility("Set thread visibility (private, workspace, or secret)")

        self.assertEqual(
            resolution.completions[("amp", "--visibility")],
            completions.Literals(("private", "workspace", "secret")),
        )

    def test_changed_value_documentation_drops_completion_and_reports_it(self) -> None:
        resolution = visibility("Set thread visibility; see the docs")

        self.assertNotIn(("amp", "--visibility"), resolution.completions)
        self.assertIn(
            "help no longer documents values: amp --visibility", resolution.diagnostics
        )

    def test_unsafe_documented_values_are_reported(self) -> None:
        resolution = visibility("Set thread visibility (private, $files)")

        self.assertNotIn(("amp", "--visibility"), resolution.completions)
        self.assertTrue(
            any("invalid literal completion" in d for d in resolution.diagnostics),
            resolution.diagnostics,
        )

    def test_literals_reject_macros_and_whitespace(self) -> None:
        for value in ("$files", "$sh(curl x)", "two words", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                completions.Literals((value,))
        completions.Literals(("fast\tFaster serving",))


if __name__ == "__main__":
    unittest.main()
