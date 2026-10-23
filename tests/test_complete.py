import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from amp_completions import complete


ROOT = Path(__file__).parents[1]


class CompleteCliTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    @property
    def calls(self) -> list[str]:
        log = self.directory / "calls"
        return log.read_text().splitlines() if log.exists() else []

    def environment(
        self,
        response: object,
        amp_exit_code: int = 0,
        *,
        responses: dict[str, object] | None = None,
        context: dict[str, str] | None = None,
    ) -> dict[str, str]:
        amp = self.directory / "amp"
        amp.write_text(
            f"#!{sys.executable}\n"
            "import json\n"
            "import sys\n"
            f"with open({str(self.directory / 'calls')!r}, 'a') as log:\n"
            "    log.write(' '.join(sys.argv[1:]) + '\\n')\n"
            f"if {amp_exit_code}:\n"
            f"    sys.exit({amp_exit_code})\n"
            f"responses = json.loads({json.dumps(responses or {})!r})\n"
            f"response = responses.get(' '.join(sys.argv[1:]), json.loads({json.dumps(response)!r}))\n"
            "if sys.argv[1] == 'threads' and 'list' in sys.argv:\n"
            "    limit = int(sys.argv[sys.argv.index('--limit') + 1])\n"
            "    offset = int(sys.argv[sys.argv.index('--offset') + 1])\n"
            "    response = response[offset:offset + limit]\n"
            "print(json.dumps(response))\n"
        )
        amp.chmod(0o755)
        environment = {
            name: value for name, value in os.environ.items() if not name.startswith("C_")
        }
        environment.update(
            {
                "AMP_BIN": str(amp),
                "PYTHONPATH": str(ROOT / "src"),
                "XDG_CACHE_HOME": str(self.directory / "cache"),
                "XDG_CONFIG_HOME": str(self.directory / "config"),
                "XDG_DATA_HOME": str(self.directory / "data"),
                **(context or {}),
            }
        )
        return environment

    def run_complete(
        self,
        resource: str,
        response: object = None,
        amp_exit_code: int = 0,
        cwd: Path | None = None,
        **options: dict[str, object] | dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "amp_completions.complete", resource],
            capture_output=True,
            cwd=cwd,
            env=self.environment(response, amp_exit_code, **options),
            text=True,
        )

    def write(self, path: str, content: str) -> None:
        target = self.directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

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
                shutil.rmtree(self.directory / "cache", ignore_errors=True)
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

        with process.stderr:
            self.assertEqual(process.stderr.read(), "")
        self.assertEqual(process.wait(), 0)

    def test_warm_cache_skips_amp(self) -> None:
        tools = [{"name": "shell_command", "description": "Run a command"}]

        first = self.run_complete("tools", tools)
        second = self.run_complete("tools", [{"name": "changed"}])

        self.assertEqual(second.stdout, first.stdout)
        self.assertEqual(self.calls, ["tools list --json"])
        cache = self.directory / "cache" / "amp-completions"
        self.assertEqual(cache.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(entry.stat().st_mode & 0o077 == 0 for entry in cache.iterdir()))

    def test_amp_state_changes_invalidate_cache(self) -> None:
        workspace = self.directory / "workspace"
        (workspace / ".git").mkdir(parents=True)
        (workspace / "src").mkdir()
        changes = {
            "account switch": lambda: self.write("data/amp/accounts.json", "{}"),
            "login": lambda: self.write("data/amp/secrets.json", "{}"),
            "user settings": lambda: self.write("config/amp/settings.json", "{}"),
            "workspace settings": lambda: self.write("workspace/.amp/settings.json", "{}"),
            "access token": lambda: {"AMP_API_KEY": "sgamp_other"},
            "server": lambda: {"AMP_URL": "https://amp.example.com"},
        }

        for change, apply in changes.items():
            with self.subTest(change=change):
                shutil.rmtree(self.directory / "cache", ignore_errors=True)
                (self.directory / "calls").unlink(missing_ok=True)
                self.run_complete("projects", [], cwd=workspace / "src")
                context = apply() or {}
                self.run_complete("projects", [], cwd=workspace / "src", context=context)

                self.assertEqual(len(self.calls), 2)

    def test_refresh_prunes_entries_past_retention(self) -> None:
        self.run_complete("projects", [])
        self.run_complete("skills", {"skills": []})
        cache = self.directory / "cache" / "amp-completions"
        old, recent = sorted(cache.iterdir())
        os.utime(old, (0, 0))
        stale = time.time() - complete.CACHE_RETENTION_SECONDS + 60
        os.utime(recent, (stale, stale))

        self.run_complete("tools", [])

        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_cache_does_not_store_access_token(self) -> None:
        self.run_complete("projects", [], context={"AMP_API_KEY": "sgamp_secret"})

        for entry in (self.directory / "cache" / "amp-completions").iterdir():
            self.assertNotIn("sgamp_secret", entry.name + entry.read_text())

    def test_context_flags_scope_queries_and_cache_entries(self) -> None:
        tools = [{"name": "shell_command"}]

        self.run_complete("tools", tools)
        scoped = self.run_complete(
            "tools", [{"name": "oracle"}], context={"C_FLAG_MODE": "ultra"}
        )

        self.assertEqual(scoped.stdout, "oracle\n")
        self.assertEqual(self.calls, ["tools list --json", "tools list --mode ultra --json"])

    def test_expired_cache_survives_failed_refresh(self) -> None:
        self.run_complete("projects", [{"namespace": "meatcar", "name": "amp"}])
        for entry in (self.directory / "cache" / "amp-completions").iterdir():
            os.utime(entry, (0, 0))

        result = self.run_complete("projects", [], amp_exit_code=1)

        self.assertEqual(result.stdout, "meatcar/amp\n")
        self.assertEqual(len(self.calls), 2)

    def test_domain_scope_flag_selects_one_account(self) -> None:
        result = self.run_complete(
            "domains",
            responses={
                "domains list --user --json": [{"hostname": "me.example.com"}],
                "domains list --workspace --json": [{"hostname": "team.example.com"}],
            },
            context={"C_FLAG_WORKSPACE": "true"},
        )

        self.assertEqual(result.stdout, "team.example.com\n")
        self.assertEqual(self.calls, ["domains list --workspace --json"])

    def test_unscoped_domains_query_both_accounts(self) -> None:
        result = self.run_complete(
            "domains",
            responses={
                "domains list --user --json": [{"hostname": "me.example.com"}],
                "domains list --workspace --json": [{"hostname": "team.example.com"}],
            },
        )

        self.assertEqual(result.stdout, "me.example.com\nteam.example.com\n")

    def test_scoped_remote_mcp_servers_use_that_scope(self) -> None:
        result = self.run_complete(
            "remote-mcp-servers",
            responses={
                "mcp remote list --project acme/app --json": {
                    "action": "list-servers",
                    "servers": [
                        {"id": "MCP-1", "name": "github", "url": "https://api.github.com/mcp"},
                        {"id": "MCP-2", "name": "Linear MCP", "url": "https://mcp.linear.app"},
                    ],
                }
            },
            context={"C_FLAG_PROJECT": "acme/app"},
        )

        self.assertEqual(
            result.stdout,
            "github\thttps://api.github.com/mcp\nMCP-2\tLinear MCP\n",
        )

    def test_workspace_model_providers_use_workspace_keys(self) -> None:
        result = self.run_complete(
            "model-providers",
            responses={
                "config model-providers list --workspace --json": [{"id": "MP-9", "type": "openai"}]
            },
            context={"C_FLAG_WORKSPACE": "true"},
        )

        self.assertEqual(result.stdout, "MP-9\topenai\n")

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

            with self.assertRaises(subprocess.TimeoutExpired):
                complete.run_json(str(amp), ["tools", "list", "--json"], timeout=0.1)


if __name__ == "__main__":
    unittest.main()
