import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class CompletionSmokeTest(unittest.TestCase):
    def complete(self, *words: str) -> set[str]:
        with tempfile.TemporaryDirectory() as directory:
            config_directory = Path(directory) / "config"
            spec_directory = config_directory / "carapace" / "specs"
            spec_directory.mkdir(parents=True)
            (spec_directory / "amp.yaml").write_text((ROOT / "amp.yaml").read_text())
            helper_directory = config_directory / "carapace" / "bin"
            helper_directory.mkdir()
            helper = helper_directory / "amp-completions"
            helper.write_text(
                "#!/bin/sh\n"
                "case $1 in\n"
                "  threads) printf 'T-123\\tExample thread\\n' ;;\n"
                "  projects) printf 'meatcar/amp-completions\\tExample project\\n' ;;\n"
                "esac\n"
            )
            helper.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": directory,
                    "XDG_CACHE_HOME": f"{directory}/cache",
                    "XDG_CONFIG_HOME": str(config_directory),
                }
            )
            result = subprocess.run(
                [
                    "carapace",
                    "amp",
                    "export",
                    "",
                    *words,
                ],
                check=True,
                capture_output=True,
                env=environment,
                text=True,
            )
        return {value["value"] for value in json.loads(result.stdout)["values"]}

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

    def test_completes_thread_flag_values(self) -> None:
        self.assertIn("T-123", self.complete("orb", "portal", "--thread", ""))

    def test_completes_thread_positional_values(self) -> None:
        self.assertIn("T-123", self.complete("threads", "continue", ""))

    def test_completes_project_positional_values(self) -> None:
        self.assertIn(
            "meatcar/amp-completions",
            self.complete("projects", "get", ""),
        )


if __name__ == "__main__":
    unittest.main()
