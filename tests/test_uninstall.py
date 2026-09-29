"""Run the standalone uninstaller in isolated installation directories."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UninstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.cache = self.root / "cache" / "ubti_tui"
        self.cache.mkdir(parents=True)
        (self.cache / "snap_packages.txt").write_text("cached packages")
        self.env = dict(
            os.environ, BIN_DIR=str(self.bin), XDG_CACHE_HOME=str(self.root / "cache")
        )
        self.script = (ROOT / "uninstall.sh").read_text()

    def run_script(self, *options):
        # bash -s matches curl | bash: the script itself occupies standard input.
        return subprocess.run(
            ["bash", "-s", "--", *options],
            input=self.script,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )

    def test_legacy_cleanup_preserves_cache_and_unrelated_files(self):
        for name in ["ubti", "ubtr", "codex", "unrelated"]:
            (self.bin / name).write_text(name)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({p.name for p in self.bin.iterdir()}, {"codex", "unrelated"})
        self.assertTrue((self.cache / "snap_packages.txt").exists())
        # Repeated uninstallation is harmless.
        self.assertEqual(self.run_script().returncode, 0)

    def test_full_install_cleanup_and_explicit_cache_purge(self):
        names = [
            "ub",
            "ubti",
            "ubtr",
            "ubtu",
            "ubtd",
            "ubtc",
            "ubtm",
            "ubta",
            "ubtools-completion.bash",
            "ubtools-common.bash",
            "ubtools-language.bash",
            "ubtools_runtime.py",
            "ubtools_mirror.py",
            "ubtools_ai.py",
        ]
        for name in names:
            (self.bin / name).write_text(name)
        result = self.run_script("--purge-cache")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.bin.iterdir()), [])
        self.assertFalse(self.cache.exists())

    def test_dry_run_preserves_files_and_cache(self):
        (self.bin / "ub").write_text("entry point")
        result = self.run_script("--dry-run", "--purge-cache")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.bin / "ub"), result.stdout)
        self.assertIn(str(self.cache), result.stdout)
        self.assertTrue((self.bin / "ub").exists())
        self.assertTrue(self.cache.exists())

    def test_dangling_legacy_symlink_is_removed(self):
        (self.bin / "ubti").symlink_to(self.root / "missing")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.bin / "ubti").is_symlink())

    def test_custom_directory_help_and_invalid_arguments(self):
        alternate = self.root / "alternate"
        alternate.mkdir()
        (alternate / "ubtr").write_text("legacy")
        result = self.run_script("--bin-dir", str(alternate))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(alternate.iterdir()), [])
        (self.bin / "ub").write_text("entry point")
        for args in [("--bin-dir",), ("--bin-dir", "/"), ("--unknown",)]:
            self.assertEqual(self.run_script(*args).returncode, 2)
        self.assertEqual(self.run_script("--help").returncode, 0)
        self.assertTrue((self.bin / "ub").exists())


if __name__ == "__main__":
    unittest.main()
