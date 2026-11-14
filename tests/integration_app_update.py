"""Actual frozen Windows helper, portable swap, Inno install and restart.

Only disposable copies and owned fixture PIDs are stopped. No Docker, accounts,
network or global keyboard/mouse injection is used by this acceptance script.
"""
import argparse
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time

from enge_spx import __version__
from enge_spx.app_updates import extract_package
from enge_spx.downloads import digest
from enge_spx.state import Store, atomic_json


def stop_owned(pid, root):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    handle = kernel.OpenProcess(0x1000 | 0x100000 | 1, False, pid)
    if not handle:
        return
    try:
        path, size = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
        assert kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size))
        assert Path(path.value).samefile(root / 'ENGE-SPX.exe'), 'Refuse to stop any other program'
        kernel.TerminateProcess(handle, 0)
        assert kernel.WaitForSingleObject(handle, 5000) == 0
    finally:
        kernel.CloseHandle(handle)


def exercise(bundle, setup, installed):
    with tempfile.TemporaryDirectory(prefix='spx update 空格-') as folder:
        base = Path(folder)
        root, stage = base / 'app', base / 'stage'
        stage.mkdir()
        if installed:
            subprocess.run([str(setup), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/DIR=' + str(root)],
                           check=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
            assert (root / 'unins000.exe').is_file()
        else:
            extract_package(bundle, root)
        (root / 'my-project.txt').write_text('preserve this extra user file', encoding='utf-8')
        store = Store(root / 'data')
        store.write('runtime.json', {'phase': 'stopped'})
        (store.home / 'account-fixture.txt').write_bytes(b'synthetic-account-marker')
        old_id = store.instance
        payload = stage / 'payload'
        extract_package(bundle, payload)
        environment = {**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'}
        parent = subprocess.Popen([str(root / 'ENGE-SPX.exe'), '--data', str(store.home)], env=environment,
                                  cwd=str(root), creationflags=subprocess.CREATE_NO_WINDOW)
        helper = None
        result = {}
        try:
            time.sleep(1.0)
            assert parent.poll() is None, 'Disposable original GUI did not stay open'
            plan = {'schema': 1, 'version': __version__, 'from_version': __version__, 'root': str(root),
                    'data': str(store.home), 'instance': old_id, 'parent_pid': parent.pid,
                    'payload': str(payload), 'archive': str(bundle), 'archive_sha256': digest(bundle),
                    'installer': str(setup) if installed else None, 'installer_sha256': digest(setup) if installed else None}
            atomic_json(stage / 'plan.json', plan)
            helper = subprocess.Popen([str(payload / 'spx.exe'), '--apply-update', str(stage / 'plan.json')], env=environment,
                                      cwd=str(payload), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
            messages = queue.Queue()
            threading.Thread(target=lambda: messages.put(helper.stdout.readline(256)), daemon=True).start()
            ready = messages.get(timeout=40)
            if ready.strip() != b'SPX_UPDATE_READY':
                if helper.poll() is None:
                    helper.terminate(); helper.wait(timeout=5)
                raise AssertionError('Helper preflight failed: ' + helper.stderr.read(2000).decode(errors='replace'))
            # Simulate the old process leaving after the product's separately
            # tested verified-shutdown handoff. Never stop a production process.
            stop_owned(parent.pid, root)
            parent.wait(timeout=5)
            helper.wait(timeout=120)
            result = json.loads((store.home / 'update-result.json').read_text(encoding='utf-8'))
            assert helper.returncode == 0 and result['success'], result
            version = subprocess.run([str(root / 'spx.exe'), '--version'], env=environment, capture_output=True,
                                     text=True, check=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
            assert version == __version__
            assert Store(store.home).instance == old_id
            assert (store.home / 'account-fixture.txt').read_bytes() == b'synthetic-account-marker'
            assert (root / 'my-project.txt').read_text(encoding='utf-8') == 'preserve this extra user file'
            time.sleep(1.5)
            assert result['restarted_pid'] > 0
            return {'kind': 'installed' if installed else 'portable', 'helper_ready': True, 'version_verified': True,
                    'same_data_instance': True, 'private_data_and_extra_file_preserved': True, 'restart_requested': True}
        finally:
            if parent.poll() is None:
                stop_owned(parent.pid, root)
                parent.wait(timeout=5)
            if helper is not None:
                if helper.poll() is None:
                    helper.terminate(); helper.wait(timeout=5)
                helper.stdout.close(); helper.stderr.close()
            if result.get('restarted_pid'):
                stop_owned(result['restarted_pid'], root)
            if installed and (root / 'unins000.exe').exists():
                subprocess.run([str(root / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'],
                               timeout=60, creationflags=subprocess.CREATE_NO_WINDOW, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--setup', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('requires a disposable Windows desktop')
    report = {'schema': 1, 'version': __version__, 'cases': [exercise(args.bundle.resolve(), args.setup.resolve(), installed) for installed in (False, True)]}
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
