import argparse
import difflib
import os
import subprocess
import sys
import tempfile
from pathlib import Path


GENERATED_FILES = ("amp.yaml", "amp-manifest.json")


def run_generation(root: Path, amp: str, spec: Path, manifest: Path) -> None:
    root = root.resolve()
    environment = os.environ.copy()
    source_path = str(root / "src")
    if python_path := environment.get("PYTHONPATH"):
        source_path = os.pathsep.join((source_path, python_path))
    environment["PYTHONPATH"] = source_path
    subprocess.run(
        [
            sys.executable,
            "-m",
            "amp_completions.generate",
            "--amp",
            amp,
            "--output",
            str(spec),
            "--manifest-output",
            str(manifest),
        ],
        check=True,
        cwd=root,
        env=environment,
    )


def file_diff(expected: Path, actual: Path, expected_label: str, actual_label: str) -> str:
    return "".join(
        difflib.unified_diff(
            expected.read_text().splitlines(keepends=True),
            actual.read_text().splitlines(keepends=True),
            fromfile=expected_label,
            tofile=actual_label,
        )
    )


def check_generated(root: Path, amp: str) -> list[str]:
    errors = []
    with tempfile.TemporaryDirectory(prefix="amp-completions-check-") as directory:
        temporary_root = Path(directory)
        first = temporary_root / "first"
        second = temporary_root / "second"
        first.mkdir()
        second.mkdir()
        run_generation(root, amp, first / GENERATED_FILES[0], first / GENERATED_FILES[1])
        run_generation(root, amp, second / GENERATED_FILES[0], second / GENERATED_FILES[1])

        for filename in GENERATED_FILES:
            stale_diff = file_diff(
                root / filename,
                first / filename,
                f"checked-in/{filename}",
                f"generated/{filename}",
            )
            if stale_diff:
                errors.append(stale_diff)

            repeat_diff = file_diff(
                first / filename,
                second / filename,
                f"first-generation/{filename}",
                f"second-generation/{filename}",
            )
            if repeat_diff:
                errors.append(f"generation is not deterministic:\n{repeat_diff}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify checked-in generated Amp files")
    parser.add_argument("--amp", default="amp", help="path to the Amp executable")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()

    errors = check_generated(arguments.root, arguments.amp)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
