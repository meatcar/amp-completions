import concurrent.futures
import dataclasses
import os
import re
import subprocess
from pathlib import Path


ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
COMMAND = re.compile(
    r"^  (?P<name>[^\s<\[]+)(?: [<\[]\S+)*\s{2,}(?P<summary>.+)$"
)
ARGUMENT_LINE = re.compile(r"^  (?P<token>\S+)(?:\s{2,}(?P<description>.+))?$")
BARE_ARGUMENT = re.compile(r"^[A-Za-z][\w-]*(?:\.\.\.)?$")
BUILTIN_HELP_COMMAND = ("help", "display help for command")
COMMAND_ALIAS = re.compile(r"^\[alias: (?P<aliases>[^]]+)]\s+(?P<description>.+)$")
OPTION_LINE = re.compile(
    r"^  (?P<names>-{1,2}[^\s,]+(?:, -{1,2}[^\s,]+)?)(?: (?P<value><[^>]+>|\[[^]]+]))?"
    r"(?:\s{2,}(?P<description>.+))?$"
)
PLACEHOLDER = re.compile(r"^(?:<(?P<required>[^<>\[\]\s]+)>|\[(?P<optional>[^<>\[\]\s]+)])$")
USAGE_STRUCTURE = frozenset({"[options]", "[command]"})


class HelpFormatError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class Argument:
    name: str
    required: bool = True
    variadic: bool = False
    description: str = ""

    @property
    def signature(self) -> str:
        name = f"{self.name}..." if self.variadic else self.name
        return f"<{name}>" if self.required else f"[{name}]"


@dataclasses.dataclass(frozen=True)
class Option:
    names: tuple[str, ...]
    description: str = ""
    value: Argument | None = None

    @property
    def name(self) -> str:
        return self.canonical.lstrip("-")

    @property
    def canonical(self) -> str:
        return next((name for name in self.names if name.startswith("--")), self.names[0])

    @property
    def spec_key(self) -> str:
        suffix = "" if self.value is None else "=" if self.value.required else "?"
        return ", ".join(self.names) + suffix


@dataclasses.dataclass
class Command:
    name: str
    description: str = ""
    aliases: list[str] = dataclasses.field(default_factory=list)
    options: list[Option] = dataclasses.field(default_factory=list)
    commands: list["Command"] = dataclasses.field(default_factory=list)
    arguments: list[Argument] = dataclasses.field(default_factory=list)


def parse_placeholder(token: str) -> Argument:
    match = PLACEHOLDER.fullmatch(token)
    if not match:
        raise HelpFormatError(f"unrecognized placeholder: {token}")
    name = match["required"] or match["optional"]
    variadic = name.endswith("...")
    return Argument(
        name.removesuffix("..."),
        required=match["required"] is not None,
        variadic=variadic,
    )


def parse_option(declaration: str, description: str = "") -> Option:
    match = OPTION_LINE.fullmatch(f"  {declaration}")
    if not match or match["description"]:
        raise HelpFormatError(f"unrecognized option declaration: {declaration}")
    value = parse_placeholder(match["value"]) if match["value"] else None
    return Option(tuple(match["names"].split(", ")), description, value)


