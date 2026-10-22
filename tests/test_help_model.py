import threading
import time
import unittest
from unittest import mock

from amp_completions import help_model


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


class ParseHelpTest(unittest.TestCase):
    def test_parses_only_direct_subcommands(self) -> None:
        commands = help_model.parse_commands(HELP)

        self.assertEqual([command.name for command in commands], ["new", "share"])
        self.assertEqual(commands[0].aliases, ["n"])

    def test_joins_wrapped_command_descriptions(self) -> None:
        commands = help_model.parse_commands(HELP)

        self.assertEqual(
            [command.description for command in commands],
            ["Create a new thread from a prompt", "Share a thread"],
        )

    def test_parses_local_options(self) -> None:
        options = help_model.parse_options(HELP)

        self.assertEqual(
            [(option.spec_key, option.description) for option in options],
            [
                ("--limit=", "Maximum number of threads to return"),
                ("-l, --label=", "Add a label. Repeat the flag for multiple labels."),
                ("-h, --help", "display help for command"),
            ],
        )

    def test_normalizes_optional_arguments(self) -> None:
        option = help_model.parse_option("-x, --execute [message]")

        self.assertEqual(option.spec_key, "-x, --execute?")
        self.assertEqual(option.value, help_model.Argument("message", required=False))

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
            help_model.parse_arguments(help_text),
            [
                help_model.Argument("service", description="MCP server name"),
                help_model.Argument(
                    "tools", required=False, variadic=True, description="MCP tool names"
                ),
            ],
        )

    def test_parses_usage_without_arguments_section(self) -> None:
        self.assertEqual(
            help_model.parse_arguments("Usage: amp update|up [options]\n"),
            [],
        )
        self.assertEqual(
            help_model.parse_arguments("Usage: amp threads color [options] <thread> <color>\n"),
            [help_model.Argument("thread"), help_model.Argument("color")],
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
            help_model.parse_arguments(help_text),
            [help_model.Argument("server-name", description="Name of the MCP server")],
        )
        self.assertEqual(
            [(command.name, command.description) for command in help_model.parse_commands(help_text)],
            [
                ("login", "Register OAuth client credentials for an MCP server"),
                ("logout", "Remove OAuth credentials for an MCP server"),
            ],
        )
        self.assertEqual(
            help_model.parse_options(help_text)[0].description,
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
            [command.description for command in help_model.parse_commands(help_text)],
            [
                'Register a portal for an existing process; use "amp orb service start" for '
                "long-lived servers",
                "Manage long-lived services as supervised processes that survive Amp CLI updates",
            ],
        )
        self.assertEqual(
            help_model.parse_options(help_text)[0].description,
            "list keys of your current workspace",
        )

    def test_rejects_unrecognized_help_lines(self) -> None:
        cases = {
            "option": (help_model.parse_options, "Options:\n  --flag {value}\n"),
            "command": (help_model.parse_commands, "Commands:\n  name\n"),
            "usage": (help_model.parse_arguments, "Usage: amp x <a> extra\n"),
            "argument": (
                help_model.parse_arguments,
                "Usage: amp x <a>\n\nArguments:\n  <b>\n      B\n",
            ),
        }

        for name, (parse, help_text) in cases.items():
            with self.subTest(name=name), self.assertRaises(help_model.HelpFormatError):
                parse(help_text)

    def test_strips_terminal_control_sequences(self) -> None:
        self.assertEqual(help_model.ANSI_ESCAPE.sub("", "\x1b[?25hUsage"), "Usage")


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

        with mock.patch.object(help_model, "run_amp", side_effect=run_amp):
            root, version = help_model.inspect_amp("amp")

        self.assertEqual(version, "1.2.3")
        self.assertEqual([command.name for command in root.commands], ["first", "second"])
        self.assertGreater(maximum_active, 1)


if __name__ == "__main__":
    unittest.main()
