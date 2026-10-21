import argparse
import json
import subprocess
import sys
from pathlib import PurePosixPath


CHECK_NAME = "merge-gate"
BASE_BRANCH = "main"
ALLOWED_FILES = {"README.md", "amp-manifest.json", "amp.yaml", "flake.lock"}
ALLOWED_DIRECTORIES = {"src", "tests"}
MAX_COMPARE_FILES = 300


def is_allowed_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if ".." in parts:
        return False
    return path in ALLOWED_FILES or (len(parts) > 1 and parts[0] in ALLOWED_DIRECTORIES)


def evaluate(repository: str, pull: dict, files: list[dict]) -> list[str]:
    violations = []
    if pull["state"] != "open":
        violations.append(f"pull request is {pull['state']}")
    base = pull["base"]
    if base["repo"]["full_name"] != repository or base["ref"] != BASE_BRANCH:
        violations.append(f"base is {base['repo']['full_name']}:{base['ref']}, not {BASE_BRANCH}")
    head_repo = pull["head"]["repo"]
    if head_repo is None or head_repo["full_name"] != repository:
        name = head_repo["full_name"] if head_repo else "missing"
        violations.append(f"head repository {name} is not {repository}")
    if len(files) >= MAX_COMPARE_FILES:
        violations.append(f"diff lists {len(files)} files; GitHub truncates at {MAX_COMPARE_FILES}")
    for file in files:
        paths = [file.get("previous_filename"), file["filename"]]
        violations.extend(
            f"{path} is outside the unattended merge allowlist"
            for path in paths
            if path and not is_allowed_path(path)
        )
    return violations


def check_run(head_sha: str, violations: list[str]) -> dict[str, object]:
    if violations:
        conclusion = "failure"
        title = "Needs human review"
        summary = "\n".join(f"- {violation}" for violation in violations)
    else:
        conclusion = "success"
        title = "Allowed for unattended merge"
        summary = "All changed files are inside the unattended merge allowlist."
    return {
        "name": CHECK_NAME,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {"title": title, "summary": summary},
    }


def gh(*arguments: str, stdin: str | None = None) -> dict:
    result = subprocess.run(
        ["gh", *arguments], check=True, capture_output=True, input=stdin, text=True
    )
    return json.loads(result.stdout)


def snapshot(pull: dict) -> tuple[str, str, str]:
    return pull["head"]["sha"], pull["base"]["sha"], pull["base"]["ref"]


def report(repository: str, pull_request: int) -> int:
    pull_path = f"repos/{repository}/pulls/{pull_request}"
    pull = gh("api", pull_path)
    head_sha, base_sha, _ = snapshot(pull)
    comparison = gh("api", f"repos/{repository}/compare/{base_sha}...{head_sha}")
    if snapshot(gh("api", pull_path)) != snapshot(pull):
        print("pull request changed during evaluation", file=sys.stderr)
        return 1

    violations = evaluate(repository, pull, comparison.get("files", []))
    payload = json.dumps(check_run(head_sha, violations))
    gh("api", "--method", "POST", f"repos/{repository}/check-runs", "--input", "-", stdin=payload)
    for violation in violations:
        print(violation, file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report whether a pull request may merge unattended as a check run"
    )
    parser.add_argument("--repository", required=True, help="owner/name")
    parser.add_argument("--pull-request", type=int, required=True)
    arguments = parser.parse_args()
    return report(arguments.repository, arguments.pull_request)


if __name__ == "__main__":
    raise SystemExit(main())