def run_amp(amp: str, arguments: list[str]) -> str:
    result = subprocess.run(
        [amp, *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = ANSI_ESCAPE.sub("", result.stdout)
    return output.replace(str(Path.home()), "~")


def section_lines(help_text: str, title: str) -> list[str]:
    lines = []
    in_section = False
    for line in help_text.splitlines():
        if line == title:
            in_section = True
            continue
        if in_section and line and not line[0].isspace():
            break
        if in_section:
            lines.append(line)
    return lines


def parse_commands(help_text: str) -> list[Command]:
    commands: list[Command] = []
    continues: Command | None = None
    summary_column = None

    for line in section_lines(help_text, "Commands:"):
        indent = len(line) - len(line.lstrip())
        if not line.strip():
            continue
        if indent > 2:
            if continues and indent == summary_column:
                continues.description += f" {line.strip()}"
            elif indent != summary_column:
                continues = None
            continue
        match = COMMAND.match(line)
        if not match:
            raise HelpFormatError(f"unrecognized command line: {line.strip()}")
        summary_column = match.start("summary")
        continues = None
        if (match["name"], match["summary"]) == BUILTIN_HELP_COMMAND:
            continue

        alias = COMMAND_ALIAS.match(match["summary"])
        aliases = alias["aliases"].split(", ") if alias else []
        description = alias["description"] if alias else match["summary"]
        continues = Command(match["name"], description, aliases)
        commands.append(continues)

    return commands


def parse_options(help_text: str) -> list[Option]:
    lines = section_lines(help_text, "Options:")
    options: list[Option] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip():
            continue
        option_line = OPTION_LINE.match(line)
        if not option_line:
            raise HelpFormatError(f"unrecognized option line: {line.strip()}")

        description = [option_line["description"]] if option_line["description"] else []
        while index < len(lines) and not lines[index].startswith("  -"):
            if lines[index].strip():
                description.append(lines[index].strip())
            index += 1
        value = parse_placeholder(option_line["value"]) if option_line["value"] else None
        options.append(
            Option(tuple(option_line["names"].split(", ")), " ".join(description), value)
        )

    return options


def parse_argument_descriptions(help_text: str) -> dict[str, str]:
    descriptions: dict[str, list[str]] = {}
    current = None
    for line in section_lines(help_text, "Arguments:"):
        if line.startswith("  ") and not line.startswith("   "):
            match = ARGUMENT_LINE.match(line)
            token = match["token"] if match else line.strip()
            if BARE_ARGUMENT.fullmatch(token):
                token = f"<{token}>"
            current = parse_placeholder(token).name
            descriptions[current] = [match["description"]] if match and match["description"] else []
        elif line.strip():
            if current is None:
                raise HelpFormatError(f"unrecognized argument line: {line.strip()}")
            descriptions[current].append(line.strip())
    return {name: " ".join(lines) for name, lines in descriptions.items()}


def parse_arguments(help_text: str) -> list[Argument]:
    usage = next((line for line in help_text.splitlines() if line.startswith("Usage: ")), None)
    descriptions = parse_argument_descriptions(help_text)
    if usage is None:
        if descriptions:
            raise HelpFormatError("Arguments section without a Usage line")
        return []

    tokens = usage.removeprefix("Usage: ").split()
    operands = [token for token in tokens if token[0] in "<["]
    if tokens[len(tokens) - len(operands) :] != operands:
        raise HelpFormatError(f"unrecognized usage: {usage}")
    arguments = [
        parse_placeholder(token)
        for token in operands
        if token not in USAGE_STRUCTURE
    ]
    names = [argument.name for argument in arguments]
    if len(names) != len(set(names)) or not set(descriptions) <= set(names):
        raise HelpFormatError(f"usage does not match Arguments section: {usage}")
    return [
        dataclasses.replace(argument, description=descriptions.get(argument.name, ""))
        for argument in arguments
    ]


def parse_command_help(command: Command, path: tuple[str, ...], help_text: str) -> None:
    try:
        command.options = parse_options(help_text)
        command.commands = parse_commands(help_text)
        command.arguments = parse_arguments(help_text)
    except HelpFormatError as error:
        raise HelpFormatError(f"{' '.join(path)}: {error}") from error


def inspect_amp(amp: str) -> tuple[Command, str]:
    workers = min(16, (os.cpu_count() or 1) + 4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        version_result = executor.submit(run_amp, amp, ["version"])
        help_text = run_amp(amp, ["--help"])
        root = Command("amp", "Amp CLI")
        parse_command_help(root, ("amp",), help_text)
        frontier = [([command.name], command) for command in root.commands]

        while frontier:
            help_texts = executor.map(
                lambda item: run_amp(amp, [*item[0], "--help"]),
                frontier,
            )
            next_frontier = []
            for (path, command), command_help in zip(frontier, help_texts, strict=True):
                parse_command_help(command, ("amp", *path), command_help)
                next_frontier.extend(
                    ([*path, child.name], child) for child in command.commands
                )
            frontier = next_frontier

        version = version_result.result().split()[0]
    return root, version
