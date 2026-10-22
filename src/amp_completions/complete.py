#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
import sys


DEFAULT_AMP = "amp"
QUERY_TIMEOUT_SECONDS = 5
THREAD_LIMIT = 500
COMPLETION_ERRORS = (
    OSError,
    subprocess.SubprocessError,
    json.JSONDecodeError,
    KeyError,
    TypeError,
    ValueError,
)


def run_json(amp: str, arguments: list[str]) -> object:
    result = subprocess.run(
        [amp, *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=QUERY_TIMEOUT_SECONDS,
    )
    return json.loads(result.stdout)


def text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"expected text, got {type(value).__name__}")
    return value


def candidate(value: object, description: object = None) -> tuple[str, str]:
    value = text(value)
    if not value or any(character.isspace() for character in value):
        raise ValueError(f"invalid completion value: {value!r}")
    return value, text(description)


def records(response: object) -> list[dict[str, object]]:
    if not isinstance(response, list) or not all(isinstance(item, dict) for item in response):
        raise TypeError("expected a list of objects")
    return response


def complete_threads(amp: str) -> list[tuple[str, str]]:
    threads = run_json(
        amp,
        [
            "threads",
            "--include-archived",
            "--limit",
            str(THREAD_LIMIT),
            "--offset",
            "0",
            "list",
            "--json",
        ],
    )
    return [candidate(thread["id"], thread.get("title")) for thread in records(threads)]


def complete_projects(amp: str) -> list[tuple[str, str]]:
    return [
        candidate(
            f"{text(project['namespace'])}/{text(project['name'])}",
            project.get("repositoryURL"),
        )
        for project in records(run_json(amp, ["projects", "list", "--json"]))
    ]


def complete_tools(amp: str) -> list[tuple[str, str]]:
    return [
        candidate(tool["name"], tool.get("description"))
        for tool in records(run_json(amp, ["tools", "list", "--json"]))
    ]


def complete_skills(amp: str) -> list[tuple[str, str]]:
    response = run_json(amp, ["skill", "list", "--json"])
    if not isinstance(response, dict):
        raise TypeError("expected an object")
    return [
        candidate(skill["name"], skill.get("description"))
        for skill in records(response["skills"])
    ]


def complete_mcp_servers(amp: str, *, remote: bool) -> list[tuple[str, str]]:
    return [
        candidate(server["name"], server.get("source"))
        for server in records(run_json(amp, ["mcp", "list", "--json"]))
        if (server.get("source") == "account") == remote
    ]


def complete_model_providers(amp: str) -> list[tuple[str, str]]:
    values = []
    providers = run_json(amp, ["config", "model-providers", "list", "--json"])
    for provider in records(providers):
        name = text(provider.get("name"))
        provider_type = text(provider.get("type"))
        description = (
            f"{name} ({provider_type})"
            if name and provider_type
            else name or provider_type
        )
        values.append(candidate(provider["id"], description))
    return values


def complete_domains(amp: str) -> list[tuple[str, str]]:
    values = []
    for scope in ("--user", "--workspace"):
        try:
            domains = run_json(amp, ["domains", "list", scope, "--json"])
            values.extend(
                candidate(domain["hostname"], domain.get("status"))
                for domain in records(domains)
            )
        except COMPLETION_ERRORS:
            continue
    return values


COMPLETERS = {
    "domains": complete_domains,
    "local-mcp-servers": lambda amp: complete_mcp_servers(amp, remote=False),
    "model-providers": complete_model_providers,
    "projects": complete_projects,
    "remote-mcp-servers": lambda amp: complete_mcp_servers(amp, remote=True),
    "skills": complete_skills,
    "threads": complete_threads,
    "tools": complete_tools,
}


def render(values: list[tuple[str, str]]) -> str:
    lines = []
    seen = set()
    for value, description in values:
        if value in seen:
            continue
        seen.add(value)
        description = " ".join(description.split())
        lines.append(f"{value}\t{description}" if description else value)
    return "".join(f"{line}\n" for line in lines)


def write_output(output: str) -> None:
    try:
        sys.stdout.write(output)
        sys.stdout.flush()
    except BrokenPipeError:
        # NOTE: Python flushes stdout again at exit; point it at devnull to keep that flush silent.
        # see https://docs.python.org/3/library/signal.html#note-on-sigpipe
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("resource", choices=COMPLETERS)
    arguments = parser.parse_args()

    try:
        amp = os.environ.get("AMP_BIN", DEFAULT_AMP)
        output = render(COMPLETERS[arguments.resource](amp))
    except COMPLETION_ERRORS:
        return
    write_output(output)


if __name__ == "__main__":
    main()
