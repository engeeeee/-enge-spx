import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import httpx

from enge_spx.app_updates import API, check, extract_package, parse_release, preferences
from enge_spx.state import Store, SPXError
from enge_spx.update_apply import swap_portable


def official_release(version='1.2.3'):
    base = 'https://github.com/engeeeee/ENGE-SPX'
    assets = []
    for suffix in ('Setup.exe', 'Portable.zip'):
        name = f'ENGE-SPX-Windows-x64-{version}-{suffix}'
        for filename in (name, name + '.sha256'):
            assets.append({'name': filename, 'state': 'uploaded', 'size': 100, 'digest': 'sha256:' + 'a' * 64,
                           'browser_download_url': f'{base}/releases/download/v{version}-windows/{filename}'})
    return {'tag_name': f'v{version}-windows', 'html_url': f'{base}/releases/tag/v{version}-windows',
            'draft': False, 'prerelease': False, 'assets': assets}


class AppUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_exact_official_stable_asset_and_version_rules(self):
        raw = official_release()
        self.assertEqual(parse_release(raw, '1.2.2')['version'], '1.2.3')
        self.assertIsNone(parse_release(raw, '1.2.3'))
        self.assertIsNone(parse_release(raw, '1.3.0'))
        for change in ('draft', 'prerelease', 'source', 'digest', 'duplicate', 'size'):
            broken = copy.deepcopy(raw)
            if change in ('draft', 'prerelease'):
                broken[change] = True
            elif change == 'source':
                broken['assets'][0]['browser_download_url'] = 'https://evil.invalid/setup.exe'
            elif change == 'digest':
                broken['assets'][0]['digest'] = None
            elif change == 'size':
                broken['assets'][0]['size'] = 2**40
            else:
                broken['assets'].append(broken['assets'][0])
            with self.subTest(change=change), self.assertRaises(SPXError):
                parse_release(broken, '1.2.2')

    def test_daily_check_uses_cache_and_proxy_failure_has_no_direct_retry(self):
        store = Store(self.root / 'data')
        store.write('settings.json', {**store.settings(), 'relay': {'enabled': False, 'downloads': False}})
        requests = []
        def transport(request):
            requests.append(request)
            self.assertEqual(str(request.url), API)
            self.assertNotIn('authorization', request.headers)
            return httpx.Response(200, json=official_release())
        mock = httpx.MockTransport(transport)
        self.assertEqual(check(store, transport=mock)['version'], '1.2.3')
        check(store, transport=mock)
        self.assertEqual(len(requests), 1)
        check(store, force=True, transport=mock)
        self.assertEqual(len(requests), 2)
        with patch('enge_spx.app_updates.download_proxy', side_effect=SPXError('proxy unavailable')):
            with self.assertRaises(SPXError):
                check(store, force=True, transport=mock)
        self.assertEqual(len(requests), 2)
        self.assertTrue(preferences(store)['auto_check'])

    def test_oversized_or_invalid_metadata_is_rejected(self):
        store = Store(self.root / 'data')
        store.write('settings.json', {**store.settings(), 'relay': {'enabled': False, 'downloads': False}})
        for body in (b'x' * 300000, b'{invalid'):
            with self.subTest(length=len(body)), self.assertRaises(SPXError):
                check(store, force=True, transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)))

    def archive(self, extra=()):
        target = self.root / 'release.zip'
        with zipfile.ZipFile(target, 'w') as package:
            for name, value in [('ENGE-SPX.exe', b'MZ-GUI'), ('spx.exe', b'MZ-CLI'), ('_internal/client.bin', b'new'), *extra]:
                package.writestr(name, value)
        return target

    def test_extract_rejects_traversal_streams_devices_links_and_user_data_roots(self):
        for name in ('../escape', '_internal/../../escape', 'C:/escape', '_internal/x:stream', '_internal/NUL.txt', '_internal/trailing.', 'data/settings.json', '_internal\\escape'):
            with self.subTest(name=name), self.assertRaises(SPXError):
                extract_package(self.archive([(name, b'unsafe')]), self.root / 'payload')
            self.assertFalse((self.root / 'payload').exists())
        link = zipfile.ZipInfo('_internal/link')
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        with self.assertRaises(SPXError):
            extract_package(self.archive([(link, b'../../escape')]), self.root / 'payload')

    def test_portable_transaction_keeps_data_extra_files_and_backup(self):
        root, ready, backup = (self.root / name for name in ('app', 'ready', 'backup'))
        root.mkdir(); backup.mkdir()
        (root / 'spx.exe').write_bytes(b'old')
        (root / 'data').mkdir(); (root / 'data/credentials.json').write_bytes(b'unchanged')
        (root / 'my-project.txt').write_text('keep')
        extract_package(self.archive(), ready)
        swap_portable(root, ready, backup)
        self.assertEqual((root / 'spx.exe').read_bytes(), b'MZ-CLI')
        self.assertEqual((backup / 'spx.exe').read_bytes(), b'old')
        self.assertEqual((root / 'data/credentials.json').read_bytes(), b'unchanged')
        self.assertEqual((root / 'my-project.txt').read_text(), 'keep')

    def test_permission_error_restores_already_replaced_files(self):
        root, ready, backup = (self.root / name for name in ('app', 'ready', 'backup'))
        root.mkdir(); backup.mkdir()
        for name in ('ENGE-SPX.exe', 'spx.exe'):
            (root / name).write_bytes(b'old-' + name.encode())
        extract_package(self.archive(), ready)
        def replace(source, target):
            if source == ready / 'spx.exe':
                raise PermissionError('simulated file in use')
            source.replace(target)
        with self.assertRaises(SPXError):
            swap_portable(root, ready, backup, replace)
        for name in ('ENGE-SPX.exe', 'spx.exe'):
            self.assertEqual((root / name).read_bytes(), b'old-' + name.encode())
        self.assertFalse((root / '_internal').exists())
