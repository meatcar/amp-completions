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
from collections.abc import Callable
from pathlib import Path


DEFAULT_AMP = "amp"
QUERY_TIMEOUT_SECONDS = 5
TOOLS_TIMEOUT_SECONDS = 15
THREAD_LIMIT = 500
CACHE_SECONDS = 300
CACHE_RETENTION_SECONDS = 86_400
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


def xdg_directory(variable: str, default: str) -> Path:
    return Path(os.environ.get(variable) or Path.home() / default)


def cache_directory() -> Path:
    return xdg_directory("XDG_CACHE_HOME", ".cache") / "amp-completions"


def workspace_roots() -> list[Path]:
    cwd = Path.cwd()
    git_root = next((path for path in (cwd, *cwd.parents) if (path / ".git").exists()), cwd)
    return sorted({cwd, git_root})


def amp_state() -> list[object]:
    # NOTE: Amp writes these only on login, account switch, or settings edits.
    directories = [
        xdg_directory("XDG_DATA_HOME", ".local/share") / "amp",
        xdg_directory("XDG_CONFIG_HOME", ".config") / "amp",
        *(root / ".amp" for root in workspace_roots()),
    ]
    files = []
    for directory in directories:
        try:
            with os.scandir(directory) as entries:
                files.extend(entry.path for entry in entries if entry.is_file())
        except OSError:
            continue
    if settings_file := os.environ.get("AMP_SETTINGS_FILE"):
        files.append(settings_file)
    state: list[object] = [os.environ.get(name) for name in ("AMP_API_KEY", "AMP_URL")]
    for file in sorted(files):
        try:
            stat = os.stat(file)
        except OSError:
            continue
        state.append([file, stat.st_mtime_ns, stat.st_size])
    return state


def cache_path(amp: str, resource: str) -> Path:
    flags = sorted((name, value) for name, value in os.environ.items() if name.startswith("C_FLAG_"))
    key = json.dumps([amp, os.getcwd(), resource, flags, amp_state()])
    return cache_directory() / hashlib.sha256(key.encode()).hexdigest()


def read_cache(path: Path) -> tuple[float, str] | None:
    try:
        return path.stat().st_mtime, path.read_text()
    except OSError:
        return None


def write_cache(path: Path, output: str) -> None:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as file:
            file.write(output)
        os.replace(file.name, path)
    except OSError:
        return
    prune_cache(path.parent)


def prune_cache(directory: Path) -> None:
    cutoff = time.time() - CACHE_RETENTION_SECONDS
    for entry in directory.iterdir():
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


def cached_output(path: Path, max_age: float, compute: Callable[[], str]) -> str:
    cached = read_cache(path)
    if cached is not None and time.time() - cached[0] < max_age:
        return cached[1]
    try:
        output = compute()
    except COMPLETION_ERRORS:
        return "" if cached is None else cached[1]
    write_cache(path, output)
    return output


def flag_variable(flag: str) -> str:
    # NOTE: Carapace keeps dashes, e.g. C_FLAG_CURRENT-PROJECT, and passes a bare optional flag as " ".
    return f"C_FLAG_{flag.upper()}"


def context(flag: str) -> str:
    return os.environ.get(flag_variable(flag), "").strip()


def enabled(flag: str) -> bool:
    return context(flag) == "true"


def text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"expected text, got {type(value).__name__}")
    return value


def first_text(record: dict[str, object], *fields: str) -> str:
    return next((value for field in fields if (value := text(record.get(field)))), "")


def candidate(value: object, description: object = None) -> tuple[str, str]:
    value = text(value)
    if not value or any(character.isspace() for character in value):
        raise ValueError(f"invalid completion value: {value!r}")
    return value, text(description)


def records(response: object) -> list[dict[str, object]]:
    if not isinstance(response, list) or not all(isinstance(item, dict) for item in response):
        raise TypeError("expected a list of objects")
    return response


def listing(response: object, key: str) -> list[dict[str, object]]:
    if not isinstance(response, dict):
        raise TypeError("expected an object")
    return records(response[key])


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
    mode = context("mode")
    query = ["tools", "list", *(["--mode", mode] if mode else []), "--json"]
    return [
        candidate(tool["name"], tool.get("description"))
        for tool in records(run_json(amp, query, TOOLS_TIMEOUT_SECONDS))
    ]


