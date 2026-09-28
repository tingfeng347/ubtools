"""Exercise the real entry point with deterministic slow package backends."""
import os
import fcntl
import pty
import select
import signal
import shlex
import shutil
import struct
import termios
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'bin' / 'ubti'


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=f'{self.bin}:{os.environ["PATH"]}',
                        XDG_CACHE_HOME=str(self.root / 'cache'),
                        PROBE_ROOT=str(self.root))
        self.stub('dpkg-query', "printf 'vim\\n'")
        self.stub('apt', "printf 'Listing...\\nstable-vim/stable 1.0 amd64\\n'")
        self.stub('snap', "sleep 1; printf 'Name Version\\nsnap-editor 2.0\\n'")
        self.stub('flatpak', '''case "$1" in
list) exit 0;;
remote-ls) sleep 1; printf 'org.editor.App\\t3.0\\n';;
esac''')
        self.stub('fzf', '''touch "$PROBE_ROOT/ready"
cat > "$PROBE_ROOT/rows"
exit 130''')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text('#!/usr/bin/env bash\n' + body + '\n')
        path.chmod(0o755)

    def run_ui(self, *args):
        start = time.monotonic()
        proc = subprocess.Popen(['bash', str(SCRIPT), *args], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        while not (self.root / 'ready').exists() and proc.poll() is None:
            if time.monotonic() - start > 5:
                proc.kill()
                self.fail('fzf did not start within 5s')
            time.sleep(.01)
        ready_time = time.monotonic() - start
        stdout, stderr = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, stderr.decode())
        return ready_time, (self.root / 'rows').read_text()

    def test_cold_start_opens_ui_before_remote_catalogs_finish(self):
        elapsed, rows = self.run_ui()
        print(f'cold startup to fzf: {elapsed:.3f}s')
        self.assertLess(elapsed, .5, 'remote catalog fetch blocks the UI')
        self.assertIn('snap-editor', rows)
        self.assertIn('org.editor.App', rows)
        self.assertIn('stable-vim', rows)

    def cache(self, src, content, stale=False):
        cache = self.root / 'cache' / 'ubti_tui' / f'{src}_packages.txt'
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(content)
        if stale:
            os.utime(cache, (1, 1))
        return cache

    def test_stale_cache_is_visible_before_refresh_finishes(self):
        cache = self.cache('snap', 'snap cached-editor 1.0\n', stale=True)
        self.stub('fzf', '''touch "$PROBE_ROOT/ready"
IFS= read -r first
printf '%s\\n' "$first" > "$PROBE_ROOT/first"
touch "$PROBE_ROOT/first-ready"
cat > "$PROBE_ROOT/rows"
exit 130''')
        started = time.monotonic()
        proc = subprocess.Popen(['bash', str(SCRIPT), '--snap'], env=self.env)
        try:
            while not (self.root / 'first-ready').exists() and proc.poll() is None:
                if time.monotonic() - started > 3:
                    self.fail('no cached row appeared')
                time.sleep(.01)
            elapsed = time.monotonic() - started
            proc.wait(timeout=5)
            self.assertLess(elapsed, .5)
            self.assertIn('cached-editor', (self.root / 'first').read_text())
            self.assertIn('snap-editor', cache.read_text())
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)

    def test_failed_refresh_preserves_cache_and_rejects_partial_output(self):
        cache = self.cache('snap', 'snap cached-editor 1.0\n')
        self.stub('snap', "printf 'Name Version\\npartial-editor 2.0\\n'; exit 1")
        _, rows = self.run_ui('--snap', '--refresh')
        self.assertIn('cached-editor', rows)
        self.assertNotIn('partial-editor', rows)
        self.assertEqual(cache.read_text(), 'snap cached-editor 1.0\n')
        self.assertEqual(list(cache.parent.glob('snap_packages.txt.*')), [])

    def test_selected_source_skips_other_installed_queries(self):
        self.stub('flatpak', 'touch "$PROBE_ROOT/unwanted"; sleep 1; exit 0')
        _, rows = self.run_ui('--apt')
        self.assertIn('stable-vim', rows)
        self.assertFalse((self.root / 'unwanted').exists())

    def test_empty_installed_list_does_not_swallow_catalog(self):
        self.stub('dpkg-query', 'exit 0')
        _, rows = self.run_ui('--apt')
        self.assertIn('stable-vim', rows)

    def test_exit_stops_slow_producer(self):
        self.stub('snap', '''echo $$ > "$PROBE_ROOT/backend-pid"
sleep 3
touch "$PROBE_ROOT/backend-finished"
printf 'Name Version\\nsnap-editor 2.0\\n' ''')
        self.stub('fzf', '''touch "$PROBE_ROOT/ready"
for i in {1..100}; do
    test -f "$PROBE_ROOT/backend-pid" && break
    sleep .01
done
: > "$PROBE_ROOT/rows"
exit 130''')
        start = time.monotonic()
        self.run_ui('--snap')
        self.assertLess(time.monotonic() - start, 1)
        pid = int((self.root / 'backend-pid').read_text())
        # A terminated backend may briefly remain as a zombie awaiting reaping.
        status = Path(f'/proc/{pid}/stat')
        deadline = time.monotonic() + .5
        while status.exists() and status.read_text().split()[2] != 'Z':
            self.assertLess(time.monotonic(), deadline, 'backend survived UI exit')
            time.sleep(.01)
        self.assertFalse((self.root / 'backend-finished').exists())


    def test_mode_switch_during_loading_keeps_all_sources_and_query(self):
        self.stub('fzf', '''touch "$PROBE_ROOT/ready"
if [[ ! -f "$PROBE_ROOT/switched" ]]; then
    IFS= read -r first
    touch "$PROBE_ROOT/switched"
    printf 'editor\\nctrl-e\\n'
    exit 0
fi
printf '%s\\n' "$@" > "$PROBE_ROOT/fzf-args"
cat > "$PROBE_ROOT/rows"
exit 130''')
        _, rows = self.run_ui()
        self.assertIn('snap-editor', rows)
        self.assertIn('org.editor.App', rows)
        args = (self.root / 'fzf-args').read_text().splitlines()
        self.assertIn('--exact', args)
        self.assertEqual(args[args.index('--query') + 1], 'editor')

    def test_ctrl_r_loads_fresh_rows_in_current_session(self):
        self.cache('snap', 'snap cached-editor 1.0\n')
        self.stub('fzf', '''touch "$PROBE_ROOT/ready"
if [[ ! -f "$PROBE_ROOT/refreshed" ]]; then
    cat > "$PROBE_ROOT/old-rows"
    touch "$PROBE_ROOT/refreshed"
    printf 'editor\\nctrl-r\\n'
    exit 0
fi
cat > "$PROBE_ROOT/rows"
exit 130''')
        _, rows = self.run_ui('--snap')
        self.assertIn('cached-editor', (self.root / 'old-rows').read_text())
        self.assertIn('snap-editor', rows)
        self.assertNotIn('cached-editor', rows)

    @unittest.skipUnless(shutil.which('fzf'), 'real fzf is unavailable')
    def test_real_fzf_draws_before_remote_queries_finish(self):
        self.stub('fzf', f'exec {shlex.quote(shutil.which("fzf"))} "$@"')
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 120, 0, 0))
        env = dict(self.env, TERM='xterm-256color', LANG='C', LC_ALL='C',
                   FZF_DEFAULT_OPTS='', FZF_DEFAULT_OPTS_FILE='/dev/null')

        def terminal_session():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

        started = time.monotonic()
        proc = subprocess.Popen(['bash', str(SCRIPT)], env=env,
                                stdin=slave, stdout=slave, stderr=slave,
                                preexec_fn=terminal_session)
        os.close(slave)
        output = b''
        try:
            while b'Tab:Multi' not in output:
                self.assertLess(time.monotonic() - started, 3, 'fzf did not draw')
                if select.select([master], [], [], .05)[0]:
                    chunk = os.read(master, 65536)
                    output += chunk
                    if b'\x1b[6n' in chunk:
                        os.write(master, b'\x1b[1;1R' * chunk.count(b'\x1b[6n'))
                    if b'\x1b[?2004$p' in chunk:
                        os.write(master, b'\x1b[?2004;2$y')
            elapsed = time.monotonic() - started
            print(f'real fzf first screen: {elapsed:.3f}s')
            os.write(master, b'\x1b')
            deadline = time.monotonic() + 3
            while proc.poll() is None:
                self.assertLess(time.monotonic(), deadline, 'fzf did not exit')
                if select.select([master], [], [], .05)[0]:
                    try:
                        os.read(master, 65536)
                    except OSError:
                        break
            proc.wait(timeout=1)
            self.assertEqual(proc.returncode, 0)
            self.assertLess(elapsed, .5)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)
            os.close(master)


if __name__ == '__main__':
    unittest.main()
