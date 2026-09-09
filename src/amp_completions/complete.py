#!/usr/bin/env python3

import argparse
import json
import os
import subprocess


DEFAULT_AMP = "amp"
THREAD_PAGE_SIZE = 500
COMPLETION_ERRORS = (
    OSError,
    subprocess.SubprocessError,
    json.JSONDecodeError,
    KeyError,
    TypeError,
)


def run_json(amp: str, arguments: list[str]) -> object:
    result = subprocess.run(
        [amp, *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def complete_threads(amp: str) -> list[tuple[str, str]]:
    values = []
    offset = 0
    while True:
        result = subprocess.run(
            [
                amp,
                "threads",
                "--include-archived",
                "--limit",
                str(THREAD_PAGE_SIZE),
                "--offset",
                str(offset),
                "list",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        threads = json.loads(result.stdout)
        values.extend(
            (thread["id"], thread.get("title") or "") for thread in threads
        )
        if len(threads) < THREAD_PAGE_SIZE:
            return values
        offset += len(threads)


def complete_projects(amp: str) -> list[tuple[str, str]]:
    return [
        (
            f"{project['namespace']}/{project['name']}",
            project.get("repositoryURL") or "",
        )
        for project in run_json(amp, ["projects", "list", "--json"])
    ]


def complete_tools(amp: str) -> list[tuple[str, str]]:
    return [
        (tool["name"], tool.get("description") or "")
        for tool in run_json(amp, ["tools", "list", "--json"])
    ]


def complete_skills(amp: str) -> list[tuple[str, str]]:
    response = run_json(amp, ["skill", "list", "--json"])
    return [
        (skill["name"], skill.get("description") or "")
        for skill in response["skills"]
    ]


def complete_mcp_servers(amp: str, *, remote: bool) -> list[tuple[str, str]]:
    return [
        (server["name"], server.get("source") or "")
        for server in run_json(amp, ["mcp", "list", "--json"])
        if (server.get("source") == "account") == remote
    ]


def complete_model_providers(amp: str) -> list[tuple[str, str]]:
    values = []
    providers = run_json(amp, ["config", "model-providers", "list", "--json"])
    for provider in providers:
        name = provider.get("name") or ""
        provider_type = provider.get("type") or ""
        description = (
            f"{name} ({provider_type})"
            if name and provider_type
            else name or provider_type
        )
        values.append((provider["id"], description))
    return values


def complete_domains(amp: str) -> list[tuple[str, str]]:
    values = []
    for scope in ("--user", "--workspace"):
        try:
            domains = run_json(amp, ["domains", "list", scope, "--json"])
        except COMPLETION_ERRORS:
            continue
        values.extend(
            (domain["hostname"], domain.get("status") or "") for domain in domains
        )
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("resource", choices=COMPLETERS)
    arguments = parser.parse_args()

    try:
        amp = os.environ.get("AMP_BIN", DEFAULT_AMP)
        values = COMPLETERS[arguments.resource](amp)
    except COMPLETION_ERRORS:
        return

    seen = set()
    for value, description in values:
        if value in seen:
            continue
        seen.add(value)
        description = " ".join(description.split())
        if description:
            print(f"{value}\t{description}")
        else:
            print(value)


if __name__ == "__main__":
    main()
