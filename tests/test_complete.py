import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from amp_completions import complete


ROOT = Path(__file__).parents[1]


class CompleteCliTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def environment(self, response: object, amp_exit_code: int = 0) -> dict[str, str]:
        amp = self.directory / "amp"
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
        return environment

    def run_complete(
        self,
        resource: str,
        response: object,
        amp_exit_code: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "amp_completions.complete", resource],
            capture_output=True,
            env=self.environment(response, amp_exit_code),
            text=True,
        )

    def start_complete(self, resource: str, response: object) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [sys.executable, "-m", "amp_completions.complete", resource],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.environment(response),
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

    def test_completes_one_bounded_page_of_threads(self) -> None:
        threads = [
            {"id": f"T-{number:04}", "title": f"Thread {number}"}
            for number in range(complete.THREAD_LIMIT + 100)
        ]

        result = self.run_complete("threads", threads)

        self.assertEqual(result.returncode, 0)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), complete.THREAD_LIMIT)
        self.assertEqual(lines[-1], f"T-{complete.THREAD_LIMIT - 1:04}\tThread {complete.THREAD_LIMIT - 1}")

    def test_rejects_malformed_candidates_without_output(self) -> None:
        cases = {
            "tools": [{"name": "shell_command", "description": 42}],
            "threads": [{"id": None, "title": "Missing ID"}],
            "projects": [{"namespace": "meatcar", "name": ["amp"]}],
        }

        for resource, response in cases.items():
            with self.subTest(resource=resource):
                result = self.run_complete(resource, response)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, "")

    def test_closed_output_is_silent(self) -> None:
        threads = [{"id": f"T-{number:04}", "title": "x" * 200} for number in range(500)]
        process = self.start_complete("threads", threads)
        assert process.stdout is not None and process.stderr is not None
        process.stdout.readline()
        process.stdout.close()

        self.assertEqual(process.stderr.read(), "")
        self.assertEqual(process.wait(), 0)

    def test_hides_amp_errors_from_the_shell(self) -> None:
        result = self.run_complete("threads", [], amp_exit_code=1)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")


class QueryTimeoutTest(unittest.TestCase):
    def test_stalled_amp_query_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            amp = Path(directory) / "amp"
            amp.write_text("#!/bin/sh\nexec sleep 10\n")
            amp.chmod(0o755)

            with (
                mock.patch.object(complete, "QUERY_TIMEOUT_SECONDS", 0.1),
                self.assertRaises(subprocess.TimeoutExpired),
            ):
                complete.run_json(str(amp), ["tools", "list", "--json"])


if __name__ == "__main__":
    unittest.main()
