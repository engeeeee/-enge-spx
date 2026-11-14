"""Out-of-process, ordinary-user update application after verified GUI shutdown."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from . import __version__
from .app_updates import ROOTS, _plain, audit_tree
from .downloads import digest
from .state import SPXError, Store, atomic_json


def prune_backups(root, data, instance, current):
    try:
        protected = [data, *(Path(path) for path in Store(data).settings()['projects'])]
        for old in root.glob('._spx-rollback-*'):
            if old == current or old.is_symlink() or getattr(old, 'is_junction', lambda: False)() or any(path == old or old in path.parents for path in protected):
                continue
            marker = old / 'update-owner.json'
            _plain(marker)
            if not marker.is_file() or marker.stat().st_size > 1024 or json.loads(marker.read_text()).get('instance') != instance or set(item.name for item in old.iterdir()) - (ROOTS | {'update-owner.json'}):
                continue
            audit_tree(old)
            shutil.rmtree(old)
    except (OSError, ValueError, SPXError, TypeError, AttributeError):
        pass  # A locked old backup is retained; never force-delete it.


def load_plan(path, executable_dir):
    path = Path(path)
    _plain(path)
    if path.stat().st_size > 65536:
        raise SPXError('更新计划大小异常。')
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema') != 1 or value.get('version') != __version__ or type(value.get('parent_pid')) is not int or not 0 < value['parent_pid'] < 2**32:
        raise SPXError('更新计划版本或进程标识不符。')
    for key in ('root', 'data', 'payload', 'archive'):
        target = Path(value[key])
        if not target.is_absolute():
            raise SPXError('更新路径必须为绝对路径。')
        for parent in (target, *target.parents):
            _plain(parent)
    root, data, payload = (Path(value[key]) for key in ('root', 'data', 'payload'))
    if payload != Path(executable_dir) or payload != path.parent / 'payload' or root == root.parent or root == Path.home() or root == payload or root in payload.parents and payload.parts[len(root.parts)] in ROOTS:
        raise SPXError('更新源与当前运行的助手或程序目录不符。')
    if not all((root / name).is_file() for name in ('ENGE-SPX.exe', 'spx.exe')):
        raise SPXError('原程序目录不完整，未自动覆盖。')
    if not (data / 'instance.json').is_file():
        raise SPXError('原数据实例不存在，未开始更新。')
    store = Store(data)
    runtime = store.read('runtime.json', {})
    if store.instance != value.get('instance') or not isinstance(runtime, dict) or runtime.get('phase') != 'stopped':
        raise SPXError('工作区尚未停止或数据实例不同，未开始更新。')
    if digest(value['archive']) != value['archive_sha256']:
        raise SPXError('更新归档校验发生变化，未修改程序。')
    if value.get('installer'):
        installer = Path(value['installer'])
        _plain(installer)
        if installer.parent != Path(value['archive']).parent or digest(installer) != value.get('installer_sha256'):
            raise SPXError('安装包校验发生变化，未运行。')
    if set(p.name for p in payload.iterdir()) - ROOTS:
        raise SPXError('更新源含有非程序文件，未覆盖。')
    audit_tree(payload)
    for name in ROOTS:
        _plain(root / name)
        if (root / name).exists():
            audit_tree(root / name)
        if data == root / name or root / name in data.parents:
            raise SPXError('数据目录与待更新程序文件重叠，未覆盖。')
    return value


def replace_with_retry(source, target):
    deadline = time.monotonic() + 5
    while True:
        try:
            source.replace(target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.1)


def swap_portable(root, ready, backup, replace=replace_with_retry):
    """Only package-owned top-level entries; data and projects stay in place."""
    done = []
    try:
        for item in sorted(ready.iterdir(), key=lambda p: p.name):
            if item.name not in ROOTS:
                raise SPXError('待安装文件超出程序范围。')
            target = root / item.name
            _plain(target)
            existed = target.exists()
            done.append((item.name, existed))
            if existed:
                replace(target, backup / item.name)
            replace(item, target)
    except Exception as error:
        recovered = True
        for name, existed in reversed(done):
            target, old = root / name, backup / name
            try:
                if existed and not old.exists():
                    continue  # The original rename failed; it is still in place.
                if target.exists():
                    replace(target, ready / name)
                if existed:
                    replace(old, target)
            except OSError:
                recovered = False
        raise SPXError('更新失败，原程序已恢复。' if recovered else '更新失败，自动恢复未完成；原文件保存在程序目录的 ._spx-rollback 备份中，请保留并重新安装。') from error


class ParentHandle:
    def __init__(self, pid, root):
        if os.name != 'nt':
            raise SPXError('更新助手仅支持 Windows。')
        from ctypes import wintypes as w
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes, self.kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.WaitForSingleObject.argtypes, self.kernel.WaitForSingleObject.restype = [w.HANDLE, w.DWORD], w.DWORD
        self.kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        self.handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, pid)
        if not self.handle:
            raise SPXError('无法确认原软件进程，未修改程序。')
        path, length = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
        if not self.kernel.QueryFullProcessImageNameW(self.handle, 0, path, ctypes.byref(length)) or not any(Path(path.value).samefile(root / name) for name in ('ENGE-SPX.exe', 'spx.exe')):
            self.close()
            raise SPXError('更新请求并非来自当前程序进程，已拒绝。')

    def wait(self):
        if self.kernel.WaitForSingleObject(self.handle, 120000) != 0:
            raise SPXError('等待原软件退出超时，未强制结束进程或覆盖程序。')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def run(plan_path):
    plan = load_plan(plan_path, Path(sys.executable).parent)
    root, data = Path(plan['root']), Path(plan['data'])
    parent = ParentHandle(plan['parent_pid'], root)
    ready = root / ('._spx-next-' + uuid.uuid4().hex)
    backup = root / ('._spx-rollback-' + uuid.uuid4().hex)
    result = {'schema': 1, 'version': __version__, 'success': False}
    parent_exited = False
    try:
        # Complete all potentially failing copy/preflight work before READY.
        backup.mkdir(mode=0o700)
        atomic_json(backup / 'update-owner.json', {'schema': 1, 'instance': plan['instance']})
        if plan.get('installer'):
            for source in root.iterdir():
                if source.name in ROOTS:
                    target = backup / source.name
                    if source.is_dir():
                        shutil.copytree(source, target)
                    else:
                        shutil.copy2(source, target)
        else:
            shutil.copytree(plan['payload'], ready)
        print('SPX_UPDATE_READY', flush=True)
        parent.wait()
        parent.close()
        parent_exited = True
        # A frozen process changes Windows DLL search paths. External installers
        # and the new independent app must resolve their own runtime libraries.
        ctypes.windll.kernel32.SetDllDirectoryW(None)
        if plan.get('installer'):
            process = subprocess.run([plan['installer'], '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                                      '/NOCLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS', '/DIR=' + str(root)],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=subprocess.CREATE_NO_WINDOW, timeout=600)
            if process.returncode != 0:
                raise SPXError('安装器未完成更新，请保留备份并重新安装；未强制关闭其它程序。')
        else:
            swap_portable(root, ready, backup)
        installed = subprocess.run([str(root / 'spx.exe'), '--version'], capture_output=True, text=True,
                                   timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        if installed.returncode or installed.stdout.strip() != __version__:
            raise SPXError('安装后版本核验失败，请保留旧版备份并重新安装。')
        result.update(success=True, backup=str(backup), message='已更新到 ' + __version__ + '；工作区保持停止，由你重新启动。')
        prune_backups(root, data, plan['instance'], backup)
    except Exception as error:
        result['message'] = str(error) if isinstance(error, SPXError) else '更新未完成，旧版文件与用户数据保留。请检查程序目录权限，或从发布页重新安装。'
        if parent_exited and plan.get('installer'):
            try:
                ready.mkdir(exist_ok=True)
                for item in backup.iterdir():
                    if item.name in ROOTS:
                        if item.is_dir():
                            shutil.copytree(item, ready / item.name)
                        else:
                            shutil.copy2(item, ready / item.name)
                failed = root / ('._spx-failed-' + uuid.uuid4().hex)
                failed.mkdir(mode=0o700)
                swap_portable(root, ready, failed)
                result['message'] = '安装器未完成更新，旧程序文件已恢复；配置和项目保留，可重新检查更新。'
            except Exception:
                result['message'] = '自动更新与恢复未完成。旧程序备份已保留，请保留数据并从官方发布页重新安装。'
    finally:
        parent.close()
        shutil.rmtree(ready, ignore_errors=True)
        atomic_json(data / 'update-result.json', result)
        atomic_json(Path(plan_path).parent / 'finished.json', {'schema': 1, 'success': result['success']})
    if not parent_exited:
        return 1
    try:
        child = subprocess.Popen([str(root / 'ENGE-SPX.exe'), '--data', str(data)], cwd=str(root), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
                         env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'})
        result['restarted_pid'] = child.pid
        atomic_json(data / 'update-result.json', result)
    except OSError:
        ctypes.windll.user32.MessageBoxW(None, '更新未能重新打开软件。请保留用户数据并从原目录启动或重新安装 ENGE SPX。', 'ENGE SPX 更新', 0x10)
    return 0 if result['success'] else 1
