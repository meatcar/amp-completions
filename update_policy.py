#!/usr/bin/env python3

import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path


ALLOWED_UPDATE_FILES = frozenset({"amp-manifest.json", "amp.yaml", "flake.lock"})
MAX_GENERATED_DIFF_LINES = 2_000
MANIFEST_FIELDS = frozenset(
    {
        "amp_version",
        "command_aliases",
        "command_paths",
        "flag_paths",
        "manifest_version",
        "persistent_flag_paths",
    }
)
AMP_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


@dataclasses.dataclass(frozen=True)
class PolicyResult:
    classification: str
    reasons: tuple[str, ...]

    @property
    def summary(self) -> str:
        if not self.reasons:
            return "safe additive update"
        return self.reasons[0]

    def as_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "reasons": list(self.reasons),
        }


def classify_update(
    base: object,
    candidate: object,
    *,
    changed_files: set[str] | frozenset[str] = frozenset(),
    deterministic: bool = True,
    parser_compatible: bool = True,
    generated_diff_lines: int = 0,
) -> PolicyResult:
    reasons = []

    for path in sorted(changed_files - ALLOWED_UPDATE_FILES):
        reasons.append(f"update changes undeclared file: {path}")
    if not deterministic:
        reasons.append("generation is not deterministic")
    if not parser_compatible:
        reasons.append("Amp help output is incompatible with the parser")
    if generated_diff_lines > MAX_GENERATED_DIFF_LINES:
        reasons.append(f"generated diff exceeds {MAX_GENERATED_DIFF_LINES} lines")

    manifest_errors = [
        *validate_manifest(base, "base"),
        *validate_manifest(candidate, "candidate"),
    ]
    if manifest_errors:
        return PolicyResult("review-required", tuple([*reasons, *manifest_errors]))

    assert isinstance(base, dict)
    assert isinstance(candidate, dict)
    old_version = parse_version(base["amp_version"])
    new_version = parse_version(candidate["amp_version"])
    assert old_version is not None and new_version is not None
    if new_version < old_version:
        reasons.append(
            f"Amp version rolls back from {base['amp_version']} to {candidate['amp_version']}"
        )

    path_kinds = (
        ("command", "command_paths"),
        ("flag", "flag_paths"),
        ("persistent flag", "persistent_flag_paths"),
    )
    for kind, key in path_kinds:
        old_paths = set(base[key])
        new_paths = set(candidate[key])
        if kind in {"command", "flag"} and len(new_paths) < len(old_paths):
            reasons.append(f"{kind} count dropped from {len(old_paths)} to {len(new_paths)}")
        for path in sorted(old_paths - new_paths):
            reasons.append(f"removed {kind} path: {path}")

    old_aliases = base["command_aliases"]
    new_aliases = candidate["command_aliases"]
    assert isinstance(old_aliases, dict) and isinstance(new_aliases, dict)
    for command_path, aliases in old_aliases.items():
        new_command_aliases = set(new_aliases.get(command_path, []))
        for alias in sorted(set(aliases) - new_command_aliases):
            reasons.append(f"removed command alias: {command_path} -> {alias}")

    classification = "review-required" if reasons else "safe"
    return PolicyResult(classification, tuple(reasons))


def parse_version(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = AMP_VERSION.fullmatch(value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def validate_manifest(manifest: object, label: str) -> list[str]:
    if not isinstance(manifest, dict):
        return [f"{label} manifest must be a JSON object"]

    reasons = []
    for field in sorted(set(manifest) - MANIFEST_FIELDS):
        reasons.append(f"{label} manifest has unknown field: {field}")
    for field in sorted(MANIFEST_FIELDS - set(manifest)):
        reasons.append(f"{label} manifest is missing field: {field}")
    if reasons:
        return reasons

    if manifest["manifest_version"] != 1:
        reasons.append(f"{label} manifest_version must be 1")
    if parse_version(manifest["amp_version"]) is None:
        reasons.append(f"{label} manifest amp_version is invalid")

    for field in ("command_paths", "flag_paths", "persistent_flag_paths"):
        value = manifest[field]
        if (
            not isinstance(value, list)
            or not all(isinstance(item, str) and item for item in value)
            or len(value) != len(set(value))
        ):
            reasons.append(f"{label} manifest {field} must be a list of unique strings")

    aliases = manifest["command_aliases"]
    if not isinstance(aliases, dict) or any(
        not isinstance(path, str)
        or not path
        or not isinstance(values, list)
        or not values
        or not all(isinstance(alias, str) and alias for alias in values)
        or len(values) != len(set(values))
        for path, values in aliases.items()
    ):
        reasons.append(
            f"{label} manifest command_aliases must map command paths to unique aliases"
        )

    flag_paths = manifest["flag_paths"]
    persistent_paths = manifest["persistent_flag_paths"]
    if isinstance(flag_paths, list) and isinstance(persistent_paths, list):
        if all(isinstance(path, str) for path in [*flag_paths, *persistent_paths]) and not set(
            persistent_paths
        ).issubset(flag_paths):
            reasons.append(f"{label} manifest persistent flags must be flag paths")
    return reasons


def render_markdown(result: PolicyResult) -> str:
    if result.classification == "safe":
        return "## Update policy: safe\n\nSafe additive update.\n"
    reasons = "\n".join(f"- {reason}" for reason in result.reasons)
    return (
        "## Update policy: review required\n\n"
        "Are these compatibility changes expected for this Amp release?\n\n"
        f"{reasons}\n"
    )


def load_manifest(path: Path) -> object:
    return json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify an Amp completion update")
    parser.add_argument("base_manifest", type=Path)
    parser.add_argument("candidate_manifest", type=Path)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--generated-diff-lines", type=int, default=0)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    arguments = parser.parse_args()

    try:
        base = load_manifest(arguments.base_manifest)
        candidate = load_manifest(arguments.candidate_manifest)
        result = classify_update(
            base,
            candidate,
            changed_files=set(arguments.changed_file),
            generated_diff_lines=arguments.generated_diff_lines,
        )
    except (OSError, json.JSONDecodeError) as error:
        result = PolicyResult("review-required", (f"cannot read manifest: {error}",))

    serialized = json.dumps(result.as_dict(), sort_keys=True) + "\n"
    if arguments.json_output:
        arguments.json_output.write_text(serialized)
    else:
        sys.stdout.write(serialized)
    if arguments.markdown_output:
        arguments.markdown_output.write_text(render_markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
