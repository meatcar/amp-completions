import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class CompletionSmokeTest(unittest.TestCase):
    def complete(self, *words: str) -> set[str]:
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": directory,
                    "XDG_CACHE_HOME": f"{directory}/cache",
                    "XDG_CONFIG_HOME": f"{directory}/config",
                }
            )
            result = subprocess.run(
                [
                    "carapace",
                    "--run",
                    str(ROOT / "amp.yaml"),
                    "__complete",
                    *words,
                ],
                check=True,
                capture_output=True,
                env=environment,
                text=True,
            )
        return {
            line.split("\t", 1)[0]
            for line in result.stdout.splitlines()
            if line and not line.startswith(":")
        }

    def test_completes_root_command(self) -> None:
        self.assertIn("threads", self.complete(""))

    def test_completes_nested_command(self) -> None:
        self.assertIn("multiplayer", self.complete("threads", "share", ""))

    def test_completes_persistent_flag_below_root(self) -> None:
        self.assertIn("--mode", self.complete("threads", "--m"))

    def test_completes_mode_values(self) -> None:
        self.assertEqual(
            self.complete("--mode", ""),
            {"high", "low", "medium", "ultra"},
        )


if __name__ == "__main__":
    unittest.main()
