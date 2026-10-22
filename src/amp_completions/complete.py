#!/usr/bin/env python3

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


DEFAULT_AMP = "amp"
QUERY_TIMEOUT_SECONDS = 5
TOOLS_TIMEOUT_SECONDS = 15
THREAD_LIMIT = 500
CACHE_SECONDS = 300
THREAD_CACHE_SECONDS = 30
COMPLETION_ERRORS = (
    OSError,
    subprocess.SubprocessError,
    json.JSONDecodeError,
    KeyError,
    TypeError,
    ValueError,
)


def run_json(amp: str, arguments: list[str], timeout: float = QUERY_TIMEOUT_SECONDS) -> object:
    result = subprocess.run(
        [amp, *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return json.loads(result.stdout)


def cache_directory() -> Path:
    root = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(root) / "amp-completions"


def read_cache(path: Path) -> tuple[float, object] | None:
    try:
        return path.stat().st_mtime, json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def write_cache(path: Path, response: object) -> None:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as file:
            json.dump(response, file)
        os.replace(file.name, path)
    except OSError:
        pass


def cached_json(
    amp: str,
    arguments: list[str],
    max_age: float = CACHE_SECONDS,
    timeout: float = QUERY_TIMEOUT_SECONDS,
) -> object:
    key = json.dumps([amp, os.getcwd(), arguments])
    path = cache_directory() / hashlib.sha256(key.encode()).hexdigest()
    cached = read_cache(path)
    if cached is not None and time.time() - cached[0] < max_age:
        return cached[1]
    try:
        response = run_json(amp, arguments, timeout)
    except COMPLETION_ERRORS:
        if cached is None:
            raise
        return cached[1]
    write_cache(path, response)
    return response


def context(flag: str) -> str:
    return os.environ.get(f"C_FLAG_{flag}", "")


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
    threads = cached_json(
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
        THREAD_CACHE_SECONDS,
    )
    return [candidate(thread["id"], thread.get("title")) for thread in records(threads)]


def complete_projects(amp: str) -> list[tuple[str, str]]:
    return [
        candidate(
            f"{text(project['namespace'])}/{text(project['name'])}",
            project.get("repositoryURL"),
        )
        for project in records(cached_json(amp, ["projects", "list", "--json"]))
    ]


def complete_tools(amp: str) -> list[tuple[str, str]]:
    mode = context("MODE")
    query = ["tools", "list", *(["--mode", mode] if mode else []), "--json"]
    return [
        candidate(tool["name"], tool.get("description"))
        for tool in records(cached_json(amp, query, timeout=TOOLS_TIMEOUT_SECONDS))
    ]


def complete_skills(amp: str) -> list[tuple[str, str]]:
    response = cached_json(amp, ["skill", "list", "--json"])
    if not isinstance(response, dict):
        raise TypeError("expected an object")
    return [
        candidate(skill["name"], skill.get("description"))
        for skill in records(response["skills"])
    ]


def complete_mcp_servers(amp: str, *, remote: bool) -> list[tuple[str, str]]:
    return [
        candidate(server["name"], server.get("source"))
        for server in records(cached_json(amp, ["mcp", "list", "--json"]))
        if (server.get("source") == "account") == remote
    ]


def remote_mcp_scope() -> list[str]:
    for flag in ("PROJECT", "WORKSPACE"):
        if value := context(flag):
            return [f"--{flag.lower()}", value]
    for flag in ("PERSONAL", "CURRENT_PROJECT"):
        if context(flag) == "true":
            return [f"--{flag.lower().replace('_', '-')}"]
    return []


def complete_remote_mcp_servers(amp: str) -> list[tuple[str, str]]:
    scope = remote_mcp_scope()
    if not scope:
        return complete_mcp_servers(amp, remote=True)
    response = cached_json(amp, ["mcp", "remote", "list", *scope, "--json"])
    if not isinstance(response, dict):
        raise TypeError("expected an object")
    values = []
    for server in records(response["servers"]):
        name = text(server["name"])
        if any(character.isspace() for character in name):
            values.append(candidate(server["id"], name))
        else:
            values.append(candidate(name, server.get("url")))
    return values


def complete_model_providers(amp: str) -> list[tuple[str, str]]:
    values = []
    scope = ["--workspace"] if context("WORKSPACE") == "true" else []
    providers = cached_json(amp, ["config", "model-providers", "list", *scope, "--json"])
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


def complete_domain_scope(amp: str, scope: str) -> list[tuple[str, str]]:
    try:
        domains = cached_json(amp, ["domains", "list", scope, "--json"])
        return [
            candidate(domain["hostname"], domain.get("status")) for domain in records(domains)
        ]
    except COMPLETION_ERRORS:
        return []


def complete_domains(amp: str) -> list[tuple[str, str]]:
    scopes = [
        f"--{flag.lower()}" for flag in ("USER", "WORKSPACE") if context(flag) == "true"
    ] or ["--user", "--workspace"]
    with concurrent.futures.ThreadPoolExecutor() as executor:
        results = executor.map(lambda scope: complete_domain_scope(amp, scope), scopes)
        return [value for values in results for value in values]


COMPLETERS = {
    "domains": complete_domains,
    "local-mcp-servers": lambda amp: complete_mcp_servers(amp, remote=False),
    "model-providers": complete_model_providers,
    "projects": complete_projects,
    "remote-mcp-servers": complete_remote_mcp_servers,
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
