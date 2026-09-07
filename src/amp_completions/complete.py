#!/usr/bin/env python3

import argparse
import json
import os
import subprocess


DEFAULT_AMP = "amp"
THREAD_PAGE_SIZE = 500


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
    result = subprocess.run(
        [amp, "projects", "list", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        (
            f"{project['namespace']}/{project['name']}",
            project.get("repositoryURL") or "",
        )
        for project in json.loads(result.stdout)
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("resource", choices=["projects", "threads"])
    arguments = parser.parse_args()

    try:
        amp = os.environ.get("AMP_BIN", DEFAULT_AMP)
        if arguments.resource == "threads":
            values = complete_threads(amp)
        else:
            values = complete_projects(amp)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError, TypeError):
        return

    for value, description in values:
        description = " ".join(description.split())
        if description:
            print(f"{value}\t{description}")
        else:
            print(value)


if __name__ == "__main__":
    main()
