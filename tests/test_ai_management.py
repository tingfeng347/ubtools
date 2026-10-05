"""Source-specific AI management verified against isolated executable fixtures."""
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
ai = importlib.import_module('ubtools_ai')


class DiscoveryAndOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.prefix = self.home / 'node-v22'
        self.npm_bin = self.prefix / 'bin'
        self.target = self.prefix / 'lib/node_modules/@openai/codex/bin/codex.js'
        self.native = self.home / '.local/bin/codex'
        self.write_tool(self.target, '1.0.0')
        self.npm_bin.mkdir(parents=True)
        self.launcher = self.npm_bin / 'codex'
        self.launcher.symlink_to(self.target)
        self.write_tool(self.native, '2.0.0')
        self.alias = self.home / 'aliases/codex'
        self.alias.parent.mkdir()
        self.alias.symlink_to(self.target)
        manager = self.npm_bin / 'npm'
        manager.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
Path(os.environ['RECORD']).write_text(json.dumps(args))
prefix = Path(args[args.index('--prefix') + 1])
target = prefix / 'lib/node_modules/@openai/codex/bin/codex.js'
if os.environ.get('FAIL_COMMAND'):
    raise SystemExit(2)
if args[0] == 'uninstall' and not os.environ.get('KEEP_TOOL'):
    (prefix / 'bin/codex').unlink()
    target.unlink()
elif args[0] == 'install':
    target.write_text("#!/bin/sh\\nprintf 'codex-cli 3.0.0\\\\n'\\n")
