import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


GATE_PATH = Path(__file__).parents[1] / ".github/scripts/merge_gate.py"
spec = importlib.util.spec_from_file_location("merge_gate", GATE_PATH)
merge_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge_gate)

REPOSITORY = "meatcar/amp-completions"
BASE_SHA = "2222222222222222222222222222222222222222"
OLD_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
NEW_SHA = "1111111111111111111111111111111111111111"


def pull(
    head_repository: str | None = REPOSITORY,
    head_sha: str = NEW_SHA,
    base_sha: str = BASE_SHA,
    base_ref: str = "main",
    base_repository: str = REPOSITORY,
    state: str = "open",
) -> dict:
    head_repo = {"full_name": head_repository} if head_repository else None
    return {
        "state": state,
        "head": {"repo": head_repo, "sha": head_sha},
        "base": {"repo": {"full_name": base_repository}, "ref": base_ref, "sha": base_sha},
    }


def changed(filename: str, status: str = "modified", **extra: str) -> dict[str, str]:
    return {"filename": filename, "status": status, **extra}


class MergeGateTest(unittest.TestCase):
    def violations(self, pull_request: dict, files: list[dict]) -> list[str]:
        return merge_gate.evaluate(REPOSITORY, pull_request, files)

    def test_allows_same_repository_changes_to_generated_and_source_files(self) -> None:
        files = [
            changed("amp.yaml"),
            changed("amp-manifest.json"),
            changed("flake.lock"),
            changed("src/amp_completions/generate.py"),
            changed("tests/test_merge_gate.py", "added"),
            changed("README.md"),
        ]

        self.assertEqual(self.violations(pull(), files), [])

    def test_rejects_fork_and_deleted_head_repositories(self) -> None:
        files = [changed("src/amp_completions/generate.py")]

        self.assertEqual(
            self.violations(pull(head_repository="other/amp-completions"), files),
            ["head repository other/amp-completions is not meatcar/amp-completions"],
        )
        self.assertEqual(
            self.violations(pull(head_repository=None), files),
            ["head repository missing is not meatcar/amp-completions"],
        )

    def test_rejects_pull_requests_not_open_against_main(self) -> None:
        files = [changed("amp.yaml")]
        cases = {
            "closed": (pull(state="closed"), "pull request is closed"),
            "other branch": (
                pull(base_ref="release"),
                "base is meatcar/amp-completions:release, not main",
            ),
            "other repository": (
                pull(base_repository="other/amp-completions"),
                "base is other/amp-completions:main, not main",
            ),
        }
        for name, (pull_request, violation) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.violations(pull_request, files), [violation])

    def test_rejects_protected_paths(self) -> None:
        for path in [
            ".github/workflows/validate.yml",
            ".github/scripts/merge_gate.py",
            ".agents/setup",
            ".amp/plugins/automation-guard.ts",
            "AGENTS.md",
            "CLAUDE.md",
            "flake.nix",
            "nix/flake-modules/devshell.nix",
            "renovate.json",
            "Makefile",
            "src2/evil.py",
            "amp.yaml.orig",
            "src/../flake.nix",
        ]:
            with self.subTest(path=path):
                self.assertEqual(
                    self.violations(pull(), [changed(path)]),
                    [f"{path} is outside the unattended merge allowlist"],
                )

    def test_checks_both_sides_of_a_rename(self) -> None:
        files = [changed("src/agents.md", "renamed", previous_filename="AGENTS.md")]

        self.assertEqual(
            self.violations(pull(), files),
            ["AGENTS.md is outside the unattended merge allowlist"],
        )

    def test_rejects_possibly_truncated_diff(self) -> None:
        files = [changed(f"src/file{index}.py") for index in range(300)]

        self.assertEqual(
            self.violations(pull(), files),
            ["diff lists 300 files; GitHub truncates at 300"],
        )
        self.assertEqual(self.violations(pull(), files[:299]), [])

    def report(self, files: list[dict], pulls: list[dict]) -> tuple[int, list, list]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pulls.json").write_text(json.dumps(pulls))
            (root / "files.json").write_text(json.dumps(files))
            fake = root / "gh"
            fake.write_text(FAKE_GH)
            fake.chmod(0o755)
            environment = {"PATH": f"{root}:{os.environ['PATH']}", "FAKE_GH": str(root)}
            with (
                mock.patch.dict(os.environ, environment),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                exit_code = merge_gate.report(REPOSITORY, 7)
            posted = [json.loads(line) for line in (root / "posted.jsonl").read_text().splitlines()]
            requested = (root / "requested.txt").read_text().splitlines()
        return exit_code, posted, requested

    def test_reports_check_run_for_evaluated_head(self) -> None:
        exit_code, posted, requested = self.report(
            [changed("amp.yaml"), changed("flake.nix")], [pull(), pull()]
        )

        self.assertEqual(exit_code, 0)
        self.assertIn(f"repos/{REPOSITORY}/compare/{BASE_SHA}...{NEW_SHA}", requested)
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0]["path"], f"repos/{REPOSITORY}/check-runs")
        check = posted[0]["body"]
        self.assertEqual(
            (check["name"], check["head_sha"], check["conclusion"]),
            ("merge-gate", NEW_SHA, "failure"),
        )
        self.assertIn("flake.nix", check["output"]["summary"])

    def test_does_not_report_when_pull_request_moves_during_evaluation(self) -> None:
        cases = {
            "head": pull(head_sha=OLD_SHA),
            "base sha": pull(base_sha=OLD_SHA),
            "base ref": pull(base_ref="release"),
        }
        for name, first in cases.items():
            with self.subTest(name):
                exit_code, posted, _ = self.report([changed("amp.yaml")], [first, pull()])

                self.assertEqual(exit_code, 1)
                self.assertEqual(posted, [])


FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

root = Path(os.environ["FAKE_GH"])
arguments = sys.argv[1:]
path = next(argument for argument in arguments[1:] if argument.startswith("repos/"))
posted = root / "posted.jsonl"
posted.touch()
with (root / "requested.txt").open("a") as requested:
    requested.write(path + "\\n")
if "--method" in arguments:
    with posted.open("a") as output:
        output.write(json.dumps({"path": path, "body": json.load(sys.stdin)}) + "\\n")
    print("{}")
elif "/compare/" in path:
    print(json.dumps({"files": json.loads((root / "files.json").read_text())}))
else:
    pulls = json.loads((root / "pulls.json").read_text())
    print(json.dumps(pulls.pop(0)))
    (root / "pulls.json").write_text(json.dumps(pulls))
"""

if __name__ == "__main__":
    unittest.main()
