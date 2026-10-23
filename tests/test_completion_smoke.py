import json
import os
import subprocess
import sys
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
            # NOTE: Python, not sh: dash drops names like C_FLAG_PERMA-ORB from its environment.
            helper.write_text(
                f"#!{sys.executable}\n"
                "import os, sys\n"
                "flags = sorted(f'{k[7:]}:{v}' for k, v in os.environ.items() if k.startswith('C_FLAG_'))\n"
                "print({\n"
                "    'threads': 'T-123\\tExample thread',\n"
                "    'projects': 'meatcar/amp-completions\\tExample project',\n"
                "    'tools': 'shell_command\\tRun a command',\n"
                "    'skills': 'tdd\\tTest-driven development',\n"
                "    'local-mcp-servers': 'playwright\\tWorkspace settings',\n"
                "    'secrets': '\\n'.join(flags),\n"
                "}.get(sys.argv[1], ''))\n"
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

    def test_completes_dynamic_tool_names(self) -> None:
        self.assertIn("shell_command", self.complete("tools", "show", ""))

    def test_passes_typed_scope_flags_to_the_helper(self) -> None:
        self.assertEqual(
            self.complete("secrets", "get", "--perma-orb", "acme/box", ""),
            {"PERMA-ORB:acme/box"},
        )
        self.assertEqual(self.complete("secrets", "get", "--project", ""), {"PROJECT: "})

    def test_completes_static_enum_values(self) -> None:
        self.assertEqual(
            self.complete("projects", "create", "--ship-behavior", ""),
            {"custom", "push-to-branch", "ship"},
        )

    def test_completes_fixed_positional_values(self) -> None:
        self.assertEqual(self.complete("completions", ""), {"bash", "fish", "pwsh", "zsh"})
        self.assertIn("T-123", self.complete("threads", "context", ""))

    def test_completes_comma_separated_features(self) -> None:
        self.assertEqual(self.complete("--features", "fast,"), {"fast,plaid", "fast,pro"})

    def test_completes_file_and_directory_values(self) -> None:
        self.assertIn("README.md", self.complete("--settings-file", ""))
        self.assertIn("src/", self.complete("clone", "owner/repo", ""))


if __name__ == "__main__":
    unittest.main()
