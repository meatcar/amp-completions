import argparse
import concurrent.futures
import dataclasses
import json
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


FLAG_COMPLETIONS = {
    "api-format": ["chat-completions", "responses", "anthropic-messages"],
    "auth": ["oauth", "bearer", "none"],
    "context": ["thread", "subagent"],
    "features": ["fast\tFaster serving", "pro\tGPT-5.6 Pro mode"],
    "log-level": ["debug", "info", "warn", "error", "audit"],
    "mode": ["low", "medium", "high", "ultra"],
    "orb-size": ["a1.tiny", "a1.small", "a1.medium", "a1.large", "a1.xxlarge"],
    "reasoning-effort": ["none", "minimal", "low", "medium", "high", "xhigh", "max"],
    "ship-behavior": ["ship", "push-to-branch", "custom"],
    "subject-scope": ["project", "thread", "user", "workspace"],
    "visibility": ["private", "unlisted", "workspace", "group"],
}
PATH_FLAG_COMPLETIONS = {
    ("amp", "plugins", "add", "target"): ["system", "workspace"],
    ("amp", "plugins", "remove", "target"): ["system", "workspace"],
    ("amp", "projects", "snapshots", "delete", "resource"): [
        "a1.tiny",
        "a1.small",
        "a1.medium",
        "a1.large",
        "a1.xxlarge",
    ],
    ("amp", "skill", "add", "target"): ["$directories"],
    ("amp", "skill", "remove", "target"): ["$directories"],
}
PATH_DYNAMIC_FLAG_COMPLETIONS = {
    ("amp", "apps", "deploy", "domain"): "domains",
    (
        "amp",
        "config",
        "model-providers",
        "check-access",
        "provider-key",
    ): "model-providers",
}
FILE_COMPLETION_FLAGS = {
    "icon",
    "log-file",
    "mcp-config",
    "output",
    "settings-file",
}
DIRECTORY_COMPLETION_FLAGS = {"cwd", "repository"}
DYNAMIC_FLAG_COMPLETIONS = {
    "project": "projects",
    "thread": "threads",
    "thread-id": "threads",
}
DYNAMIC_COMPLETION_RESOURCES = {
    "domains",
    "local-mcp-servers",
    "model-providers",
    "projects",
    "remote-mcp-servers",
    "skills",
    "threads",
    "tools",
}
POSITIONAL_COMPLETIONS = {
    ("amp", "orb", "system-metrics"): "threads",
    ("amp", "projects", "delete"): "projects",
    ("amp", "projects", "gallery-media", "get"): "projects",
    ("amp", "projects", "gallery-media", "set"): "projects",
    ("amp", "projects", "get"): "projects",
    ("amp", "projects", "snapshots", "delete"): "projects",
    ("amp", "projects", "snapshots", "list"): "projects",
    ("amp", "projects", "update"): "projects",
    ("amp", "threads", "archive"): "threads",
    ("amp", "threads", "delete"): "threads",
    ("amp", "threads", "export"): "threads",
    ("amp", "threads", "label"): "threads",
    ("amp", "threads", "markdown"): "threads",
    ("amp", "threads", "raw"): "threads",
    ("amp", "threads", "rename"): "threads",
    ("amp", "threads", "share"): "threads",
    ("amp", "threads", "share", "multiplayer", "off"): "threads",
    ("amp", "threads", "share", "multiplayer", "on"): "threads",
    ("amp", "threads", "share", "multiplayer", "ttl"): "threads",
    ("amp", "threads", "usage"): "threads",
    ("amp", "tools", "show"): "tools",
    ("amp", "skill", "info"): "skills",
    ("amp", "skill", "remove"): "skills",
    ("amp", "mcp", "remove"): "local-mcp-servers",
    ("amp", "mcp", "remote", "check"): "remote-mcp-servers",
    ("amp", "mcp", "remote", "login"): "remote-mcp-servers",
    ("amp", "mcp", "remote", "logout"): "remote-mcp-servers",
    ("amp", "mcp", "remote", "remove"): "remote-mcp-servers",
    ("amp", "mcp", "remote", "tools"): "remote-mcp-servers",
    ("amp", "mcp", "remote", "update"): "remote-mcp-servers",
    ("amp", "config", "model-providers", "activate"): "model-providers",
    ("amp", "config", "model-providers", "deactivate"): "model-providers",
    ("amp", "config", "model-providers", "delete"): "model-providers",
    ("amp", "config", "model-providers", "edit-key"): "model-providers",
    ("amp", "config", "model-providers", "show"): "model-providers",
    ("amp", "config", "model-providers", "test"): "model-providers",
    ("amp", "domains", "check"): "domains",
    ("amp", "domains", "remove"): "domains",
}
POSITIONAL_SEQUENCE_COMPLETIONS = {
    ("amp", "apps", "deploy"): [[], ["$directories"]],
    ("amp", "clone"): [[], ["$directories"]],
    ("amp", "config", "model-providers", "setup-guide"): [
        [
            "ollama-cloud",
            "openrouter",
            "vercel",
            "cloudflare",
            "google-cloud-agent-platform",
            "amazon-bedrock",
            "opencode-go",
            "custom-url",
        ]
    ],
    ("amp", "permissions", "add"): [
        ["allow", "reject", "ask", "delegate"],
        ["tools"],
    ],
    ("amp", "permissions", "test"): [["tools"]],
    ("amp", "skill", "add"): [["$files", "$directories"]],
    ("amp", "threads", "color"): [
        ["threads"],
        ["blue", "purple", "pink", "red", "orange", "yellow", "green", "cyan"],
    ],
    ("amp", "threads", "visibility"): [["private", "workspace", "group"]],
}
POSITIONAL_ANY_COMPLETIONS = {
    ("amp", "threads", "continue"): "threads",
}


