import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate.protocol import Lines
from dictate.hotkeys import same_target
from dictate import install, doctor


class ProtocolTests(unittest.TestCase):
    def test_fragmented_utf8_and_multiple_messages(self):
        parser = Lines()
        payload = json.dumps({'text': '中文'}, ensure_ascii=False).encode() + b'\n{"phase":"done"}\n'
        split = payload.index('中'.encode()) + 1
        self.assertEqual(parser.feed(payload[:split]), [])
        self.assertEqual(parser.feed(payload[split:]), [{'text': '中文'}, {'phase': 'done'}])

    def test_bad_json_does_not_lose_next_message(self):
        self.assertEqual(Lines().feed(b'not-json\n{"ok":true}\n'), [{'ok': True}])


class FocusTests(unittest.TestCase):
    def test_different_window_and_different_child_are_rejected(self):
        self.assertFalse(same_target({'window': 2, 'focus': 4}, {'window': 1, 'focus': 4}))
        self.assertFalse(same_target({'window': 1, 'focus': 3}, {'window': 1, 'focus': 4}))

    def test_toolkit_top_level_focus_proxy_is_accepted(self):
        self.assertTrue(same_target({'window': 1, 'focus': 1}, {'window': 1, 'focus': 4}))
        self.assertTrue(same_target({'window': 1, 'focus': 4}, {'window': 1, 'focus': 1}))


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dictate-install-unit-')
        self.home = Path(self.temp.name)
        self.root = self.home / 'installation'
        self.hosts = [self.home / 'chrome/host.json', self.home / 'chromium/host.json']
        self.stack = contextlib.ExitStack()
        replacements = {'INSTALL': self.root, 'AUTOSTART': self.home / 'autostart.desktop',
                        'COMMAND': self.home / 'bin/dictate'}
        for name, value in replacements.items():
            self.stack.enter_context(patch.object(install, name, value))
        self.stack.enter_context(patch.object(install, 'manifests', return_value=self.hosts))
        self.stack.enter_context(patch.object(install, 'environment_checks', return_value=[]))
        self.stack.enter_context(patch.object(install, 'prepare_python', return_value=Path('/usr/bin/python3')))
        self.stack.enter_context(patch.object(install, 'daemon_pid', return_value=None))
        self.stack.enter_context(patch.object(install, 'stop_daemon'))
        self.stack.enter_context(patch.object(install, 'start_daemon', return_value=None))
        self.stack.enter_context(patch.object(install, 'verify_started'))
        self.stack.enter_context(patch.object(install.subprocess, 'run'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def test_install_repeat_update_uninstall_preserves_user_settings(self):
        settings = self.home / 'settings.json'
        settings.write_text('{"sounds":true}')
        install.install('a' * 32)
        first = os.readlink(self.root / 'current')
        self.assertTrue((self.root / 'current/dictate/daemon.py').is_file())
        self.assertEqual(json.loads(self.hosts[0].read_text())['allowed_origins'], ['chrome-extension://' + 'a' * 32 + '/'])
        install.install('a' * 32)
        self.assertNotEqual(first, os.readlink(self.root / 'current'))
        install.update()
        install.uninstall()
        self.assertFalse(self.root.exists())
        self.assertFalse(install.COMMAND.exists())
        self.assertTrue(all(not h.exists() for h in self.hosts))
        self.assertEqual(settings.read_text(), '{"sounds":true}')

    def test_failure_after_switch_restores_previous_program_and_configuration(self):
        install.install('a' * 32)
        target = os.readlink(self.root / 'current')
        manifest = self.hosts[0].read_bytes()
        command = install.COMMAND.read_bytes()
        with patch.object(install, 'verify_started', side_effect=RuntimeError('failed boot')):
            with self.assertRaisesRegex(RuntimeError, 'failed boot'):
                install.install('b' * 32)
        self.assertEqual(os.readlink(self.root / 'current'), target)
        self.assertEqual(self.hosts[0].read_bytes(), manifest)
        self.assertEqual(install.COMMAND.read_bytes(), command)
        self.assertEqual(len(list((self.root / 'releases').iterdir())), 1)

    def test_first_install_failure_removes_partial_installation(self):
        with patch.object(install, 'verify_started', side_effect=RuntimeError('failed boot')):
            with self.assertRaises(RuntimeError):
                install.install('a' * 32)
        self.assertFalse(self.root.exists())
        self.assertFalse(install.COMMAND.exists())
        self.assertTrue(all(not h.exists() for h in self.hosts))

    def test_invalid_id_and_failed_preflight_do_not_modify_installation(self):
        with self.assertRaises(ValueError):
            install.install('wrong-id')
        with patch.object(install, 'environment_checks', return_value=[{'required': True, 'ok': False, 'name': 'X11', 'detail': 'missing'}]):
            with self.assertRaises(RuntimeError):
                install.install('a' * 32)
        self.assertFalse(self.root.exists())


class DiagnosticsTests(unittest.TestCase):
    def test_stale_status_is_not_reported_as_a_running_service_or_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / 'desktop-status.json').write_text(json.dumps({'pid': 99999999, 'connected': True, 'text': 'private'}))
            with patch.object(doctor, 'CACHE', cache):
                result = doctor.installed_status()
            self.assertFalse(result['running'])
            self.assertFalse(result['connected'])
            self.assertNotIn('private', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
