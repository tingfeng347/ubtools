"""Snap queries reach the backend; fzf matches package names only."""
import subprocess
import unittest
import shutil
import os
import fcntl
import pty
import select
import signal
import shlex
import struct
import termios
import time

import test_ubti_startup as startup


class SearchTests(unittest.TestCase):
    setUp = startup.StartupTests.setUp
    stub = startup.StartupTests.stub
    run_ui = startup.StartupTests.run_ui
    cache = startup.StartupTests.cache

    def snap_search_backend(self):
        self.stub('snap', '''printf '%s\\n' "$*" >> "$PROBE_ROOT/snap-calls"
case "$*" in
'find genact') printf 'Name Version Publisher Notes Summary\\ngenact 0.4.0 publisher - Generator\\n';;
'find') printf 'No search term specified. Here are some interesting snaps:\\n\\nName Version Publisher Notes Summary\\nfeatured-editor 2.0 publisher - Editor\\n\\nProvide a search term for more specific results.\\n';;
esac''')

    def test_initial_query_searches_snap_without_polluting_featured_cache(self):
        self.snap_search_backend()
        cache = self.cache('snap', 'snap featured-editor 2.0\n')
        _, rows = self.run_ui('--snap', 'genact')
        self.assertIn('\tsnap\tgenact\t', rows)
        self.assertIn('find genact', (self.root / 'snap-calls').read_text())
        self.assertEqual(cache.read_text(), 'snap featured-editor 2.0\n')

    def test_featured_output_ignores_headers_blank_lines_and_messages(self):
        self.snap_search_backend()
        _, rows = self.run_ui('--snap', '--refresh')
        self.assertEqual(len(rows.splitlines()), 1)
        self.assertIn('\tsnap\tfeatured-editor\t', rows)

    def test_existing_malformed_featured_cache_is_filtered(self):
        self.cache('snap', 'snap Name Version\nsnap  \nsnap featured-editor 2.0\n')
        _, rows = self.run_ui('--snap')
        self.assertEqual(len(rows.splitlines()), 1)
        self.assertIn('\tsnap\tfeatured-editor\t', rows)

    def test_selection_still_installs_the_package_from_its_source(self):
        self.snap_search_backend()
        self.stub('sudo', 'printf "%s\\n" "$*" > "$PROBE_ROOT/install-command"')
        self.stub('fzf', '''touch "$PROBE_ROOT/ready"
cat > "$PROBE_ROOT/rows"
printf 'genact\\n\\n'
cat "$PROBE_ROOT/rows"
exit 0''')
        self.run_ui('--snap', 'genact')
        self.assertEqual((self.root / 'install-command').read_text(), 'snap install genact\n')

    def test_typing_query_reloads_snap_and_mode_switch_keeps_new_rows(self):
        self.snap_search_backend()
        self.stub('fzf', r'''touch "$PROBE_ROOT/ready"
if [[ ! -f "$PROBE_ROOT/typed" ]]; then
    cat > "$PROBE_ROOT/initial-rows"
    args=("$@")
    for ((i=0; i<${#args[@]}; i++)); do
        if [[ "${args[i]}" == --bind && "${args[i+1]}" == change:reload:* ]]; then
            command="${args[i+1]#change:reload:}"
            command="${command//\{q\}/genact}"
            bash -c "$command" > "$PROBE_ROOT/reloaded-rows" || exit 1
            touch "$PROBE_ROOT/typed"
            printf 'genact\nctrl-e\n'
            exit 0
        fi
    done
    exit 1
fi
cat > "$PROBE_ROOT/rows"
exit 130''')
        _, rows = self.run_ui('--snap')
        self.assertTrue((self.root / 'typed').exists(), 'no query reload binding')
        self.assertIn('\tsnap\tgenact\t', rows)
        self.assertIn('\tsnap\tgenact\t', (self.root / 'reloaded-rows').read_text())

    @unittest.skipUnless(shutil.which('fzf'), 'real fzf is unavailable')
    def test_real_fzf_matches_names_but_not_versions_or_sources(self):
        real_fzf = shutil.which('fzf')
        self.stub('apt', "printf 'Listing...\\ngenact/stable 1.0 amd64\\nother/stable genact amd64\\nstable-name/stable 2.0 amd64\\n'")
        self.stub('fzf', '''touch "$PROBE_ROOT/ready"
printf '%s\\n' "$@" > "$PROBE_ROOT/fzf-args"
cat > "$PROBE_ROOT/rows"
exit 130''')
        _, rows = self.run_ui('--apt', 'genact')
        args = (self.root / 'fzf-args').read_text().splitlines()
        matching = []
        for option in ('--delimiter', '--with-nth', '--nth'):
            value = next((arg.split('=', 1)[1] for arg in args if arg.startswith(option + '=')), None)
            if value is None and option in args:
                value = args[args.index(option) + 1]
            self.assertIsNotNone(value, option)
            matching.extend([option, value])
        for query, expected in [('genact', 'genact'), ('stable', 'stable-name'), ('2.0', None)]:
            result = subprocess.run([real_fzf, '--ansi', *matching, '--filter', query],
                                    input=rows, capture_output=True, text=True, env=self.env)
            matches = [line.split('\t')[2] for line in result.stdout.splitlines()]
            self.assertEqual(matches, [] if expected is None else [expected])

    @unittest.skipUnless(shutil.which('fzf'), 'real fzf is unavailable')
    def test_real_fzf_typing_queries_snap(self):
        self.run_real_fzf_query()

    @unittest.skipUnless(shutil.which('fzf'), 'real fzf is unavailable')
    def test_exit_stops_in_flight_query_reload(self):
        self.run_real_fzf_query(slow=True)

    def run_real_fzf_query(self, slow=False):
        self.snap_search_backend()
        if slow:
            self.stub('snap', '''printf '%s\\n' "$*" >> "$PROBE_ROOT/snap-calls"
if [[ "$*" == 'find genact' ]]; then
    echo $$ > "$PROBE_ROOT/reload-backend-pid"
    sleep 3
    touch "$PROBE_ROOT/reload-backend-finished"
fi
printf 'Name Version\\ngenact 0.4.0\\n' ''')
        self.stub('fzf', f'exec {shlex.quote(shutil.which("fzf"))} "$@"')
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 120, 0, 0))
        env = dict(self.env, TERM='xterm-256color', UBTOOLS_LANG='en',
                   FZF_DEFAULT_OPTS='', FZF_DEFAULT_OPTS_FILE='/dev/null')

        def terminal_session():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

        proc = subprocess.Popen(['bash', str(startup.SCRIPT), '--snap'], env=env,
                                stdin=slave, stdout=slave, stderr=slave,
                                preexec_fn=terminal_session)
        os.close(slave)
        output = b''

        def wait_for(predicate):
            nonlocal output
            deadline = time.monotonic() + 5
            while not predicate():
                self.assertIsNone(proc.poll(), output.decode(errors='replace'))
                self.assertLess(time.monotonic(), deadline, output.decode(errors='replace'))
                if select.select([master], [], [], .05)[0]:
                    chunk = os.read(master, 65536)
                    output += chunk
                    if b'\x1b[6n' in chunk:
                        os.write(master, b'\x1b[1;1R' * chunk.count(b'\x1b[6n'))
                    if b'\x1b[?2004$p' in chunk:
                        os.write(master, b'\x1b[?2004;2$y')

        try:
            wait_for(lambda: b'Tab:Multi' in output)
            os.write(master, b'genact')
            calls = self.root / 'snap-calls'
            wait_for(lambda: calls.exists() and 'find genact\n' in calls.read_text())
            if slow:
                wait_for(lambda: (self.root / 'reload-backend-pid').exists())
            else:
                # The package row includes its version, unlike the typed prompt.
                wait_for(lambda: b'0.4.0' in output)
            os.write(master, b'\x1b')
            proc.wait(timeout=3)
            self.assertEqual(proc.returncode, 0)
            if slow:
                pid = int((self.root / 'reload-backend-pid').read_text())
                status = startup.Path(f'/proc/{pid}/stat')
                deadline = time.monotonic() + .5
                while status.exists() and status.read_text().split()[2] != 'Z':
                    self.assertLess(time.monotonic(), deadline, 'query backend survived UI exit')
                    time.sleep(.01)
                self.assertFalse((self.root / 'reload-backend-finished').exists())
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)
            os.close(master)


if __name__ == '__main__':
    unittest.main()
