#!/usr/bin/env python3

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/numtide/llm-agents.nix/"
    "main/packages/amp/hashes.json"
)


class NetworkError(Exception):
    pass


class ParseError(Exception):
    pass


def load_json(source: str) -> object:
    try:
        if source.startswith(("https://", "http://")):
            with urllib.request.urlopen(source, timeout=30) as response:
                content = response.read().decode()
        else:
            content = Path(source).read_text()
    except urllib.error.URLError as error:
        raise NetworkError(str(error.reason)) from error
    except OSError as error:
        raise ParseError(f"cannot read {source}: {error}") from error

    try:
        return json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ParseError(f"invalid JSON from {source}: {error}") from error


def compare_versions(manifest: object, upstream: object) -> dict[str, str]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("amp_version"), str):
        raise ParseError("manifest has no Amp version")
    if not isinstance(upstream, dict) or not isinstance(upstream.get("version"), str):
        raise ParseError("upstream hashes have no Amp version")

    old_version = manifest["amp_version"]
    new_version = upstream["version"]
    update_available = old_version != new_version
    return {
        "detector_status": "update-available" if update_available else "no-update",
        "update_available": str(update_available).lower(),
        "old_version": old_version,
        "new_version": new_version,
    }


def write_output(path: Path, values: dict[str, str]) -> None:
    with path.open("a") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def run(manifest_path: Path, source: str, output: Path) -> int:
    manifest = load_json(str(manifest_path))
    upstream = load_json(source)
    write_output(output, compare_versions(manifest, upstream))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect a new llm-agents.nix Amp version")
    parser.add_argument("--manifest", type=Path, default=Path("amp-manifest.json"))
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    try:
        return run(arguments.manifest, arguments.source, arguments.output)
    except NetworkError as error:
        write_output(arguments.output, {"detector_status": "network-error"})
        print(f"network error: {error}", file=sys.stderr)
        return 2
    except ParseError as error:
        write_output(arguments.output, {"detector_status": "parse-error"})
        print(f"parse error: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