def emit_mapping(lines: list[str], indent: int, name: str, values: list[tuple[str, str]]) -> None:
    if not values:
        return
    lines.append(f"{' ' * indent}{name}:")
    for key, value in values:
        description = value.replace("`", "'")
        lines.append(f"{' ' * (indent + 2)}{json.dumps(key)}: {json.dumps(description)}")


def dynamic_completion(resource: str) -> str:
    helper = '"${XDG_CONFIG_HOME:-$HOME/.config}/carapace/bin/amp-completions"'
    return f"$sh({helper} {resource})"


def emit_command(
    command: Command,
    indent: int,
    sequence: bool = False,
    parents: tuple[str, ...] = (),
) -> list[str]:
    prefix = " " * indent
    first = "- " if sequence else ""
    lines = [f"{prefix}{first}name: {json.dumps(command.name)}"]
    property_indent = indent + (2 if sequence else 0)
    property_prefix = " " * property_indent
    path = (*parents, command.name)

    if command.aliases:
        lines.append(f"{property_prefix}aliases: {json.dumps(command.aliases)}")
    if command.description:
        lines.append(f"{property_prefix}description: {json.dumps(command.description)}")

    option_key = "persistentflags" if command.name == "amp" else "flags"
    emit_mapping(
        lines,
        property_indent,
        option_key,
        [(option.spec_key, option.description) for option in command.options],
    )

    completions = []
    for option in command.options:
        name = option.name
        path_completion = PATH_FLAG_COMPLETIONS.get((*path, name))
        path_dynamic_completion = PATH_DYNAMIC_FLAG_COMPLETIONS.get((*path, name))
        if path_completion:
            completions.append((name, path_completion))
        elif path_dynamic_completion:
            completions.append((name, [dynamic_completion(path_dynamic_completion)]))
        elif name in FLAG_COMPLETIONS:
            completions.append((name, FLAG_COMPLETIONS[name]))
        elif name in DYNAMIC_FLAG_COMPLETIONS:
            resource = DYNAMIC_FLAG_COMPLETIONS[name]
            completions.append((name, [dynamic_completion(resource)]))
        elif name.endswith("-file") or name in FILE_COMPLETION_FLAGS:
            completions.append((name, ["$files"]))
        elif name in DIRECTORY_COMPLETION_FLAGS:
            completions.append((name, ["$directories"]))
    positional = POSITIONAL_COMPLETIONS.get(path)
    positional_sequence = POSITIONAL_SEQUENCE_COMPLETIONS.get(path)
    positional_any = POSITIONAL_ANY_COMPLETIONS.get(path)
    if completions or positional or positional_sequence or positional_any:
        lines.append(f"{property_prefix}completion:")
        if completions:
            lines.append(f"{property_prefix}  flag:")
            for name, values in completions:
                lines.append(f"{property_prefix}    {json.dumps(name)}: {json.dumps(values)}")
        if positional:
            lines.append(f"{property_prefix}  positional:")
            lines.append(
                f"{property_prefix}    - {json.dumps([dynamic_completion(positional)])}"
            )
        if positional_sequence:
            lines.append(f"{property_prefix}  positional:")
            for values in positional_sequence:
                resolved = [
                    dynamic_completion(value)
                    if value in DYNAMIC_COMPLETION_RESOURCES
                    else value
                    for value in values
                ]
                lines.append(f"{property_prefix}    - {json.dumps(resolved)}")
        if positional_any:
            lines.append(
                f"{property_prefix}  positionalany: "
                f"{json.dumps([dynamic_completion(positional_any)])}"
            )

    if command.commands:
        lines.append(f"{property_prefix}commands:")
        for child in command.commands:
            lines.extend(
                emit_command(
                    child,
                    property_indent + 2,
                    sequence=True,
                    parents=path,
                )
            )

    return lines


def render(root: Command, version: str) -> str:
    header = [
        "# Generated by generate.py. Do not edit by hand.",
        f"# Amp version: {version}",
        "# yaml-language-server: $schema=https://carapace.sh/schemas/command.json",
    ]
    return "\n".join([*header, *emit_command(root, 0), ""])


def build_manifest(root: Command, version: str) -> dict[str, object]:
    command_paths = []
    command_aliases = {}
    flag_paths = []
    persistent_flag_paths = []

    def visit(command: Command, parents: tuple[str, ...]) -> None:
        path = (*parents, command.name)
        command_path = " ".join(path)
        command_paths.append(command_path)
        if command.aliases:
            command_aliases[command_path] = sorted(command.aliases)
        for option in command.options:
            flag_path = f"{command_path} {option.canonical}"
            flag_paths.append(flag_path)
            if command is root:
                persistent_flag_paths.append(flag_path)
        for child in command.commands:
            visit(child, path)

    visit(root, ())
    return {
        "amp_version": version,
        "command_aliases": dict(sorted(command_aliases.items())),
        "command_paths": sorted(command_paths),
        "flag_paths": sorted(flag_paths),
        "manifest_version": 1,
        "persistent_flag_paths": sorted(persistent_flag_paths),
    }


def render_manifest(root: Command, version: str) -> str:
    return json.dumps(build_manifest(root, version), indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Carapace spec from Amp's help output")
    parser.add_argument("--amp", default="amp", help="path to the Amp executable")
    parser.add_argument("--output", type=Path, default=Path("amp.yaml"))
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=Path("amp-manifest.json"),
    )
    arguments = parser.parse_args()

    root, version = inspect_amp(arguments.amp)
    arguments.output.write_text(render(root, version))
    arguments.manifest_output.write_text(render_manifest(root, version))


if __name__ == "__main__":
    main()
