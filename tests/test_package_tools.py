"""Entry-point tests with isolated package managers; no host mutations."""

import fcntl
import os
import pty
import select
import shlex
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import time
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"


class PackageToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            XDG_CACHE_HOME=str(self.root / "cache"),
            TEST_ROOT=str(self.root),
            LANG="C",
            LC_ALL="C",
            UBTOOLS_LANG="C",
        )
        self.stub("sudo", 'exec "$@"')
        self.stub(
            "apt",
            """case "$*" in
'list --upgradable') printf 'Listing...\\nvim/stable 2.0 amd64 [upgradable from: 1.0]\\nlibfoo/stable 4.0 i386 [upgradable from: 3.0]\\n';;
*) exit 2;;
esac""",
        )
        self.stub(
            "apt-get",
            """case "$*" in
'--simulate autoremove') printf 'Remv old-lib [1.0]\\nAfter this operation, 10 MB disk space will be freed.\\n';;
'indextargets --format $(URI)') printf 'https://user:password@apt.example/dists/stable/main/binary-amd64/Packages\\n';;
*) printf 'apt-get:%s\\n' "$*" >> "$TEST_ROOT/mutations";;
esac""",
        )
        self.stub(
            "snap",
            """case "$*" in
'list') printf 'Name Version Rev Tracking Publisher Notes\\neditor 1.0 10 stable vendor -\\n';;
'list --all'|'list --all editor') printf 'Name Version Rev Tracking Publisher Notes\\neditor 1.0 9 stable vendor disabled\\neditor 1.0 10 stable vendor -\\n';;
'refresh --list') printf 'Name Version Rev Size Publisher Notes\\neditor 2.0 11 1MB vendor -\\n';;
'version') printf 'snap 2.0\\n';;
*) printf 'snap:%s\\n' "$*" >> "$TEST_ROOT/mutations";;
esac""",
        )
        self.stub(
            "flatpak",
            """scope=user
[[ "$*" == *--system* ]] && scope=system
case "$1" in
list)
    [[ "$*" == *--runtime* ]] && exit 0
    printf 'org.editor.App/x86_64/stable\\t1.0\\toldcommit000000\\tcustom-remote\\n';;
remote-ls) printf 'org.editor.App/x86_64/stable\\t2.0\\tnewcommit000000\\tcustom-remote\\n';;
remotes) printf 'custom-remote\\n';;
*) printf 'flatpak:%s\\n' "$*" >> "$TEST_ROOT/mutations";;
esac""",
        )
        self.stub("apt-cache", "exit 0")
        self.stub("dpkg", "exit 0")
        self.stub("fuser", "exit 1")
        self.stub("curl", "exit 0")
        self.stub(
            "fzf",
            """touch "$TEST_ROOT/ready"
printf '\\n\\n'
cat""",
        )

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\nset -eu\n" + body + "\n")
        path.chmod(0o755)

    def run_tool(self, name, *args, answer="y\n"):
        return subprocess.run(
            [str(BIN / name), *args],
            check=False,
            env=self.env,
            input=answer,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def mutations(self):
        file = self.root / "mutations"
        return file.read_text() if file.exists() else ""

    def test_updates_preserve_architectures_and_flatpak_scope(self):
        proc = self.run_tool("ubtu", "--list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("\tapt\tsystem\tvim:amd64\t1.0\t2.0", proc.stdout)
        self.assertIn("\tlibfoo:i386\t", proc.stdout)
        self.assertIn("\tsnap\tsystem\teditor\t1.0@10\t2.0@11", proc.stdout)
        for scope in ["user", "system"]:
            self.assertIn(
                f"\tflatpak\t{scope}\tapp/org.editor.App/x86_64/stable\t", proc.stdout
            )
        self.assertEqual(self.mutations(), "")

    def test_selected_updates_execute_in_correct_scope(self):
        proc = self.run_tool("ubtu")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        mutations = self.mutations()
        self.assertIn("apt-get:install --only-upgrade", mutations)
        self.assertIn("vim:amd64", mutations)
        self.assertIn("snap:refresh editor", mutations)
        self.assertIn(
            "flatpak:update --user app/org.editor.App/x86_64/stable", mutations
        )
        self.assertIn(
            "flatpak:update --system app/org.editor.App/x86_64/stable", mutations
        )
        self.assertNotIn("--assumeyes", mutations)

    def test_dry_run_and_declined_confirmation_do_not_update(self):
        proc = self.run_tool("ubtu", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("sudo apt-get install --only-upgrade", proc.stdout)
        self.assertEqual(self.mutations(), "")
        proc = self.run_tool("ubtu", answer="n\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.mutations(), "")

    def test_source_filter_does_not_query_other_sources(self):
        self.stub("snap", 'echo called >> "$TEST_ROOT/mutations"; exit 1')
        self.stub("flatpak", 'echo called >> "$TEST_ROOT/mutations"; exit 1')
        proc = self.run_tool("ubtu", "--apt", "--list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("vim", proc.stdout)
        self.assertEqual(self.mutations(), "")

    def test_failed_partial_query_never_becomes_update(self):
        self.stub("apt", "printf 'vim/stable 2 amd64 [upgradable from: 1]\\n'; exit 1")
        proc = self.run_tool("ubtu", "--apt", "--list")
        self.assertEqual(proc.stdout, "")
        self.assertIn("Query failed", proc.stderr)
        self.assertEqual(self.mutations(), "")

    def test_partial_flatpak_ref_version_update_is_visible(self):
        self.stub(
            "flatpak",
            """case "$1" in
list) [[ "$*" == *--runtime* ]] && exit 0
printf 'org.editor.App/x86_64/stable\\t1.0\\taaaa11111111\\tcustom\\n';;
remote-ls) printf 'org.editor.App/x86_64/stable\\t1.0\\tbbbb22222222\\tcustom\\n';;
esac""",
        )
        proc = self.run_tool("ubtu", "--flatpak", "--list")
        self.assertIn("1.0@aaaa11111111\t1.0@bbbb22222222", proc.stdout)

    def test_cleanup_lists_only_disabled_snap_revisions(self):
        proc = self.run_tool("ubtc", "--list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("disabled revision 9", proc.stdout)
        self.assertNotIn("disabled revision 10", proc.stdout)
        self.assertIn("\tapt\tsystem\tautoremove\t", proc.stdout)
        self.assertEqual(self.mutations(), "")

    def test_cleanup_dry_run_and_active_revision_recheck(self):
        proc = self.run_tool("ubtc", "--snap", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("sudo snap remove editor --revision=9", proc.stdout)
        self.assertEqual(self.mutations(), "")
        self.stub(
            "snap",
            """case "$*" in
'list --all') printf 'Name Version Rev Notes\\neditor 1.0 9 disabled\\n';;
'list --all editor') printf 'Name Version Rev Notes\\neditor 1.0 9 -\\n';;
*) echo mutation >> "$TEST_ROOT/mutations";;
esac""",
        )
        proc = self.run_tool("ubtc", "--snap")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Revision state changed", proc.stderr)
        self.assertEqual(self.mutations(), "")

    def test_cleanup_executes_selected_actions_with_native_confirmation(self):
        self.stub(
            "flatpak",
            """case "$1" in
list) printf 'org.platform.Runtime/x86_64/stable\\t100 MB\\n';;
*) printf 'flatpak:%s\\n' "$*" >> "$TEST_ROOT/mutations";;
esac""",
        )
        proc = self.run_tool("ubtc")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        mutations = self.mutations()
        self.assertIn("apt-get:clean", mutations)
        self.assertIn("apt-get:autoremove", mutations)
        self.assertIn("snap:remove editor --revision=9", mutations)
        self.assertIn("flatpak:uninstall --user --unused", mutations)
        self.assertIn("flatpak:uninstall --system --unused", mutations)
        self.assertNotIn("--delete-data", mutations)
        self.assertNotIn("--assumeyes", mutations)

    def test_diagnostics_offline_never_contacts_remotes(self):
        self.stub("curl", 'echo network >> "$TEST_ROOT/mutations"; exit 1')
        self.stub(
            "snap",
            """[[ "$*" != 'refresh --list' ]] || { echo network >> "$TEST_ROOT/mutations"; exit 1; }
exit 0""",
        )
        self.stub(
            "flatpak",
            """[[ "$1" != remote-ls ]] || { echo network >> "$TEST_ROOT/mutations"; exit 1; }
printf 'local\\n' """,
        )
        proc = self.run_tool("ubtd", "--offline")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Remote connectivity", proc.stdout)
        self.assertEqual(self.mutations(), "")

    def test_diagnostics_report_failure_timings_and_redact_urls(self):
        self.stub("curl", "exit 22")
        proc = self.run_tool("ubtd", "--apt")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("FAIL", proc.stdout)
        self.assertIn("APT HEAD: apt.example", proc.stdout)
        self.assertRegex(proc.stdout, r"\d+ms")
        self.assertNotIn("password", proc.stdout + proc.stderr)

    def test_diagnostics_bound_slow_queries(self):
        self.stub("snap", "exec sleep 5")
        start = time.monotonic()
        proc = self.run_tool("ubtd", "--snap", "--offline", "--timeout", "1")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertLess(time.monotonic() - start, 3)
        self.assertIn("exit=124", proc.stdout)

    def test_unknown_flags_and_help(self):
        for name in ["ubtu", "ubtc", "ubtd"]:
            self.assertEqual(self.run_tool(name, "--bad-option").returncode, 2)
            self.assertEqual(self.run_tool(name, "--help").returncode, 0)
        proc = self.run_tool("ubtu", "--refresh-index", "--dry-run")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(self.mutations(), "")

    def test_update_ui_starts_before_slow_query(self):
        self.stub(
            "apt",
            """sleep 1
printf 'vim/stable 2 amd64 [upgradable from: 1]\\n' """,
        )
        self.stub(
            "fzf",
            """touch "$TEST_ROOT/ready"
cat > /dev/null
exit 130""",
        )
        start = time.monotonic()
        proc = subprocess.Popen(
            [str(BIN / "ubtu"), "--apt"],
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            while not (self.root / "ready").exists() and proc.poll() is None:
                self.assertLess(time.monotonic() - start, 3)
                time.sleep(0.01)
            elapsed = time.monotonic() - start
            _, stderr = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 0, stderr.decode())
            self.assertLess(elapsed, 0.5)
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.communicate(timeout=5)

    def test_installer_and_uninstaller_include_all_commands_and_shared_helpers(self):
        self.stub(
            "grep",
            '''if [[ "$*" == *ubuntu* && "$*" == */etc/os-release* ]]; then exit 0; fi
exec /usr/bin/grep "$@"''',
        )
        self.stub("flatpak", "printf 'flathub\\n'")
        install_dir = self.root / "installed"
        env = dict(self.env, BIN_DIR=str(install_dir))
        proc = subprocess.run(
            ["bash", str(BIN.parent / "install.sh")],
            check=False,
            env=env,
            text=True,
            input="n\n",
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for name in [
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
            "ubtools_runtime.py",
            "ubtools_mirror.py",
            "ubtools_ai.py",
        ]:
            self.assertEqual(
                (install_dir / name).read_bytes(), (BIN / name).read_bytes()
            )
        for name in ["ub", "ubtu", "ubtd", "ubtc", "ubtm", "ubta"]:
            proc = subprocess.run(
                [str(install_dir / name), "--help"],
                check=False,
                env=env,
                text=True,
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = subprocess.run(
            ["bash", str(BIN.parent / "uninstall.sh")],
            check=False,
            env=env,
            text=True,
            input="n\n",
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(list(install_dir.iterdir()), [])

    def test_unrecognized_selection_metadata_does_not_execute(self):
        self.stub(
            "fzf",
            """cat > /dev/null
printf '\\n\\nforged\\tapt\\tsystem\\tunexpected-package\\t1\\t2\\n'
""",
        )
        proc = self.run_tool("ubtu")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.mutations(), "")

    def test_reload_and_mode_switch_preserve_query(self):
        self.stub(
            "fzf",
            """cat > "$TEST_ROOT/rows"
if [[ ! -f "$TEST_ROOT/mode-switched" ]]; then
    touch "$TEST_ROOT/mode-switched"
    printf 'editor\\nctrl-e\\n'
elif [[ ! -f "$TEST_ROOT/reloaded" ]]; then
    printf '%s\\n' "$@" > "$TEST_ROOT/mode-args"
    touch "$TEST_ROOT/reloaded"
    printf 'editor\\nctrl-r\\n'
else
    printf '%s\\n' "$@" > "$TEST_ROOT/reload-args"
    printf 'editor\\n\\n'
    cat "$TEST_ROOT/rows"
fi""",
        )
        proc = self.run_tool("ubtu", "--snap", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for file in ["mode-args", "reload-args"]:
            args = (self.root / file).read_text().splitlines()
            self.assertIn("--exact", args)
            self.assertEqual(args[args.index("--query") + 1], "editor")
        self.assertIn("sudo snap refresh editor", proc.stdout)
        self.assertEqual(self.mutations(), "")

    def test_download_installer_fetches_shared_helpers(self):
        self.stub(
            "grep",
            '''if [[ "$*" == *ubuntu* && "$*" == */etc/os-release* ]]; then exit 0; fi
exec /usr/bin/grep "$@"''',
        )
        self.stub("flatpak", "printf 'flathub\\n'")
        self.stub(
            "curl",
            '''url="$2"
cp "$TEST_SOURCE_BIN/${url##*/}" "$4"''',
        )
        standalone = self.root / "install.sh"
        standalone.write_bytes((BIN.parent / "install.sh").read_bytes())
        install_dir = self.root / "download-installed"
        env = dict(self.env, BIN_DIR=str(install_dir), TEST_SOURCE_BIN=str(BIN))
        proc = subprocess.run(
            ["bash", str(standalone)],
            check=False,
            env=env,
            text=True,
            input="n\n",
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            (install_dir / "ubtools-common.bash").read_bytes(),
            (BIN / "ubtools-common.bash").read_bytes(),
        )
        self.assertEqual(len(list(install_dir.iterdir())), 13)

    @unittest.skipUnless(shutil.which("fzf"), "real fzf is unavailable")
    def test_real_fzf_selection_routes_to_dry_run_update(self):
        self.stub("fzf", f'exec {shlex.quote(shutil.which("fzf"))} "$@"')
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))
        env = dict(
            self.env,
            TERM="xterm-256color",
            FZF_DEFAULT_OPTS="",
            FZF_DEFAULT_OPTS_FILE="/dev/null",
        )

        proc = subprocess.Popen(
            ["setsid", "--ctty", str(BIN / "ubtu"), "--apt", "--dry-run", "vim"],
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
        )
        os.close(slave)
        output = b""
        deadline = time.monotonic() + 5
        selected = False
        try:
            while proc.poll() is None or select.select([master], [], [], 0)[0]:
                self.assertLess(time.monotonic(), deadline, "fzf did not complete")
                if select.select([master], [], [], 0.05)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    output += chunk
                    if b"\x1b[6n" in chunk:
                        os.write(master, b"\x1b[1;1R" * chunk.count(b"\x1b[6n"))
                    if b"\x1b[?2004$p" in chunk:
                        os.write(master, b"\x1b[?2004;2$y")
                    if not selected and b"vim:amd64" in output:
                        os.write(master, b"\r")
                        selected = True
            proc.wait(timeout=1)
            self.assertEqual(proc.returncode, 0)
            self.assertIn(
                b"sudo apt-get install --only-upgrade vim:amd64", output[-2000:]
            )
            self.assertEqual(self.mutations(), "")
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)
            os.close(master)


if __name__ == "__main__":
    unittest.main()
