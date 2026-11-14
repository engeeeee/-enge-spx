import io
import subprocess
import tarfile
import unittest
from unittest.mock import Mock, patch

from enge_spx.state import SPXError
from enge_spx.workspace_timezone import archive, prepare_project, ready


class WorkspaceTimezoneTests(unittest.TestCase):
    def test_archive_replaces_system_symlink_and_text_without_overwriting_zone_database(self):
        with tarfile.open(fileobj=io.BytesIO(archive('America/Los_Angeles'))) as package:
            self.assertEqual(package.getnames(), ['localtime', 'timezone'])
            link = package.getmember('localtime')
            self.assertTrue(link.issym())
            self.assertEqual(link.linkname, '/usr/share/zoneinfo/America/Los_Angeles')
            self.assertEqual(package.extractfile('timezone').read(), b'America/Los_Angeles\n')
            self.assertEqual(package.getmember('timezone').mode, 0o644)
        for zone in ('../../etc/passwd', '/tmp/zone', 'America/../UTC'):
            with self.assertRaises((ValueError, KeyError)):
                archive(zone)

    def engine(self):
        engine = Mock()
        engine.store.settings.return_value = {'timezone': 'America/Los_Angeles'}
        engine.docker.command.return_value = ['docker', 'cp', '-', 'owned:/etc']
        engine.docker.environment.return_value = {}
        return engine

    def test_system_update_keeps_user_mounts_identity_and_utc_database(self):
        engine = self.engine()
        obj = {'Id': 'owned', 'HostConfig': {'ReadonlyRootfs': False}, 'Config': {'User': '1000:1000'}}
        before = {'tzif_matches': False, 'timezone_text_matches': False, 'process_tz_matches': True, 'utc_tzif_sha256': 'public-utc'}
        after = {**before, 'tzif_matches': True, 'timezone_text_matches': True}
        with patch('enge_spx.workspace_timezone.probe', side_effect=[before, after]), patch('enge_spx.workspace_timezone.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'', b'')) as execute:
            self.assertTrue(ready(prepare_project(engine, obj)))
        self.assertEqual(obj['Config']['User'], '1000:1000')
        self.assertFalse(obj['HostConfig']['ReadonlyRootfs'])
        self.assertNotIn('--user', execute.call_args.args[0])
        self.assertNotIn('--privileged', execute.call_args.args[0])
        engine.docker.command.assert_called_once_with('cp', '-', 'owned:/etc')

    def test_failed_copy_or_readonly_root_never_relaxes_permissions_or_exports_error(self):
        engine = self.engine()
        before = {'tzif_matches': False, 'timezone_text_matches': False, 'process_tz_matches': True, 'utc_tzif_sha256': 'public-utc'}
        obj = {'Id': 'owned', 'HostConfig': {'ReadonlyRootfs': True}}
        with patch('enge_spx.workspace_timezone.probe', return_value=before), patch('enge_spx.workspace_timezone.subprocess.run') as execute:
            with self.assertRaises(SPXError):
                prepare_project(engine, obj)
            execute.assert_not_called()
        obj['HostConfig']['ReadonlyRootfs'] = False
        with patch('enge_spx.workspace_timezone.probe', return_value=before), patch('enge_spx.workspace_timezone.subprocess.run', return_value=subprocess.CompletedProcess([], 1, b'', b'private-error')):
            with self.assertRaises(SPXError) as error:
                prepare_project(engine, obj)
            self.assertNotIn('private-error', str(error.exception))

    def test_matching_configuration_does_not_write_or_create_a_container(self):
        engine = self.engine()
        value = dict.fromkeys(('tzif_matches', 'timezone_text_matches', 'process_tz_matches'), True)
        with patch('enge_spx.workspace_timezone.probe', return_value=value), patch('enge_spx.workspace_timezone.subprocess.run') as execute:
            self.assertEqual(prepare_project(engine, {'Id': 'owned'}), value)
            execute.assert_not_called()
        engine.docker.command.assert_not_called()
