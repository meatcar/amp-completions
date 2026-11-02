#!/usr/bin/env python3

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlsplit


DEFAULT_AMP = "amp"
QUERY_TIMEOUT_SECONDS = 10
TOOLS_TIMEOUT_SECONDS = 15
THREAD_LIMIT = 500
CACHE_SECONDS = 300
CACHE_RETENTION_SECONDS = 86_400
FAILURE_BACKOFF_SECONDS = 30
THREAD_CACHE_SECONDS = 30
RECORD_ERRORS = (KeyError, TypeError, ValueError)
COMPLETION_ERRORS = (
    OSError,
    subprocess.SubprocessError,
    json.JSONDecodeError,
    *RECORD_ERRORS,
)

Candidate = tuple[str, str]
T = TypeVar("T")


class PartialResult(Exception):
    def __init__(self, values: list[Candidate]) -> None:
        super().__init__("some queries failed")
        self.values = values


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
    helper = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    key = json.dumps([helper, amp, os.getcwd(), resource, flags, amp_state()])
    return cache_directory() / hashlib.sha256(key.encode()).hexdigest()


def read_cache(path: Path) -> tuple[float, str] | None:
    try:
        return path.stat().st_mtime, path.read_text()
    except OSError:
        return None


def write_cache(path: Path, output: str) -> None:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as file:
            file.write(output)
        os.replace(file.name, path)
    except OSError:
        return
    prune_cache(path.parent)


def prune_cache(directory: Path) -> None:
    cutoff = time.time() - CACHE_RETENTION_SECONDS
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


def parse(output: str) -> list[Candidate]:
    return [(value, description) for value, _, description in (line.partition("\t") for line in output.splitlines())]


def cached_output(path: Path, max_age: float, compute: Callable[[], list[Candidate]]) -> str:
    now = time.time()
    cached = read_cache(path)
    if cached is not None and now - cached[0] < max_age:
        return cached[1]
    failure = path.with_name(f"{path.name}.failed")
    failed = read_cache(failure)
    if failed is not None and now - failed[0] < FAILURE_BACKOFF_SECONDS:
        return failed[1]
    previous = "" if cached is None else cached[1]
    try:
        output = render(compute())
    except PartialResult as partial:
        output = render([*partial.values, *parse(previous)])
    except COMPLETION_ERRORS:
        output = previous
    else:
        write_cache(path, output)
        failure.unlink(missing_ok=True)
        return output
    write_cache(failure, output)
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
    if not isinstance(response, list):
        raise TypeError("expected a list")
    return [item for item in response if isinstance(item, dict)]


def listing(response: object, key: str) -> list[dict[str, object]]:
    if not isinstance(response, dict):
        raise TypeError("expected an object")
    return records(response[key])


def collect(items: Iterable[T], make: Callable[[T], Candidate]) -> list[Candidate]:
    values = []
    for item in items:
        try:
            values.append(make(item))
        except RECORD_ERRORS:
            continue
    return values


def complete_threads(amp: str) -> list[Candidate]:
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
    return collect(records(threads), lambda thread: candidate(thread["id"], thread.get("title")))


def complete_projects(amp: str) -> list[Candidate]:
    return collect(
        records(run_json(amp, ["projects", "list", "--json"])),
        lambda project: candidate(
            f"{text(project['namespace'])}/{text(project['name'])}",
            project.get("repositoryURL"),
        ),
    )


def complete_tools(amp: str) -> list[Candidate]:
    mode = context("mode")
    query = ["tools", "list", *(["--mode", mode] if mode else []), "--json"]
    return collect(
        records(run_json(amp, query, TOOLS_TIMEOUT_SECONDS)),
        lambda tool: candidate(tool["name"], tool.get("description")),
    )


def complete_skills(amp: str) -> list[Candidate]:
    return collect(
        listing(run_json(amp, ["skill", "list", "--json"]), "skills"),
        lambda skill: candidate(skill["name"], skill.get("description")),
    )


def remote_mcp_server(server: dict[str, object], description: object) -> Candidate:
    name = text(server["name"])
    if any(character.isspace() for character in name):
        return candidate(server["id"], name)
    return candidate(name, description)


def complete_mcp_servers(amp: str, *, remote: bool) -> list[Candidate]:
    servers = [
        server
        for server in records(run_json(amp, ["mcp", "list", "--json"]))
        if (server.get("source") == "account") == remote
    ]
    if remote:
        return collect(servers, lambda server: remote_mcp_server(server, server.get("source")))
    return collect(servers, lambda server: candidate(server["name"], server.get("source")))


def remote_mcp_scope() -> list[str]:
    for flag in ("project", "workspace"):
        if value := context(flag):
            return [f"--{flag}", value]
    for flag in ("personal", "current-project"):
        if enabled(flag):
            return [f"--{flag}"]
    return []


def url_host(value: object) -> str:
    # NOTE: Show only the host; MCP URLs can carry tokens in the path or query.
    return urlsplit(text(value)).hostname or ""


def complete_remote_mcp_servers(amp: str) -> list[Candidate]:
    scope = remote_mcp_scope()
    if not scope:
        return complete_mcp_servers(amp, remote=True)
    servers = listing(run_json(amp, ["mcp", "remote", "list", *scope, "--json"]), "servers")
    return collect(servers, lambda server: remote_mcp_server(server, url_host(server.get("url"))))


def model_provider(provider: dict[str, object]) -> Candidate:
    name = text(provider.get("name"))
    provider_type = text(provider.get("type"))
    description = f"{name} ({provider_type})" if name and provider_type else name or provider_type
    return candidate(provider["id"], description)


def complete_model_providers(amp: str) -> list[Candidate]:
    scope = ["--workspace"] if enabled("workspace") else []
    providers = run_json(amp, ["config", "model-providers", "list", *scope, "--json"])
    return collect(records(providers), model_provider)


def complete_domain_scope(amp: str, scope: str) -> list[Candidate]:
    return collect(
        records(run_json(amp, ["domains", "list", scope, "--json"])),
        lambda domain: candidate(domain["hostname"], domain.get("status")),
    )


def complete_domains(amp: str) -> list[Candidate]:
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
    if errors:
        raise PartialResult(values)
    return values


def complete_accounts(amp: str) -> list[Candidate]:
    accounts = collect(
        listing(run_json(amp, ["account", "list", "--json"]), "accounts"),
        lambda account: (text(account.get("email")), first_text(account, "userID", "userId", "id")),
    )
    emails = Counter(email for email, _ in accounts)

    def account_candidate(account: tuple[str, str]) -> Candidate:
        email, user_id = account
        if email and emails[email] == 1:
            return candidate(email, user_id)
        return candidate(user_id, email)

    return collect(accounts, account_candidate)


def complete_runners(amp: str) -> list[Candidate]:
    return collect(
        listing(run_json(amp, ["runner", "list", "--json"]), "runners"),
        lambda runner: candidate(first_text(runner, "id", "runnerID", "runnerId")),
    )


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


def complete_secrets(amp: str) -> list[Candidate]:
    scope = secrets_scope()
    if scope is None:
        return []
    return collect(
        records(run_json(amp, ["secrets", "list", *scope, "--json"])),
        lambda secret: candidate(secret["name"]),
    )


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
        lambda: COMPLETERS[resource](executable),
    )
    write_output(output)


if __name__ == "__main__":
    main()
