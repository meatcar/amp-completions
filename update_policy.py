#!/usr/bin/env python3

import dataclasses


ALLOWED_UPDATE_FILES = frozenset({"amp-manifest.json", "amp.yaml", "flake.lock"})
MAX_GENERATED_DIFF_LINES = 2_000


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
    base: dict[str, object],
    candidate: dict[str, object],
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

    for kind, key in (("command", "command_paths"), ("flag", "flag_paths")):
        old_paths = set(base.get(key, []))
        new_paths = set(candidate.get(key, []))
        for path in sorted(old_paths - new_paths):
            reasons.append(f"removed {kind} path: {path}")

    classification = "review-required" if reasons else "safe"
    return PolicyResult(classification, tuple(reasons))
