"""Exercise the unified CLI, signed local mirrors and isolated AI operations."""

import argparse
import hashlib
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
ai = importlib.import_module("ubtools_ai")
mirror = importlib.import_module("ubtools_mirror")
runtime = importlib.import_module("ubtools_runtime")


class UnifiedTests(unittest.TestCase):
    def test_help_and_dispatch(self):
        for action in [
            "install",
            "remove",
            "update",
            "doctor",
            "clean",
            "mirror",
            "ai",
        ]:
            proc = subprocess.run(
                [str(BIN / "ub"), action, "--help"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("ub " + action, proc.stdout)
        proc = subprocess.run(
            [str(BIN / "ub"), "nonexistent"], check=False, capture_output=True
        )
        self.assertEqual(proc.returncode, 2)
        for name in ["ubtm", "ubta"]:
            self.assertEqual(
                subprocess.run(
                    [str(BIN / name), "--help"], check=False, capture_output=True
                ).returncode,
                0,
            )

    def test_remove_help_does_not_require_fzf(self):
        with tempfile.TemporaryDirectory() as directory:
            for utility in ["bash", "readlink", "realpath", "dirname", "grep", "cat"]:
                path = shutil.which(utility)
                if path:
                    (Path(directory) / utility).symlink_to(path)
            env = dict(os.environ, PATH=directory)
            result = subprocess.run(
                [str(BIN / "ub"), "remove", "--help"],
                check=False,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ub remove", result.stdout)

    def test_bash_completion_contains_only_the_current_feature_commands(self):
        output = subprocess.run(
            [str(BIN / "ub"), "completion", "bash"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        script = (
            output
            + '\nCOMP_WORDS=(ub ai ""); COMP_CWORD=2; _ub_complete; printf "%s\\n" "${COMPREPLY[@]}"'
        )
        proc = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=True
        )
        self.assertIn("status", proc.stdout)
        self.assertIn("remove", proc.stdout)
        self.assertIn("pi", output)
        self.assertIn("install", proc.stdout)
        self.assertNotIn("backup", output)
        for shell in ["zsh", "fish"]:
            self.assertEqual(
                subprocess.run(
                    [str(BIN / "ub"), "completion", shell],
                    check=False,
                    capture_output=True,
                ).returncode,
                0,
            )

    def test_official_fallback_list_still_has_alternative_mirrors(self):
        args = argparse.Namespace(arch="amd64", mirror=None, timeout=1, limit=8)
        with patch.object(
            mirror, "fetch", return_value=b"http://archive.ubuntu.com/ubuntu/\n"
        ):
            urls = mirror.candidate_urls(args)
        self.assertEqual(len(urls), 3)
        self.assertIn("https://mirrors.tuna.tsinghua.edu.cn/ubuntu", urls)
        self.assertIn("https://mirrors.ustc.edu.cn/ubuntu", urls)


class AITests(unittest.TestCase):
    def test_no_arguments_reaches_install_menu_on_older_python(self):
        original_get_values = argparse.ArgumentParser._get_values

        def legacy_get_values(parser, action, values):
            # Python 3.10 checks [] against choices for nargs="*".
            if action.nargs == "*" and not values and action.choices is not None:
                raise argparse.ArgumentError(action, "invalid choice: []")
            return original_get_values(parser, action, values)

        for argv in [None, []]:
            with self.subTest(argv=argv), patch.object(
                argparse.ArgumentParser, "_get_values", legacy_get_values
            ), patch.object(sys, "argv", ["ubtools_ai.py"]), patch.object(
                ai, "choose", return_value=list(ai.TOOLS)
            ) as choose, patch.object(
                ai, "detect_all", return_value=[]
            ), patch.object(ai, "confirm", return_value=False), patch.object(
                ai, "execute"
            ) as execute, redirect_stdout(io.StringIO()):
                self.assertEqual(ai.main(argv), 0)
                choose.assert_called_once_with("install")
                execute.assert_not_called()

    def test_unknown_tool_is_rejected_before_selection_or_installation(self):
        with patch.object(ai, "choose") as choose, patch.object(
            ai, "execute"
        ) as execute, redirect_stdout(io.StringIO()), patch.object(
            sys, "stderr", io.StringIO()
        ) as error, self.assertRaises(SystemExit) as raised:
            ai.main(["install", "unknown-client", "--dry-run"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("unknown tool", error.getvalue())
        choose.assert_not_called()
        execute.assert_not_called()

    def test_interactive_selection_includes_all_tools_and_select_all_binding(self):
        result = subprocess.CompletedProcess([], 0, "codex\nclaude\nopencode\npi\n")
        for language, expected_header in [
            (
                "zh",
                "Tab: 多选 | Ctrl+A: 全选 | Ctrl+D: 清除 | Enter: 继续 | Esc: 退出",
            ),
            (
                "en",
                "Tab: Multi-select | Ctrl+A: Select all | Ctrl+D: Clear | Enter: Continue | Esc: Exit",
            ),
        ]:
            with self.subTest(language=language), patch.dict(
                os.environ, UBTOOLS_LANG=language
            ), patch.object(ai.shutil, "which", return_value="/bin/fzf"), patch.object(
                ai, "run", return_value=result
            ) as run, patch.object(ai, "detect_all", return_value=[]):
                self.assertEqual(ai.choose("install"), list(ai.TOOLS))
            arguments, kwargs = run.call_args
            self.assertIn("ctrl-a:select-all,ctrl-d:deselect-all", arguments[0])
            self.assertEqual(
                arguments[0][arguments[0].index("--header") + 1], expected_header
            )
            state = "未安装" if language == "zh" else "Not installed"
            self.assertEqual(kwargs["input"], "".join(f"{name}\t{state}\t-\n" for name in ai.TOOLS))

    def test_separate_remove_menu_shows_only_installed_tools(self):
        installed = ai.Installation('/local/bin/codex', 'npm', '@openai/codex')
        result = subprocess.CompletedProcess([], 0, 'codex\tInstalled\tnpm\t/local/bin/codex\n')
        with patch.object(ai.shutil, 'which', return_value='/bin/fzf'), patch.object(
            ai, 'detect_all', side_effect=lambda name: [installed] if name == 'codex' else []
        ), patch.object(ai, 'run', return_value=result) as run:
            self.assertEqual(ai.choose('uninstall'), [('codex', installed)])
        rows = run.call_args.kwargs['input']
        self.assertIn('codex\t', rows)
        self.assertNotIn('pi\t', rows)
        self.assertFalse(any(arg.startswith('--expect') for arg in run.call_args.args[0]))

    def test_remove_menu_previews_and_requires_confirmation(self):
        installed = ai.Installation('/local/bin/codex', 'npm', '@openai/codex')
        with patch.object(ai, 'choose', return_value=['codex']) as choose, patch.object(
            ai, 'detect_all', return_value=[installed]
        ), patch.object(ai, 'confirm', return_value=False) as confirm, patch.object(
            ai, 'execute'
        ) as execute, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ai.main(['remove']), 0)
        choose.assert_called_once_with('uninstall')
        self.assertIn('npm uninstall --global @openai/codex', output.getvalue())
        confirm.assert_called_once()
        execute.assert_not_called()

    def test_remove_menu_confirmed_uninstall_uses_existing_manager(self):
        installed = ai.Installation('/local/bin/codex', 'npm', '@openai/codex')
        with patch.object(ai, 'choose', return_value=['codex']), patch.object(
            ai, 'detect_all', side_effect=[[installed], []]
        ), patch.object(ai, 'confirm', return_value=True), patch.object(ai, 'execute') as execute, redirect_stdout(io.StringIO()):
            self.assertEqual(ai.main(['remove']), 0)
        execute.assert_called_once_with([['npm', 'uninstall', '--global', '@openai/codex']], 15)

    def test_remove_and_legacy_uninstall_support_named_tools_and_dry_run(self):
        installed = ai.Installation('/local/bin/codex', 'npm', '@openai/codex')
        for action in ['remove', 'uninstall']:
            with self.subTest(action=action), patch.object(ai, 'detect_all', return_value=[installed]), patch.object(
                ai, 'execute'
            ) as execute, patch.object(ai, 'choose') as choose, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(ai.main([action, 'codex', '--dry-run']), 0)
            self.assertIn('npm uninstall --global @openai/codex', output.getvalue())
            execute.assert_not_called()
            choose.assert_not_called()

    def test_remove_skips_missing_tools(self):
        with patch.object(ai, 'choose', return_value=['pi']), patch.object(
            ai, 'detect_all', return_value=[]
        ), patch.object(ai, 'confirm') as confirm, patch.object(ai, 'execute') as execute, redirect_stdout(io.StringIO()):
            self.assertEqual(ai.main(['remove']), 0)
        confirm.assert_not_called()
        execute.assert_not_called()

    def test_menu_status_is_explicit_and_offline(self):
        with patch.object(ai, 'choose'), patch.object(
            ai, 'detect_all', side_effect=lambda name: [ai.Installation('/local/bin/codex', 'npm', '@openai/codex')] if name == 'codex' else []
        ), patch.object(ai, 'version', return_value=('1.0', False)), patch.object(ai, 'fetch') as fetch, patch.object(
            ai, 'execute'
        ) as execute, patch.dict(os.environ, UBTOOLS_LANG='zh'), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ai.main(['status', 'codex', 'pi']), 0)
        self.assertIn('已安装', output.getvalue())
        self.assertIn('未安装', output.getvalue())
        fetch.assert_not_called()
        execute.assert_not_called()

    def test_install_menu_cancel_does_not_execute(self):
        with patch.object(ai, 'choose', return_value=[]), patch.object(
            ai, 'confirm'
        ) as confirm, patch.object(ai, 'execute') as execute:
            self.assertEqual(ai.main([]), 0)
        confirm.assert_not_called()
        execute.assert_not_called()

    @unittest.skipUnless(shutil.which('fzf'), 'real fzf is unavailable')
    def test_real_fzf_install_menu_searches_only_tool_names(self):
        installed = ai.Installation('/local/bin/codex', 'npm', '@openai/codex')
        for query, expected in [('codex', ['codex']), ('npm', []), ('Installed', [])]:
            with self.subTest(query=query), patch.dict(os.environ, FZF_DEFAULT_OPTS=f'--filter={query}'), patch.object(
                ai, 'detect_all', return_value=[installed]
            ):
                self.assertEqual(ai.choose('install'), expected)

    @unittest.skipUnless(shutil.which("fzf"), "real fzf is unavailable")
    def test_real_fzf_can_select_all_tools_for_install_preview(self):
        with patch.dict(os.environ, FZF_DEFAULT_OPTS="--filter="), patch.object(
            ai, "detect_all", return_value=[]
        ), patch.object(ai, "execute") as execute, patch.object(
            ai, "fetch"
        ) as fetch, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ai.main(["install", "--dry-run"]), 0)
        for name in ai.TOOLS:
            self.assertIn(f"{name}: missing", output.getvalue())
        execute.assert_not_called()
        fetch.assert_not_called()

    def test_fresh_install_dry_run_does_not_download_or_execute(self):
        with patch.object(ai, "detect_all", return_value=[]), patch.object(
            ai, "fetch"
        ) as fetch, patch.object(ai, "execute") as execute, redirect_stdout(
            io.StringIO()
        ) as output:
            self.assertEqual(ai.main(["install", "--all", "--dry-run"]), 0)
        self.assertIn("https://chatgpt.com/codex/install.sh", output.getvalue())
        self.assertIn("https://claude.ai/install.sh", output.getvalue())
        self.assertIn("https://opencode.ai/install", output.getvalue())
        self.assertIn("https://pi.dev/install.sh", output.getvalue())
        fetch.assert_not_called()
        execute.assert_not_called()

    def test_pi_install_and_update_plans_use_official_channels(self):
        self.assertEqual(
            ai.plan("pi", ai.Installation(), "install"),
            [["@installer", "https://pi.dev/install.sh", "sh"]],
        )
        self.assertEqual(
            ai.plan("pi", ai.Installation("/local/pi", "native"), "update"),
            [["/local/pi", "update"]],
        )
        self.assertEqual(
            ai.plan(
                "pi",
                ai.Installation("/bin/pi", "npm", "@earendil-works/pi-coding-agent"),
                "update",
            ),
            [
                [
                    "npm",
                    "install",
                    "--global",
                    "--ignore-scripts",
                    "@earendil-works/pi-coding-agent@latest",
                ]
            ],
        )
        self.assertEqual(
            ai.plan(
                "pi",
                ai.Installation("/bin/pi", "npm", "@mariozechner/pi-coding-agent"),
                "update",
            ),
            [["/bin/pi", "update"], ["/bin/pi", "update"]],
        )

    def test_pi_managed_node_modules_install_is_detected_as_native(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / ".pi/agent"
            executable = (
                root
                / "install/releases/1/node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
            )
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            launcher = home / ".local/bin/pi"
            launcher.parent.mkdir(parents=True)
            launcher.symlink_to(executable)
            with patch.object(ai.Path, "home", return_value=home), patch.dict(
                os.environ, PI_CODING_AGENT_DIR=str(root)
            ), patch.object(
                ai.shutil,
                "which",
                side_effect=lambda name: str(launcher) if name == "pi" else None,
            ):
                found = ai.detect("pi")
            self.assertEqual(found.method, "native")
            self.assertEqual(
                ai.plan("pi", found, "update"), [[str(launcher), "update"]]
            )

    def test_pi_managed_launcher_outside_path_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            launcher = root / "bin/pi"
            launcher.parent.mkdir()
            launcher.write_text("#!/bin/sh\nexit 0\n")
            launcher.chmod(0o755)
            with patch.dict(os.environ, PI_CODING_AGENT_DIR=str(root)), patch.object(
                ai.shutil, "which", return_value=None
            ):
                found = ai.detect("pi")
            self.assertEqual(found.path, str(launcher))
            self.assertEqual(found.method, "native")

    def test_pi_npm_detection_preserves_legacy_package_for_migration(self):
        for package in [
            "@mariozechner/pi-coding-agent",
            "@earendil-works/pi-coding-agent",
        ]:
            executable = f"/tmp/node_modules/{package}/dist/cli.js"
            with self.subTest(package=package), patch.object(
                ai.shutil,
                "which",
                side_effect=lambda name, executable=executable: (
                    executable if name == "pi" else None
                ),
            ):
                found = ai.detect("pi")
                self.assertEqual(found.method, "npm")
                self.assertEqual(found.package, package)

    def test_pi_dry_run_and_latest_version_query(self):
        with patch.object(ai, "detect_all", return_value=[]), patch.object(
            ai, "fetch", return_value=b'{"version":"1.2.3"}'
        ) as fetch, patch.object(ai, "execute") as execute, redirect_stdout(
            io.StringIO()
        ) as output:
            self.assertEqual(ai.main(["install", "pi", "--dry-run"]), 0)
            fetch.assert_not_called()
            execute.assert_not_called()
            self.assertEqual(ai.main(["status", "pi", "--latest"]), 0)
        self.assertIn("https://pi.dev/install.sh", output.getvalue())
        self.assertIn("npm-latest=1.2.3", output.getvalue())
        self.assertEqual(
            fetch.call_args.args[0],
            "https://registry.npmjs.org/@earendil-works%2Fpi-coding-agent/latest",
        )

    def test_npm_and_native_updates_use_the_existing_method(self):
        self.assertEqual(
            ai.plan(
                "codex", ai.Installation("/bin/codex", "npm", "@openai/codex"), "update"
            ),
            [["npm", "install", "--global", "@openai/codex@latest"]],
        )
        self.assertEqual(
            ai.plan("claude", ai.Installation("/bin/claude", "native"), "update"),
            [["/bin/claude", "update"]],
        )
        self.assertEqual(
            ai.plan("opencode", ai.Installation("/bin/opencode", "native"), "update"),
            [["/bin/opencode", "upgrade", "--method", "curl"]],
        )
        with self.assertRaises(ValueError):
            ai.plan("codex", ai.Installation("/some/wrapper", "unmanaged"), "update")

    def test_distribution_owner_takes_precedence_over_node_modules(self):
        found = "/tmp/node_modules/@openai/codex/bin/codex.js"

        def which(name):
            return (
                found
                if name == "codex"
                else "/bin/dpkg-query"
                if name == "dpkg-query"
                else None
            )

        result = subprocess.CompletedProcess([], 0, "codex: " + found + "\n", "")
        with patch.object(ai.shutil, "which", side_effect=which), patch.object(
            ai, "run", return_value=result
        ):
            self.assertEqual(ai.detect("codex").method, "apt")

    def test_declined_install_does_not_execute(self):
        with patch.object(ai, "detect_all", return_value=[]), patch.object(
            ai, "confirm", return_value=False
        ), patch.object(ai, "execute") as execute, redirect_stdout(io.StringIO()):
            self.assertEqual(ai.main(["install", "codex"]), 0)
        execute.assert_not_called()

    def test_missing_clients_are_skipped_on_update(self):
        with patch.object(ai, "detect_all", return_value=[]), patch.object(
            ai, "execute"
        ) as execute, redirect_stdout(io.StringIO()):
            self.assertEqual(ai.main(["update", "--all"]), 0)
        execute.assert_not_called()

    def test_offline_status_does_not_query_versions_online(self):
        # The doctor dependency probe must not depend on what the host has
        # installed; this test is about offline behaviour, not environment health.
        dependencies = {"curl", "bash", "tar", "unzip"}

        def which(name):
            return f"/usr/bin/{name}" if name in dependencies else None

        with patch.object(ai, "detect_all", return_value=[]), patch.object(
            ai, "fetch"
        ) as fetch, patch.object(
            ai.shutil, "which", side_effect=which
        ), redirect_stdout(io.StringIO()):
            self.assertEqual(ai.main(["status"]), 0)
            self.assertEqual(ai.main(["doctor", "--offline"]), 0)
        fetch.assert_not_called()

    def test_official_script_runs_as_file_and_rejects_html(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "installed"
            data = f'#!/bin/sh\nprintf installed > "{marker}"\n'.encode()
            steps = ai.plan("codex", ai.Installation(), "install")
            with patch.object(ai, "fetch", return_value=data) as fetch:
                ai.execute(steps, 1)
                fetch.assert_called_once_with(
                    ai.TOOLS["codex"]["url"], timeout=1, limit=2 * 1024 * 1024
                )
            self.assertEqual(marker.read_text(), "installed")
            with patch.object(
                ai, "fetch", return_value=b"<html>error</html>"
            ), self.assertRaises(ValueError):
                ai.execute(steps, 1)


@unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgv"), "GnuPG unavailable")
class MirrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.base = Path(cls.fixture.name)
        cls.gpg_home = cls.base / "gnupg"
        cls.gpg_home.mkdir(mode=0o700)
        prefix = [
            "gpg",
            "--homedir",
            str(cls.gpg_home),
            "--batch",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            "",
        ]
        subprocess.run(
            prefix
            + ["--quick-generate-key", "ubtools test fixture", "ed25519", "sign", "0"],
            check=True,
            capture_output=True,
        )
        exported = subprocess.run(
            prefix + ["--export"], check=True, capture_output=True
        ).stdout
        cls.keyring = cls.base / "ubuntu-archive-keyring.gpg"
        cls.keyring.write_bytes(exported)
        cls.index = b"Package: test-package\nVersion: 1.0\n" * 2048
        cls.releases = {}
        for kind in ["fresh", "stale", "expired", "wrongarch"]:
            for suite in ["noble", "noble-updates"]:
                content = cls.index if kind != "stale" else b"old package index"
                release = (
                    f"Origin: Ubuntu\nSuite: {suite}\nCodename: noble\n"
                    f"Architectures: {'arm64' if kind == 'wrongarch' else 'amd64'}\n"
                    f"Date: Mon, 01 Jan 2024 00:00:00 UTC\n"
                    f"Valid-Until: {'Mon, 01 Jan 2001' if kind == 'expired' else 'Wed, 01 Jan 2070'} 00:00:00 UTC\n"
                    f"SHA256:\n {hashlib.sha256(content).hexdigest()} {len(content)} main/binary-amd64/Packages\n"
                )
                file = cls.base / f"{kind}-{suite}"
                file.write_text(release)
                output = cls.base / (file.name + ".signed")
                subprocess.run(
                    prefix
                    + ["--armor", "--output", str(output), "--clearsign", str(file)],
                    check=True,
                    capture_output=True,
                )
                cls.releases[kind, suite] = output.read_bytes()
        owner = cls

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parts = self.path.split("/")
                if len(parts) < 5:
                    self.send_error(404)
                    return
                kind, suite = parts[1], parts[3]
                mapping = {
                    "reference": "fresh",
                    "fast": "fresh",
                    "slow": "fresh",
                    "bad": "fresh",
                    "stale": "stale",
                    "expired": "expired",
                    "wrongarch": "wrongarch",
                }
                if kind not in mapping or suite not in {"noble", "noble-updates"}:
                    self.send_error(404)
                    return
                if self.path.endswith("/InRelease"):
                    data = owner.releases[mapping[kind], suite]
                    if kind == "bad":
                        data = data.replace(b"Origin: Ubuntu", b"Origin: BadTest")
                else:
                    if kind == "slow":
                        time.sleep(0.08)
                    data = owner.index
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        subprocess.run(
            ["gpgconf", "--homedir", str(cls.gpg_home), "--kill", "gpg-agent"],
            check=False,
            capture_output=True,
        )
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.apt = self.root / "apt"
        (self.apt / "sources.list.d").mkdir(parents=True)
        self.source = self.apt / "sources.list.d/ubuntu.sources"
        self.original = (
            b"# Ubuntu archive\nTypes: deb deb-src\nURIs: http://archive.ubuntu.com/ubuntu\n"
            b"Suites: noble\n noble-updates\nComponents: main universe\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n\n"
            b"Types: deb\nURIs: http://security.ubuntu.com/ubuntu\nSuites: noble-security\nComponents: main\n\n"
            b"Types: deb\nURIs: https://vendor.example/apt\nSuites: noble\nComponents: main\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n\n"
            b"Enabled: no\nTypes: deb\nURIs: http://archive.ubuntu.com/ubuntu\nSuites: noble\n"
        )
        self.source.write_bytes(self.original)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        apt_get = self.bin / "apt-get"
        apt_get.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_APT_LOG"\nexit "${TEST_APT_EXIT:-0}"\n'
        )
        apt_get.chmod(0o755)
        self.env = patch.dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            TEST_APT_LOG=str(self.root / "apt.log"),
            TEST_APT_EXIT="0",
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.args = [
            "--apt-dir",
            str(self.apt),
            "--state-dir",
            str(self.root / "state"),
            "--keyring",
            str(self.keyring),
            "--reference",
            self.url + "/reference",
            "--arch",
            "amd64",
            "--timeout",
            "2",
        ]

    def call(self, *args):
        with redirect_stdout(io.StringIO()) as output:
            result = mirror.main([*args, *self.args])
        self.assertEqual(result, 0)
        return output.getvalue()

    def test_signed_fastest_mirror_wins_without_modifying_sources(self):
        output = self.call(
            "test",
            "--mirror",
            self.url + "/slow",
            "--mirror",
            self.url + "/fast",
            "--json",
        )
        results = json.loads(output)
        self.assertEqual(results[0]["url"], self.url + "/fast")
        self.assertTrue(all(item["ok"] for item in results))
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse((self.root / "apt.log").exists())

    def test_invalid_signature_stale_expired_and_wrong_arch_are_rejected(self):
        candidates = []
        for kind in ["fast", "bad", "stale", "expired", "wrongarch"]:
            candidates += ["--mirror", self.url + "/" + kind]
        output = self.call("test", *candidates, "--json")
        rows = json.loads(output)
        self.assertEqual(sum(item["ok"] for item in rows), 1)
        self.assertEqual(rows[0]["url"], self.url + "/fast")

    def test_auto_backs_up_changes_only_ubuntu_and_restore_is_exact(self):
        self.call("auto", "--mirror", self.url + "/fast", "--yes")
        changed = self.source.read_text()
        self.assertIn(self.url + "/fast", changed)
        self.assertIn("http://security.ubuntu.com/ubuntu", changed)
        self.assertIn("https://vendor.example/apt", changed)
        self.assertIn(
            "Enabled: no\nTypes: deb\nURIs: http://archive.ubuntu.com/ubuntu", changed
        )
        self.assertIn(
            "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg", changed
        )
        self.assertIn("Dir::State::lists=", (self.root / "apt.log").read_text())
        self.call("restore", "--yes")
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_failed_apt_update_rolls_back_sources(self):
        with patch.dict(os.environ, TEST_APT_EXIT="1"), redirect_stdout(
            io.StringIO()
        ), self.assertRaises(RuntimeError):
            mirror.main(["auto", "--mirror", self.url + "/fast", "--yes", *self.args])
        self.assertEqual(self.source.read_bytes(), self.original)
        manifest = next((self.root / "state").glob("*/manifest.json"))
        self.assertTrue(json.loads(manifest.read_text())["restored"])

    def test_auto_dry_run_does_not_change_sources_or_create_backups(self):
        self.call("auto", "--mirror", self.url + "/fast", "--dry-run")
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse((self.root / "state").exists())
        self.assertFalse((self.root / "apt.log").exists())

    def test_restore_refuses_subsequent_manual_changes(self):
        self.call("auto", "--mirror", self.url + "/fast", "--yes")
        self.source.write_bytes(self.source.read_bytes() + b"\n# manual edit\n")
        with self.assertRaises(ValueError), redirect_stdout(io.StringIO()):
            mirror.main(["restore", "--yes", *self.args])
        self.assertIn(b"# manual edit", self.source.read_bytes())

    def test_legacy_sources_preserve_options_comments_and_third_party(self):
        self.source.unlink()
        file = self.apt / "sources.list"
        original = "# original\ndeb [arch=amd64] http://archive.ubuntu.com/ubuntu noble main # keep\ndeb https://vendor.example/apt stable main\n"
        file.write_text(original)
        self.call("auto", "--mirror", self.url + "/fast", "--yes")
        self.assertIn(
            f"deb [arch=amd64] {self.url}/fast noble main # keep", file.read_text()
        )
        self.assertIn("deb https://vendor.example/apt stable main", file.read_text())
        self.call("restore", "--yes")
        self.assertEqual(file.read_text(), original)


if __name__ == "__main__":
    unittest.main()
