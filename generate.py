#!/usr/bin/env python3

import argparse
import dataclasses
import json
import re
import subprocess
from pathlib import Path


ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SECTION = re.compile(r"^[A-Z][^:]*:$")
COMMAND = re.compile(
    r"^(?P<indent> +)(?P<name>\S+)\s{2,}(?P<summary>.+)$"
)
COMMAND_ALIAS = re.compile(r"^\[alias: (?P<aliases>[^]]+)]\s+(?P<description>.+)$")
OPTION_LINE = re.compile(
    r"^  (?P<declaration>-{1,2}\S+(?:, -{1,2}\S+)?(?: (?:<[^>]+>|\[[^]]+]))?)"
    r"(?:\s{2,}(?P<description>.+))?$"
)
OPTION_ARGUMENT = re.compile(r"\s+(?P<argument><[^>]+>|\[[^]]+])$")


@dataclasses.dataclass
class Option:
    declaration: str
    description: str


@dataclasses.dataclass
class Command:
    name: str
    description: str = ""
    aliases: list[str] = dataclasses.field(default_factory=list)
    options: list[Option] = dataclasses.field(default_factory=list)
    commands: list["Command"] = dataclasses.field(default_factory=list)


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


def parse_commands(help_text: str) -> list[Command]:
    commands: list[Command] = []
    in_commands = False

    for line in help_text.splitlines():
        if line == "Commands:":
            in_commands = True
            continue
        if in_commands and SECTION.match(line):
            break
        if not in_commands:
            continue

        match = COMMAND.match(line)
        if not match or len(match["indent"]) != 2:
            continue

        alias = COMMAND_ALIAS.match(match["summary"])
        aliases = alias["aliases"].split(", ") if alias else []
        description = alias["description"] if alias else match["summary"]
        commands.append(Command(match["name"], description, aliases))

    return commands


def parse_options(help_text: str) -> list[Option]:
    lines = help_text.splitlines()
    options: list[Option] = []
    in_options = False
    index = 0

    while index < len(lines):
        line = lines[index]
        if line == "Options:":
            in_options = True
            index += 1
            continue
        if in_options and SECTION.match(line):
            break
        option_line = OPTION_LINE.match(line) if in_options else None
        if not option_line:
            index += 1
            continue

        declaration = option_line["declaration"]
        description = [option_line["description"]] if option_line["description"] else []
        index += 1
        while index < len(lines):
            next_line = lines[index]
            if OPTION_LINE.match(next_line) or SECTION.match(next_line):
                break
            if next_line.strip():
                description.append(next_line.strip())
            index += 1
        options.append(Option(normalize_option(declaration), " ".join(description)))

    return options


def normalize_option(declaration: str) -> str:
    argument = OPTION_ARGUMENT.search(declaration)
    if not argument:
        return declaration

    suffix = "=" if argument["argument"].startswith("<") else "?"
    return OPTION_ARGUMENT.sub("", declaration) + suffix


def inspect_command(amp: str, path: list[str], summary: Command) -> Command:
    help_text = run_amp(amp, [*path, "--help"])
    summary.options = parse_options(help_text)
    summary.commands = [
        inspect_command(amp, [*path, child.name], child)
        for child in parse_commands(help_text)
    ]
    return summary


def inspect_amp(amp: str) -> tuple[Command, str]:
    help_text = run_amp(amp, ["--help"])
    root = Command("amp", "Amp CLI", options=parse_options(help_text))
    root.commands = [
        inspect_command(amp, [child.name], child) for child in parse_commands(help_text)
    ]
    version = run_amp(amp, ["version"]).split()[0]
    return root, version


FLAG_COMPLETIONS = {
    "features": ["fast\tFaster serving", "pro\tGPT-5.6 Pro mode"],
    "mode": ["low", "medium", "high", "ultra"],
    "visibility": ["private", "unlisted", "workspace", "group"],
}


def completion_name(declaration: str) -> str:
    names = declaration.rstrip("=?*").split(", ")
    return next((name[2:] for name in names if name.startswith("--")), names[0].lstrip("-"))


def emit_mapping(lines: list[str], indent: int, name: str, values: list[tuple[str, str]]) -> None:
    if not values:
        return
    lines.append(f"{' ' * indent}{name}:")
    for key, value in values:
        description = value.replace("`", "'")
        lines.append(f"{' ' * (indent + 2)}{json.dumps(key)}: {json.dumps(description)}")


def emit_command(command: Command, indent: int, sequence: bool = False) -> list[str]:
    prefix = " " * indent
    first = "- " if sequence else ""
    lines = [f"{prefix}{first}name: {json.dumps(command.name)}"]
    property_indent = indent + (2 if sequence else 0)
    property_prefix = " " * property_indent

    if command.aliases:
        lines.append(f"{property_prefix}aliases: {json.dumps(command.aliases)}")
    if command.description:
        lines.append(f"{property_prefix}description: {json.dumps(command.description)}")

    option_key = "persistentflags" if command.name == "amp" else "flags"
    emit_mapping(
        lines,
        property_indent,
        option_key,
        [(option.declaration, option.description) for option in command.options],
    )

    completions = []
    for option in command.options:
        name = completion_name(option.declaration)
        if name in FLAG_COMPLETIONS:
            completions.append((name, FLAG_COMPLETIONS[name]))
    if completions:
        lines.append(f"{property_prefix}completion:")
        lines.append(f"{property_prefix}  flag:")
        for name, values in completions:
            lines.append(f"{property_prefix}    {json.dumps(name)}: {json.dumps(values)}")

    if command.commands:
        lines.append(f"{property_prefix}commands:")
        for child in command.commands:
            lines.extend(emit_command(child, property_indent + 2, sequence=True))

    return lines


def render(root: Command, version: str) -> str:
    header = [
        "# Generated by generate.py. Do not edit by hand.",
        f"# Amp version: {version}",
        "# yaml-language-server: $schema=https://carapace.sh/schemas/command.json",
    ]
    return "\n".join([*header, *emit_command(root, 0), ""])


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Carapace spec from Amp's help output")
    parser.add_argument("--amp", default="amp", help="path to the Amp executable")
    parser.add_argument("--output", type=Path, default=Path("amp.yaml"))
    arguments = parser.parse_args()

    root, version = inspect_amp(arguments.amp)
    arguments.output.write_text(render(root, version))


if __name__ == "__main__":
    main()
