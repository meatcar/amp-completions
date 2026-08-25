#!/usr/bin/env python3

import argparse
import json
import subprocess
from pathlib import Path

import update_policy


ALLOWED_FILES = frozenset({"amp-manifest.json", "amp.yaml", "flake.lock"})


def validate_lock_update(base: object, candidate: object) -> str:
    if not isinstance(base, dict) or not isinstance(candidate, dict):
        raise ValueError("flake locks must be JSON objects")
    if {key: value for key, value in base.items() if key != "nodes"} != {
        key: value for key, value in candidate.items() if key != "nodes"
    }:
        raise ValueError("flake lock metadata changed")

    base_nodes = base.get("nodes")
    candidate_nodes = candidate.get("nodes")
    if not isinstance(base_nodes, dict) or not isinstance(candidate_nodes, dict):
        raise ValueError("flake locks have no nodes")
    if set(base_nodes) != set(candidate_nodes):
        raise ValueError("flake lock node set changed")

    changed_nodes = {
        name for name in base_nodes if base_nodes[name] != candidate_nodes[name]
    }
    if changed_nodes != {"llm-agents"}:
        names = ", ".join(sorted(changed_nodes)) or "none"
        raise ValueError(f"expected only llm-agents lock change, changed: {names}")

    llm_agents = candidate_nodes["llm-agents"]
    if not isinstance(llm_agents, dict) or not isinstance(llm_agents.get("locked"), dict):
        raise ValueError("llm-agents lock node is malformed")
    revision = llm_agents["locked"].get("rev")
    if not isinstance(revision, str):
        raise ValueError("llm-agents lock node has no revision")
    return revision


def validate_changed_files(changed_files: set[str]) -> None:
    undeclared = changed_files - ALLOWED_FILES
    if undeclared:
        raise ValueError(f"candidate changes undeclared files: {', '.join(sorted(undeclared))}")
    if not changed_files:
        raise ValueError("candidate has no changes")


def build_pr_body(
    old_version: str,
    new_version: str,
    upstream_revision: str,
    policy_report: str,
) -> str:
    upstream_url = f"https://github.com/numtide/llm-agents.nix/commit/{upstream_revision}"
    return (
        "## Amp completion update\n\n"
        f"{old_version} → {new_version}\n\n"
        f"Upstream: [{upstream_revision[:12]}]({upstream_url})\n\n"
        f"{policy_report}"
    )


def git_output(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def count_generated_diff_lines() -> int:
    lines = 0
    for line in git_output(
        "diff", "--numstat", "--", "amp.yaml", "amp-manifest.json"
    ).splitlines():
        added, removed, _path = line.split("\t", 2)
        if not added.isdigit() or not removed.isdigit():
            raise ValueError("generated diff contains binary data")
        lines += int(added) + int(removed)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and describe an Amp update candidate")
    parser.add_argument("--base-lock", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--policy-json", type=Path, required=True)
    parser.add_argument("--policy-markdown", type=Path, required=True)
    parser.add_argument("--pr-body", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    base_lock = json.loads(arguments.base_lock.read_text())
    candidate_lock = json.loads(Path("flake.lock").read_text())
    upstream_revision = validate_lock_update(base_lock, candidate_lock)

    changed_files = set(git_output("diff", "--name-only").splitlines())
    validate_changed_files(changed_files)
    base_manifest = json.loads(arguments.base_manifest.read_text())
    candidate_manifest = json.loads(Path("amp-manifest.json").read_text())
    new_version = candidate_manifest.get("amp_version")
    if new_version != arguments.expected_version:
        raise ValueError(
            f"detected Amp {arguments.expected_version}, but generated {new_version}"
        )

    result = update_policy.classify_update(
        base_manifest,
        candidate_manifest,
        changed_files=changed_files,
        generated_diff_lines=count_generated_diff_lines(),
    )
    policy_markdown = update_policy.render_markdown(result)
    arguments.policy_json.write_text(json.dumps(result.as_dict(), sort_keys=True) + "\n")
    arguments.policy_markdown.write_text(policy_markdown)
    old_version = base_manifest["amp_version"]
    arguments.pr_body.write_text(
        build_pr_body(old_version, new_version, upstream_revision, policy_markdown)
    )
    arguments.output.write_text(
        f"classification={result.classification}\nupstream_revision={upstream_revision}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
