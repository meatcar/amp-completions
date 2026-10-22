import unittest

from amp_completions import completions
from test_generate import tree


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

    def test_reports_rules_whose_field_disappeared(self) -> None:
        resolution = completions.resolve(
            tree(("threads color", [], ["<thread>"]), ("plugins add", ["--target"], []))
        )

        self.assertIn(
            "rule targets no value-taking field: amp threads color <color>",
            resolution.diagnostics,
        )
        self.assertIn(
            "rule targets no value-taking field: amp plugins add --target",
            resolution.diagnostics,
        )
        self.assertNotIn(
            "rule targets no value-taking field: amp threads color <thread>",
            resolution.diagnostics,
        )

    def test_literals_reject_macros_and_whitespace(self) -> None:
        for value in ("$files", "$sh(curl x)", "two words", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                completions.Literals((value,))
        completions.Literals(("fast\tFaster serving",))


if __name__ == "__main__":
    unittest.main()
