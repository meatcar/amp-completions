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
        "argument_signatures",
        "command_aliases",
        "command_paths",
        "completion_diagnostics",
        "field_completions",
        "flag_paths",
        "manifest_version",
        "persistent_flag_paths",
    }
)
MANIFEST_VERSION = 2
COMPLETION_KINDS = ("literals", "resource", "paths", "exempt")
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
    blocking_reasons = []

    for path in sorted(changed_files - ALLOWED_UPDATE_FILES):
        blocking_reasons.append(f"update changes undeclared file: {path}")
    if not deterministic:
        blocking_reasons.append("generation is not deterministic")
    if not parser_compatible:
        blocking_reasons.append("Amp help output is incompatible with the parser")
    if generated_diff_lines > MAX_GENERATED_DIFF_LINES:
        blocking_reasons.append(f"generated diff exceeds {MAX_GENERATED_DIFF_LINES} lines")

    manifest_errors = [
        *validate_manifest(base, "base"),
        *validate_manifest(candidate, "candidate"),
    ]
    if manifest_errors:
        return PolicyResult(
            "review-required", tuple([*blocking_reasons, *manifest_errors])
        )

    assert isinstance(base, dict)
    assert isinstance(candidate, dict)
    compatibility_reasons = []
    old_version = parse_version(base["amp_version"])
    new_version = parse_version(candidate["amp_version"])
    assert old_version is not None and new_version is not None
    if new_version < old_version:
        blocking_reasons.append(
            f"Amp version rolls back from {base['amp_version']} to {candidate['amp_version']}"
        )
    elif new_version == old_version and candidate["amp_version"] != base["amp_version"]:
        blocking_reasons.append(
            "Amp version changed without advancing from "
            f"{base['amp_version']} to {candidate['amp_version']}"
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
            compatibility_reasons.append(
                f"{kind} count dropped from {len(old_paths)} to {len(new_paths)}"
            )
        for path in sorted(old_paths - new_paths):
            compatibility_reasons.append(f"removed {kind} path: {path}")

    old_aliases = base["command_aliases"]
    new_aliases = candidate["command_aliases"]
    assert isinstance(old_aliases, dict) and isinstance(new_aliases, dict)
    for command_path, aliases in old_aliases.items():
        new_command_aliases = set(new_aliases.get(command_path, []))
        for alias in sorted(set(aliases) - new_command_aliases):
            compatibility_reasons.append(
                f"removed command alias: {command_path} -> {alias}"
            )

    blocking_reasons.extend(
        f"completion diagnostic: {diagnostic}" for diagnostic in candidate["completion_diagnostics"]
    )
    blocking_reasons.extend(lost_completions(base, candidate))
    compatibility_reasons.extend(signature_changes(base, candidate))
    compatibility_reasons.extend(completion_losses(base, candidate))

    if blocking_reasons:
        return PolicyResult(
            "review-required", tuple([*blocking_reasons, *compatibility_reasons])
        )
    if compatibility_reasons:
        return PolicyResult("compatibility-change", tuple(compatibility_reasons))
    return PolicyResult("safe", ())


def signature_changes(base: dict, candidate: dict) -> list[str]:
    new_commands = set(candidate["command_paths"])
    old_signatures = base["argument_signatures"]
    new_signatures = candidate["argument_signatures"]
    return [
        f"changed arguments: {path} from {old_signatures.get(path, '(none)')} "
        f"to {new_signatures.get(path, '(none)')}"
        for path in sorted(set(old_signatures) | set(new_signatures))
        if path in base["command_paths"]
        and path in new_commands
        and old_signatures.get(path) != new_signatures.get(path)
    ]


def lost_completions(base: dict, candidate: dict) -> list[str]:
    new_completions = candidate["field_completions"]
    return [
        f"completion became exempt: {key} (was {completion_kind(old)})"
        for key, old in sorted(base["field_completions"].items())
        if (new := new_completions.get(key)) is not None
        and completion_kind(old) != "exempt"
        and completion_kind(new) == "exempt"
    ]


def completion_losses(base: dict, candidate: dict) -> list[str]:
    reasons = []
    new_completions = candidate["field_completions"]
    for key, old in sorted(base["field_completions"].items()):
        new = new_completions.get(key)
        old_kind = completion_kind(old)
        if new is None or old_kind == "exempt" or completion_kind(new) == "exempt":
            continue
        new_kind = completion_kind(new)
        if new_kind != old_kind:
            reasons.append(f"changed completion: {key} from {old_kind} to {new_kind}")
        elif old_kind == "literals":
            removed = [value for value in old["literals"] if value not in new["literals"]]
            reasons.extend(f"removed completion value: {key} -> {value}" for value in removed)
            if old.get("delimiter") != new.get("delimiter"):
                reasons.append(f"changed completion delimiter: {key}")
        elif old != new:
            reasons.append(f"changed completion: {key} from {old[old_kind]} to {new[new_kind]}")
    return reasons


def completion_kind(completion: dict) -> str:
    return next(kind for kind in COMPLETION_KINDS if kind in completion)


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

    if manifest["manifest_version"] != MANIFEST_VERSION:
        reasons.append(f"{label} manifest_version must be {MANIFEST_VERSION}")
    if parse_version(manifest["amp_version"]) is None:
        reasons.append(f"{label} manifest amp_version is invalid")

    signatures = manifest["argument_signatures"]
    if not isinstance(signatures, dict) or not all(
        isinstance(path, str) and isinstance(signature, str) and path and signature
        for path, signature in signatures.items()
    ):
        reasons.append(f"{label} manifest argument_signatures must map command paths to strings")

    completions = manifest["field_completions"]
    if not isinstance(completions, dict) or not all(
        isinstance(key, str) and valid_completion(completion)
        for key, completion in completions.items()
    ):
        reasons.append(f"{label} manifest field_completions has an invalid entry")

    for field in ("command_paths", "completion_diagnostics", "flag_paths", "persistent_flag_paths"):
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


def valid_completion(completion: object) -> bool:
    if not isinstance(completion, dict):
        return False
    kinds = [kind for kind in COMPLETION_KINDS if kind in completion]
    if len(kinds) != 1:
        return False
    kind = kinds[0]
    if kind == "literals":
        values = completion["literals"]
        return (
            set(completion) <= {"literals", "delimiter"}
            and isinstance(values, list)
            and all(isinstance(value, str) and value for value in values)
            and isinstance(completion.get("delimiter", ""), str)
        )
    return set(completion) == {kind} and isinstance(completion[kind], str)


def render_markdown(result: PolicyResult) -> str:
    if result.classification == "safe":
        return "## Update policy: safe\n\nSafe additive update.\n"
    reasons = "\n".join(f"- {reason}" for reason in result.reasons)
    if result.classification == "compatibility-change":
        return (
            "## Update policy: compatibility changes\n\n"
            "This validated update will merge automatically. Compatibility changes:\n\n"
            f"{reasons}\n"
        )
    return (
        "## Update policy: review required\n\n"
        "This update cannot merge automatically:\n\n"
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
