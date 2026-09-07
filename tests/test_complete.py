import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class CompleteCliTest(unittest.TestCase):
    def run_complete(
        self,
        resource: str,
        response: object,
        amp_exit_code: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            amp = Path(directory) / "amp"
            amp.write_text(
                f"#!{sys.executable}\n"
                "import json\n"
                "import sys\n"
                f"if {amp_exit_code}:\n"
                f"    sys.exit({amp_exit_code})\n"
                f"response = json.loads({json.dumps(response)!r})\n"
                "if sys.argv[1] == 'threads' and 'list' in sys.argv:\n"
                "    limit = int(sys.argv[sys.argv.index('--limit') + 1])\n"
                "    offset = int(sys.argv[sys.argv.index('--offset') + 1])\n"
                "    response = response[offset:offset + limit]\n"
                "print(json.dumps(response))\n"
            )
            amp.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "AMP_BIN": str(amp),
                    "PYTHONPATH": str(ROOT / "src"),
                }
            )
            return subprocess.run(
                [sys.executable, "-m", "amp_completions.complete", resource],
                capture_output=True,
                env=environment,
                text=True,
            )

    def test_completes_threads_with_titles(self) -> None:
        result = self.run_complete(
            "threads",
            [
                {"id": "T-123", "title": "Fix completion"},
                {"id": "T-456", "title": ""},
                {"id": "T-789", "title": "Title\twith\nwhitespace"},
                {"id": "T-999", "title": None},
            ],
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            "T-123\tFix completion\nT-456\nT-789\tTitle with whitespace\nT-999\n",
        )

    def test_completes_projects_with_repository_descriptions(self) -> None:
        result = self.run_complete(
            "projects",
            [
                {
                    "id": "P-123",
                    "name": "amp-completions",
                    "namespace": "meatcar",
                    "repositoryURL": "https://github.com/meatcar/amp-completions",
                }
            ],
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            "meatcar/amp-completions\thttps://github.com/meatcar/amp-completions\n",
        )

    def test_completes_json_backed_resources(self) -> None:
        cases = {
            "tools": (
                [{"name": "shell_command", "description": "Run a command", "source": "builtin"}],
                "shell_command\tRun a command\n",
            ),
            "skills": (
                {
                    "errors": [],
                    "skills": [
                        {
                            "name": "tdd",
                            "description": "Test-driven development",
                            "source": "workspace",
                        }
                    ],
                },
                "tdd\tTest-driven development\n",
            ),
            "remote-mcp-servers": (
                [
                    {
                        "id": "MCP-123",
                        "name": "linear",
                        "source": "account",
                        "connected": True,
                    }
                ],
                "linear\taccount\n",
            ),
            "local-mcp-servers": (
                [
                    {
                        "id": "MCP-123",
                        "name": "linear",
                        "source": "account",
                        "connected": True,
                    },
                    {
                        "id": "MCP-456",
                        "name": "playwright",
                        "source": "workspace settings",
                        "connected": True,
                    },
                ],
                "playwright\tworkspace settings\n",
            ),
            "model-providers": (
                [
                    {
                        "id": "MP-123",
                        "name": "Work OpenAI",
                        "type": "openai",
                    }
                ],
                "MP-123\tWork OpenAI (openai)\n",
            ),
            "domains": (
                [{"hostname": "docs.example.com", "status": "active"}],
                "docs.example.com\tactive\n",
            ),
        }

        for resource, (response, expected) in cases.items():
            with self.subTest(resource=resource):
                result = self.run_complete(resource, response)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, expected)

    def test_completes_threads_beyond_the_first_page(self) -> None:
        threads = [
            {"id": f"T-{number:03}", "title": f"Thread {number}"}
            for number in range(501)
        ]

        result = self.run_complete("threads", threads)

        self.assertEqual(result.returncode, 0)
        self.assertIn("T-500\tThread 500\n", result.stdout)

    def test_hides_amp_errors_from_the_shell(self) -> None:
        result = self.run_complete("threads", [], amp_exit_code=1)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
