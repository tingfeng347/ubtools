"""Regression: fzf preview commands must not assume the login shell is bash.

fzf runs ``--preview`` through the user's ``$SHELL``. A preview command that
contains bash-only syntax (for example ``line={}; ...``) therefore fails under
fish with ``Unsupported use of '='``. ubti/ubtr instead pass the raw
tab-delimited row to the script and parse it there, which works in any shell.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
SCRIPTS = ("ubti", "ubtr")
SHELLS = tuple(
    shell
    for shell in (
        shutil.which(name) for name in ("fish", "bash", "sh", "dash")
    )
    if shell
)


def fzf_quote(line):
    """Reproduce fzf's ``{}`` replacement: the single-quoted current line."""
    return "'" + line.replace("'", "'\\''") + "'"


class ShellPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.bin = root / "bin"
        self.bin.mkdir()
        apt_cache = self.bin / "apt-cache"
        apt_cache.write_text(
            '#!/bin/sh\nprintf "Package: %s\\nVersion: 1.0\\n" "$2"\n'
        )
        apt_cache.chmod(0o755)
        self.env = dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ.get('PATH', '')}",
            UBTOOLS_LANG="en",
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_CACHE_HOME=str(root / "cache"),
        )
        # Visible label, source field and package field, separated by tabs.
        self.line = "apt             bash 5.2                \tapt\tbash"

    def test_preview_command_runs_under_every_login_shell(self):
        if not SHELLS:
            self.skipTest("no login shell available")
        for script in SCRIPTS:
            path = BIN / script
            if not path.exists():
                self.skipTest(f"{script} is missing")
            command = f'"{path}" --preview-package {fzf_quote(self.line)}'
            for shell in SHELLS:
                with self.subTest(script=script, shell=Path(shell).name):
                    proc = subprocess.run(
                        [shell, "-c", command],
                        env=self.env,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertNotIn("Unsupported use of", proc.stderr)
                    self.assertNotIn("Unknown option", proc.stderr)
                    self.assertIn("Package: bash", proc.stdout)

    def test_preview_commands_avoid_bash_only_syntax(self):
        for script in SCRIPTS:
            path = BIN / script
            if not path.exists():
                self.skipTest(f"{script} is missing")
            with self.subTest(script=script):
                source = path.read_text()
                match = re.search(r"^PREVIEW_CMD=(.*)$", source, re.MULTILINE)
                self.assertIsNotNone(match, f"{script} defines no PREVIEW_CMD")
                command = match.group(1)
                # fzf runs this through the user's shell; keep it shell-agnostic.
                self.assertIn("--preview-package {}", command)
                self.assertNotRegex(command, r"\$\(")
                self.assertNotRegex(
                    command, r"(?:^|[;\s])[A-Za-z_][A-Za-z0-9_]*="
                )


if __name__ == "__main__":
    unittest.main()