''')
        manager.chmod(0o755)
        self.record = self.home / 'command.json'
        self.config = self.home / '.codex/auth.json'
        self.config.parent.mkdir()
        self.config.write_text('fixture-settings')
        env = dict(PATH=os.pathsep.join([str(self.npm_bin), str(self.alias.parent)]),
                   UBTOOLS_LANG='en', RECORD=str(self.record),
                   CODEX_HOME=str(self.config.parent), NVM_DIR=str(self.home / '.nvm'),
                   PI_CODING_AGENT_DIR=str(self.home / '.pi/agent'))
        self.environment = patch.dict(os.environ, env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.home_patch = patch.object(ai.Path, 'home', return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

    def write_tool(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!/bin/sh\nprintf 'codex-cli {value}\\n'\n")
        path.chmod(0o755)

    def run_command(self, arguments):
        with redirect_stdout(io.StringIO()) as output:
            result = ai.main(arguments)
        return result, output.getvalue()

    def test_discovers_hidden_native_install_and_deduplicates_symlink_aliases(self):
        found = ai.detect_all('codex')
        self.assertEqual([item.method for item in found], ['npm', 'native'])
        self.assertEqual(found[0].prefix, str(self.prefix))
        self.assertIn(str(self.alias), found[0].aliases)
        self.assertEqual(ai.detect('codex').path, str(self.launcher))
        self.assertEqual(found[1].path, str(self.native))

    def test_discovers_other_nvm_version_outside_path(self):
        hidden = self.home / '.nvm/versions/node/v20/bin/codex'
        self.write_tool(hidden, '0.9.0')
        self.assertIn(str(hidden), [item.path for item in ai.detect_all('codex')])

    def test_hidden_nvm_npm_installation_uses_its_own_manager_and_prefix(self):
        hidden_prefix = self.home / '.nvm/versions/node/v20'
        target = hidden_prefix / 'lib/node_modules/@openai/codex/bin/codex.js'
        self.write_tool(target, '0.9.0')
        launcher = hidden_prefix / 'bin/codex'
        launcher.parent.mkdir()
        launcher.symlink_to(target)
        manager = launcher.parent / 'npm'
        manager.write_bytes((self.npm_bin / 'npm').read_bytes())
        manager.chmod(0o755)
        result, output = self.run_command(['remove', 'codex', '--path', str(launcher), '--yes'])
        self.assertEqual(result, 0)
        self.assertFalse(target.exists())
        self.assertTrue(self.target.exists())
        self.assertTrue(self.native.exists())
        args = json.loads(self.record.read_text())
        self.assertEqual(args[args.index('--prefix') + 1], str(hidden_prefix))
        self.assertIn('2 other installation(s) remain', output)

    def test_configured_native_directory_does_not_hide_the_default_native_copy(self):
        custom = self.home / 'custom/codex'
        self.write_tool(custom, '0.8.0')
        with patch.dict(os.environ, CODEX_INSTALL_DIR=str(custom.parent)):
            installed = ai.detect_all('codex')
            self.assertEqual([item.method for item in installed], ['npm', 'native', 'native'])
            result, _ = self.run_command(['remove', 'codex', '--path', str(custom), '--yes'])
        self.assertEqual(result, 0)
        self.assertTrue(self.native.exists())
        self.assertFalse(custom.exists())

    def test_status_reports_each_copy_and_active_path(self):
        result, output = self.run_command(['status', 'codex'])
        self.assertEqual(result, 0)
        self.assertIn('2 installations detected', output)
        self.assertIn('1.0.0', output)
        self.assertIn('2.0.0', output)
        self.assertIn('[Active]', output)

    def test_ambiguous_named_removal_requires_a_specific_source(self):
        with self.assertRaisesRegex(ValueError, 'multiple installations'):
            ai.main(['remove', 'codex', '--yes'])
        self.assertFalse(self.record.exists())
        self.assertTrue(self.native.exists())

    def test_named_path_removes_only_that_npm_prefix_and_refreshes_remaining_copy(self):
        result, output = self.run_command(['remove', 'codex', '--path', str(self.launcher), '--yes'])
        self.assertEqual(result, 0)
        self.assertFalse(self.launcher.exists())
        self.assertTrue(self.native.exists())
        self.assertIn('other installation(s) remain', output)
        self.assertIn(str(self.native), output)
        args = json.loads(self.record.read_text())
        self.assertEqual(args[0], 'uninstall')
        self.assertEqual(args[args.index('--prefix') + 1], str(self.prefix))
        self.assertEqual(self.config.read_text(), 'fixture-settings')

    def test_alias_path_can_select_the_same_installation(self):
        result, _ = self.run_command(['remove', 'codex', '--path', str(self.alias), '--yes'])
        self.assertEqual(result, 0)
        self.assertTrue(self.native.exists())
        self.assertFalse(self.target.exists())

    def test_removing_native_copy_keeps_npm_and_settings(self):
        result, output = self.run_command(['remove', 'codex', '--path', str(self.native), '--yes'])
        self.assertEqual(result, 0)
        self.assertFalse(self.native.exists())
        self.assertTrue(self.target.exists())
        self.assertIn(str(self.launcher), output)
        self.assertEqual(self.config.read_text(), 'fixture-settings')

    def test_remove_all_verifies_not_installed(self):
        result, output = self.run_command(['remove', '--all', '--yes'])
        self.assertEqual(result, 0)
        self.assertEqual(ai.detect_all('codex'), [])
        self.assertIn('verified not installed', output)
        self.assertTrue(self.config.exists())

    def test_zero_exit_without_removal_is_reported_as_incomplete(self):
        with patch.dict(os.environ, KEEP_TOOL='1'):
            result, output = self.run_command(['remove', 'codex', '--path', str(self.launcher), '--yes'])
        self.assertEqual(result, 1)
        self.assertIn('removal incomplete', output)
        self.assertTrue(self.target.exists())

    def test_failed_command_still_refreshes_the_actual_installation_state(self):
        with patch.dict(os.environ, FAIL_COMMAND='1'):
            result, output = self.run_command(['remove', 'codex', '--path', str(self.launcher), '--yes'])
        self.assertEqual(result, 1)
        self.assertIn('Remaining:', output)
        self.assertIn(str(self.launcher), output)

    def test_update_rechecks_version_and_reports_duplicate_installations(self):
        result, output = self.run_command(['update', 'codex', '--yes'])
        self.assertEqual(result, 0)
        self.assertIn('3.0.0', output)
        self.assertIn('2 installations detected', output)
        self.assertIn(str(self.native), output)

    def test_install_rechecks_version_after_existing_source_is_updated(self):
        result, output = self.run_command(['install', 'codex', '--yes'])
        self.assertEqual(result, 0)
        self.assertIn('3.0.0', output)
        self.assertIn('2 installations detected', output)

    def test_fresh_installer_that_exits_without_installing_is_not_successful(self):
        with patch.object(ai, 'detect_all', return_value=[]), patch.object(ai, 'execute'), patch.object(
            ai, 'confirm', return_value=True
        ):
            result, output = self.run_command(['install', 'pi'])
        self.assertEqual(result, 1)
        self.assertIn('target installation not found', output)

    def test_check_can_report_local_version_newer_than_upstream(self):
        with patch.object(ai, 'latest', return_value='0.9.0'):
            result, output = self.run_command(['update', 'codex', '--check'])
        self.assertEqual(result, 0)
        self.assertIn('Local version newer', output)

    def test_unknown_removal_path_does_not_modify_any_installation(self):
        with self.assertRaisesRegex(ValueError, 'installation path not found'):
            ai.main(['remove', 'codex', '--path', str(self.home / 'wrong/codex'), '--yes'])
        self.assertFalse(self.record.exists())

    def test_path_requires_one_tool_name(self):
        with redirect_stdout(io.StringIO()), patch.object(sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit) as raised:
            ai.main(['remove', '--all', '--path', str(self.launcher)])
        self.assertEqual(raised.exception.code, 2)

    def test_remove_ui_preserves_the_selected_source(self):
        def selection(arguments, **kwargs):
            rows = kwargs['input'].splitlines()
            chosen = next(row for row in rows if str(self.native) in row)
            return subprocess.CompletedProcess(arguments, 0, chosen + '\n')
        with patch.object(ai.shutil, 'which', side_effect=lambda name: '/bin/fzf' if name == 'fzf' else None), patch.object(
            ai, 'run', side_effect=selection
        ):
            selected = ai.choose('uninstall')
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0][0], 'codex')
        self.assertEqual(selected[0][1].path, str(self.native))

    def test_update_check_compares_all_copies_without_mutating_or_prompting(self):
        with patch.object(ai, 'latest', return_value='2.0.0') as latest, patch.object(
            ai, 'execute'
        ) as execute, patch.object(ai, 'choose') as choose, patch.object(ai, 'confirm') as confirm:
            result, output = self.run_command(['update', '--check'])
        self.assertEqual(result, 0)
        self.assertIn('Update available', output)
        self.assertIn('Up to date', output)
        self.assertIn('Not installed', output)
        latest.assert_called_once_with('codex', 15)
        execute.assert_not_called()
        choose.assert_not_called()
        confirm.assert_not_called()
        self.assertFalse(self.record.exists())


class VersionComparisonTests(unittest.TestCase):
    def test_latest_rejects_non_version_registry_payloads(self):
        for payload in [b'[]', b'{"version":null}', b'{"version":42}', b'{"version":"not-a-version"}']:
            with self.subTest(payload=payload), patch.object(ai, 'fetch', return_value=payload), self.assertRaises(ValueError):
                ai.latest('codex', 1)

    def test_selected_pnpm_and_bun_global_locations_are_explicit(self):
        pnpm = ai.Installation('/fixture/pnpm/pi', 'pnpm', 'pi', target='/fixture/global/5/node_modules/.pnpm/pi/bin/pi', prefix='/fixture/global')
        bun = ai.Installation('/fixture/.bun/bin/codex', 'bun', '@openai/codex', target='/fixture/.bun/install/global/node_modules/@openai/codex/bin/codex', prefix='/fixture/.bun/install/global')
        pnpm_plan = ai.plan('pi', pnpm, 'uninstall')[0]
        self.assertIn('--global-dir', pnpm_plan)
        self.assertIn('/fixture/global', pnpm_plan)
        self.assertIn('--global-bin-dir', pnpm_plan)
        bun_plan = ai.plan('codex', bun, 'uninstall')[0]
        self.assertIn('BUN_INSTALL_GLOBAL_DIR=/fixture/.bun/install/global', bun_plan)
        self.assertIn('BUN_INSTALL_BIN=/fixture/.bun/bin', bun_plan)

    def test_unknown_global_prefix_is_not_removed_using_the_default_manager(self):
        local = ai.Installation('/fixture/local/bin/codex', 'npm', '@openai/codex', target='/fixture/local/node_modules/codex.js')
        with self.assertRaisesRegex(ValueError, 'global installation directory'):
            ai.plan('codex', local, 'uninstall')

    def test_semver_order_including_prereleases_and_build_metadata(self):
        cases = [('codex-cli 1.9.0', '1.10.0', -1),
                 ('2.1.284 (Claude Code)', '2.1.284', 0),
                 ('v1.0.0-rc.2', '1.0.0-rc.10', -1),
                 ('1.0.0-alpha.1', '1.0.0-alpha.beta', -1),
                 ('1.0.0-beta', '1.0.0-beta.1', -1),
                 ('1.0.0-rc.1', '1.0.0', -1),
                 ('1.0.0+local', '1.0.0+upstream', 0),
                 ('3.0.0', '2.0.0', 1),
                 ('nightly', '1.0.0', None),
                 ('1.0.0-01', '1.0.0', None),
                 ('1.2.3.4', '1.2.3', None)]
        for current, latest, expected in cases:
            with self.subTest(current=current, latest=latest):
                self.assertEqual(ai.compare_versions(current, latest), expected)

    def test_failed_online_check_reports_error_and_continues_checks(self):
        found = ai.Installation('/fixture/client', 'native')
        with patch.object(ai, 'detect_all', return_value=[found]), patch.object(
            ai, 'latest', side_effect=[TimeoutError(), '1.0.0']
        ), patch.object(ai, 'version', return_value=('1.0.0', False)), redirect_stdout(io.StringIO()) as output, patch.dict(
            os.environ, UBTOOLS_LANG='en'
        ):
            self.assertEqual(ai.main(['update', 'codex', 'claude', '--check']), 1)
        self.assertIn('codex: check failed', output.getvalue())
        self.assertIn('Up to date', output.getvalue())

    def test_version_probe_failure_is_not_an_available_update(self):
        with patch.object(ai, 'detect_all', return_value=[ai.Installation('/fixture/client', 'npm')]), patch.object(
            ai, 'latest', return_value='1.0.0'
        ), patch.object(ai, 'version', return_value=('version check failed', True)), redirect_stdout(io.StringIO()) as output, patch.dict(
            os.environ, UBTOOLS_LANG='en'
        ):
            self.assertEqual(ai.main(['update', 'codex', '--check']), 1)
        self.assertIn('Cannot compare', output.getvalue())
        self.assertNotIn('Update available', output.getvalue())


if __name__ == '__main__':
    unittest.main()