def complete_skills(amp: str) -> list[tuple[str, str]]:
    return [
        candidate(skill["name"], skill.get("description"))
        for skill in listing(run_json(amp, ["skill", "list", "--json"]), "skills")
    ]


def complete_mcp_servers(amp: str, *, remote: bool) -> list[tuple[str, str]]:
    return [
        candidate(server["name"], server.get("source"))
        for server in records(run_json(amp, ["mcp", "list", "--json"]))
        if (server.get("source") == "account") == remote
    ]


def remote_mcp_scope() -> list[str]:
    for flag in ("project", "workspace"):
        if value := context(flag):
            return [f"--{flag}", value]
    for flag in ("personal", "current-project"):
        if enabled(flag):
            return [f"--{flag}"]
    return []


def complete_remote_mcp_servers(amp: str) -> list[tuple[str, str]]:
    scope = remote_mcp_scope()
    if not scope:
        return complete_mcp_servers(amp, remote=True)
    values = []
    for server in listing(run_json(amp, ["mcp", "remote", "list", *scope, "--json"]), "servers"):
        name = text(server["name"])
        if any(character.isspace() for character in name):
            values.append(candidate(server["id"], name))
        else:
            values.append(candidate(name, server.get("url")))
    return values


def complete_model_providers(amp: str) -> list[tuple[str, str]]:
    values = []
    scope = ["--workspace"] if enabled("workspace") else []
    providers = run_json(amp, ["config", "model-providers", "list", *scope, "--json"])
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
    domains = run_json(amp, ["domains", "list", scope, "--json"])
    return [candidate(domain["hostname"], domain.get("status")) for domain in records(domains)]


def complete_domains(amp: str) -> list[tuple[str, str]]:
    scopes = [f"--{flag}" for flag in ("user", "workspace") if enabled(flag)] or [
        "--user",
        "--workspace",
    ]
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(complete_domain_scope, amp, scope) for scope in scopes]
    values = []
    errors = []
    for future in futures:
        try:
            values.extend(future.result())
        except COMPLETION_ERRORS as error:
            errors.append(error)
    if len(errors) == len(futures):
        raise errors[0]
    return values


def complete_accounts(amp: str) -> list[tuple[str, str]]:
    values = []
    for account in listing(run_json(amp, ["account", "list", "--json"]), "accounts"):
        user_id = first_text(account, "userID", "userId", "id")
        email = text(account.get("email"))
        values.append(candidate(email, user_id) if email else candidate(user_id))
    return values


def complete_runners(amp: str) -> list[tuple[str, str]]:
    return [
        candidate(first_text(runner, "id", "runnerID", "runnerId"))
        for runner in listing(run_json(amp, ["runner", "list", "--json"]), "runners")
    ]


def secrets_scope() -> list[str] | None:
    for flag in ("user", "workspace"):
        if enabled(flag):
            return [f"--{flag}"]
    if machine := context("perma-orb"):
        deployment = context("deployment")
        return ["--perma-orb", machine, *(["--deployment", deployment] if deployment else [])]
    if flag_variable("project") in os.environ:
        project = context("project")
        return ["--project", *([project] if project else [])]
    return None


def complete_secrets(amp: str) -> list[tuple[str, str]]:
    scope = secrets_scope()
    if scope is None:
        return []
    return [
        candidate(secret["name"])
        for secret in records(run_json(amp, ["secrets", "list", *scope, "--json"]))
    ]


COMPLETERS = {
    "accounts": complete_accounts,
    "domains": complete_domains,
    "local-mcp-servers": lambda amp: complete_mcp_servers(amp, remote=False),
    "model-providers": complete_model_providers,
    "projects": complete_projects,
    "remote-mcp-servers": complete_remote_mcp_servers,
    "runners": complete_runners,
    "secrets": complete_secrets,
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
    resource = parser.parse_args().resource

    executable = os.environ.get("AMP_BIN", DEFAULT_AMP)
    max_age = THREAD_CACHE_SECONDS if resource == "threads" else CACHE_SECONDS
    output = cached_output(
        cache_path(executable, resource),
        max_age,
        lambda: render(COMPLETERS[resource](executable)),
    )
    write_output(output)


if __name__ == "__main__":
    main()
