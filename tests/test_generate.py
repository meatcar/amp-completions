import importlib.util
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "generate", Path(__file__).parents[1] / "generate.py"
)
generate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(generate)


HELP = """\
Usage: amp threads [options] [command]

Commands:

  new            [alias: n] Create a new thread
  share          [alias: s] Share a thread
    multiplayer  Open or close multiplayer

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
        commands = generate.parse_commands(HELP)

        self.assertEqual([command.name for command in commands], ["new", "share"])
        self.assertEqual(commands[0].aliases, ["n"])

    def test_parses_local_options(self) -> None:
        options = generate.parse_options(HELP)

        self.assertEqual(
            [(option.declaration, option.description) for option in options],
            [
                ("--limit=", "Maximum number of threads to return"),
                ("-l, --label=", "Add a label. Repeat the flag for multiple labels."),
                ("-h, --help", "display help for command"),
            ],
        )

    def test_normalizes_optional_arguments(self) -> None:
        self.assertEqual(generate.normalize_option("-x, --execute [message]"), "-x, --execute?")

    def test_strips_terminal_control_sequences(self) -> None:
        self.assertEqual(generate.ANSI_ESCAPE.sub("", "\x1b[?25hUsage"), "Usage")


class RenderTest(unittest.TestCase):
    def test_renders_aliases_flags_and_known_values(self) -> None:
        command = generate.Command(
            "amp",
            "Amp CLI",
            options=[generate.Option("-m, --mode=", "Set the `mode`")],
            commands=[generate.Command("version", "Print the version")],
        )

        rendered = generate.render(command, "1.2.3")

        self.assertIn('"-m, --mode=": "Set the \'mode\'"', rendered)
        self.assertIn('"mode": ["low", "medium", "high", "ultra"]', rendered)
        self.assertIn('- name: "version"', rendered)


if __name__ == "__main__":
    unittest.main()
