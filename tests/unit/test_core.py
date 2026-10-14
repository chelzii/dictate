import collections
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dictate.protocol import Lines
from dictate.hotkeys import same_target
from dictate.daemon import Daemon
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


class PendingInsertTests(unittest.TestCase):
    def daemon(self):
        daemon = Daemon.__new__(Daemon)
        daemon.pending_insert = '保留的转写'
        daemon.phase = 'error'
        daemon.history = collections.deque([{'text': '保留的转写', 'at': '12:00'}])
        daemon.paste = Mock()
        daemon.record = Mock()
        daemon.show = Mock()
        daemon.send_bridge = Mock()
        return daemon

    def test_successful_retry_consumes_pending_marker_but_keeps_history(self):
        daemon = self.daemon()
        target = {'window': 1, 'focus': 2}

        self.assertTrue(daemon.retry_pending_insert(target))

        daemon.paste.assert_called_once_with('保留的转写', target)
        self.assertIsNone(daemon.pending_insert)
        self.assertEqual(daemon.history[0]['text'], '保留的转写')
        daemon.send_bridge.assert_called_once_with({
            'type': 'retry-insert-result', 'ok': True, 'status': '文字已重新插入当前输入框。'})

    def test_failed_retry_remains_pending(self):
        daemon = self.daemon()
        daemon.paste.side_effect = ValueError('输入焦点已改变')

        self.assertTrue(daemon.retry_pending_insert({'window': 1, 'focus': 2}))

        self.assertEqual(daemon.pending_insert, '保留的转写')
        daemon.show.assert_called_once_with(
            'error', '输入焦点已改变', retryInsert=True, fix='copy')

    def test_failed_automatic_insert_becomes_pending(self):
        daemon = self.daemon()
        daemon.pending_insert = None
        daemon.history.clear()
        daemon.push_menu = Mock()
        daemon.paste.side_effect = ValueError('输入焦点已改变')

        daemon.on_bridge({'type': 'insert', 'requestId': '7', 'text': '新的转写',
                          'target': {'window': 1, 'focus': 2}})

        self.assertEqual(daemon.pending_insert, '新的转写')
        self.assertEqual(daemon.history[0]['text'], '新的转写')
        daemon.send_bridge.assert_called_once_with({
            'type': 'insert-result', 'requestId': '7', 'ok': False, 'error': '输入焦点已改变'})

    def test_f8_retries_pending_result_instead_of_sending_cancel(self):
        daemon = self.daemon()
        target = {'window': 1, 'focus': 2}
        daemon.settings = {'sleeping': False}
        daemon.closing = False
        daemon.pending = None
        daemon.extension_ready = True
        daemon.focus = Mock(return_value=target)
        daemon.retry_pending_insert = Mock(return_value=True)
        daemon.command = Mock()

        daemon.on_key('cancel', key_at=123)

        daemon.retry_pending_insert.assert_called_once_with(target)
        daemon.command.assert_not_called()

    def test_f8_still_cancels_during_an_active_task(self):
        daemon = self.daemon()
        daemon.phase = 'recording'
        daemon.settings = {'sleeping': False}
        daemon.closing = False
        daemon.pending = None
        daemon.extension_ready = True
        daemon.focus = Mock(return_value={'window': 1, 'focus': 2})
        daemon.retry_pending_insert = Mock(return_value=True)
        daemon.command = Mock()

        daemon.on_key('cancel', key_at=123)

        daemon.retry_pending_insert.assert_not_called()
        daemon.command.assert_called_once_with(
            'cancel', target={'window': 1, 'focus': 2}, keyAt=123000)

    def test_starting_a_new_dictation_discards_pending_retry(self):
        daemon = self.daemon()
        daemon.settings = {'sleeping': False}
        daemon.closing = False
        daemon.recording = None
        daemon.sound = Mock()
        daemon.start_recording = Mock()
        daemon.stop_recording = Mock()

        daemon.on_status({'phase': 'starting', 'status': '正在启动'})

        self.assertIsNone(daemon.pending_insert)


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
