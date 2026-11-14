import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from enge_spx.engine import Engine
from enge_spx.exit_timezone import apply_verified_exit
from enge_spx.state import Store, SPXError


class ExitTimezoneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'data')
        self.engine = Engine(self.store)

    def test_final_geo_preserves_manual_value_and_other_settings(self):
        before = self.store.settings()
        before['timezone_mode'] = 'exit'
        before['terminal'] = {'kind': 'custom', 'executable': 'unchanged'}
        self.store.write('settings.json', before)
        evidence = {'ip': '8.8.8.8', 'timezone': 'Asia/Tokyo', 'line_ip': '9.9.9.9', 'line_timezone': 'Europe/London'}
        self.assertEqual(apply_verified_exit(self.engine, evidence), 'Asia/Tokyo')
        after = self.store.settings()
        self.assertEqual(after['manual_timezone'], before['timezone'])
        self.assertEqual(after['terminal'], before['terminal'])
        self.assertEqual(self.store.read('environment.json'), {'timezone': 'Asia/Tokyo'})
        self.assertEqual(apply_verified_exit(self.engine, {**evidence, 'timezone': 'Europe/Berlin'}), 'Europe/Berlin')

    def test_unknown_geo_or_malicious_zone_does_not_silently_fall_back(self):
        for name in (None, '未知', '../../etc/passwd', '/etc/localtime', 'UTC\nTZ=Bad', 'America/../UTC'):
            with self.subTest(name=name), self.assertRaises(SPXError):
                apply_verified_exit(self.engine, {'timezone': name})
        self.assertEqual(self.store.settings()['timezone'], 'America/Los_Angeles')

    def test_manual_mode_ignores_geo_and_existing_environment_can_change(self):
        settings = self.store.settings()
        settings.update(timezone_mode='manual', timezone='Europe/London')
        self.store.write('settings.json', settings)
        self.assertEqual(apply_verified_exit(self.engine, {'timezone': 'Asia/Tokyo'}), 'Europe/London')
        self.store.write('environment.json', {'timezone': 'America/Los_Angeles'})
        with patch.object(self.engine, '_stop') as stop:
            self.engine.save_settings('', 'Asia/Tokyo', 'desktop-linux', {'enabled': False, 'downloads': False}, 'manual')
        stop.assert_called_once()
        self.assertEqual(self.store.settings()['timezone'], 'Asia/Tokyo')

    def test_confirm_rejects_changed_zone_before_starting_guard(self):
        self.store.write('runtime.json', {'phase': 'review', 'checked': __import__('time').time(), 'evidence': {'ip': '8.8.8.8'}})
        with patch.object(self.engine, 'audit_topology'), patch.object(self.engine, 'probe_chain', return_value={'ip': '8.8.8.8', 'timezone': 'Asia/Tokyo'}), patch.object(self.engine, '_stop'), patch.object(self.engine, 'start_guard') as start:
            with self.assertRaises(SPXError):
                self.engine.confirm()
        start.assert_not_called()
