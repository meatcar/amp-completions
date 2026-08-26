#!/usr/bin/env python3

import argparse
import json
import subprocess
from pathlib import Path


def dependency_closure(nodes: dict[str, object], root: str) -> set[str]:
    pending = [root]
    found = set()
    while pending:
        name = pending.pop()
        if name in found:
            continue
        found.add(name)
        node = nodes.get(name)
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        pending.extend(
            reference for reference in node["inputs"].values() if isinstance(reference, str)
        )
    return found


def closure_snapshot(nodes: dict[str, object], root: str) -> dict[str, object]:
    return {name: nodes.get(name) for name in dependency_closure(nodes, root)}


def validate_lock_update(
    base: object,
    candidate: object,
    input_names: tuple[str, ...],
) -> tuple[str, ...]:
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

    root_name = base.get("root")
    base_root = base_nodes.get(root_name) if isinstance(root_name, str) else None
    candidate_root = candidate_nodes.get(root_name) if isinstance(root_name, str) else None
    if not isinstance(base_root, dict) or not isinstance(candidate_root, dict):
        raise ValueError("flake locks have no root node")
    if base_root != candidate_root:
        raise ValueError("flake lock root changed")
    root_inputs = base_root.get("inputs")
    if not isinstance(root_inputs, dict):
        raise ValueError("flake lock root has no inputs")

    targets = set(input_names)
    target_references = {}
    for name in input_names:
        reference = root_inputs.get(name)
        if not isinstance(reference, str):
            raise ValueError(f"flake lock root has no {name} input")
        target_references[name] = reference

    for name, reference in root_inputs.items():
        if name in targets or not isinstance(reference, str):
            continue
        if closure_snapshot(base_nodes, reference) != closure_snapshot(candidate_nodes, reference):
            raise ValueError(f"lock changed protected {name} input")

    changed_nodes = {
        name
        for name in set(base_nodes) | set(candidate_nodes)
        if base_nodes.get(name) != candidate_nodes.get(name)
    }
    if not changed_nodes:
        raise ValueError("candidate has no lock changes")

    allowed_nodes = set()
    changed_inputs = []
    for name, reference in target_references.items():
        base_snapshot = closure_snapshot(base_nodes, reference)
        candidate_snapshot = closure_snapshot(candidate_nodes, reference)
        allowed_nodes.update(base_snapshot)
        allowed_nodes.update(candidate_snapshot)
        if base_snapshot != candidate_snapshot:
            changed_inputs.append(name)

    unexpected_nodes = changed_nodes - allowed_nodes
    if unexpected_nodes:
        raise ValueError(f"lock changed outside declared inputs: {', '.join(sorted(unexpected_nodes))}")
    return tuple(changed_inputs)


def validate_changed_files(changed_files: set[str]) -> None:
    if changed_files != {"flake.lock"}:
        names = ", ".join(sorted(changed_files)) or "none"
        raise ValueError(f"candidate must change only flake.lock, changed: {names}")


def build_pr_body(changed_inputs: tuple[str, ...]) -> str:
    inputs = "\n".join(f"- `{name}`" for name in changed_inputs)
    return (
        "## Nix flake input update\n\n"
        "Updated root inputs:\n\n"
        f"{inputs}\n\n"
        "The `llm-agents` input and its dependency closure remain unchanged.\n"
    )


def git_output(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a non-Amp flake input update")
    parser.add_argument("--base-lock", type=Path, required=True)
    parser.add_argument("--input", action="append", dest="inputs", required=True)
    parser.add_argument("--pr-body", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    base_lock = json.loads(arguments.base_lock.read_text())
    candidate_lock = json.loads(Path("flake.lock").read_text())
    changed_inputs = validate_lock_update(base_lock, candidate_lock, tuple(arguments.inputs))
    validate_changed_files(set(git_output("diff", "--name-only").splitlines()))
    arguments.pr_body.write_text(build_pr_body(changed_inputs))
    with arguments.output.open("a") as output:
        output.write("update_available=true\n")
        output.write(f"changed_inputs={','.join(changed_inputs)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
