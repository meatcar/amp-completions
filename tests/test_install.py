import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class InstallTest(unittest.TestCase):
    def test_installs_spec_and_dynamic_completion_helper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            environment = os.environ.copy()
            environment["AMP_BIN"] = str(Path(directory) / "amp & custom")
            environment["XDG_CONFIG_HOME"] = str(config)

            subprocess.run(
                ["make", "install"],
                check=True,
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertTrue((config / "carapace" / "specs" / "amp.yaml").is_file())
            helper = config / "carapace" / "bin" / "amp-completions"
            self.assertTrue(helper.is_file())
            self.assertTrue(os.access(helper, os.X_OK))
            amp = environment.get("AMP_BIN") or shutil.which(
                "amp", path=environment["PATH"]
            )
            self.assertIn(
                f'DEFAULT_AMP = "{amp}"',
                helper.read_text(),
            )


if __name__ == "__main__":
    unittest.main()
