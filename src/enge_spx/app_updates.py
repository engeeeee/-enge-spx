"""Official, bounded client updates; networking never needs Docker or API tokens."""
import json
import os
from pathlib import Path, PurePosixPath
import queue
import re
import shutil
import stat
import subprocess
import sys
import threading
import tempfile
import time
import uuid
import zipfile

import httpx

from . import __version__
from .brand import PROJECT_URL
from .downloads import DownloadPaused, client, digest, download, network_error
from .proxy import download_proxy
from .state import SPXError, atomic_json

API = 'https://api.github.com/repos/engeeeee/ENGE-SPX/releases/latest'
PREFERENCES = 'update-preferences.json'
MAX_PACKAGE = 512 * 1024**2
ROOTS = {'ENGE-SPX.exe', 'spx.exe', '_internal', 'docs', 'assets', 'licenses', 'THIRD-PARTY-LICENSES',
         'README.md', 'README.zh-CN.md', 'README.en.md', 'LICENSE', 'NOTICE.md', 'THIRD_PARTY_NOTICES.md',
         'AUTHORS.md', 'CONTRIBUTING.md', 'SECURITY.md', 'SUPPORT.md', 'CHANGELOG.md'}


def audit_tree(root):
    pending = [root]
    while pending:
        path = pending.pop()
        _plain(path)
        if path.is_dir():
            pending.extend(path.iterdir())
        elif not path.is_file():
            raise SPXError('更新目录包含非普通文件，已拒绝使用。')


def version(value):
    if not isinstance(value, str) or re.fullmatch(r'(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})', value) is None:
        raise SPXError('更新版本格式无效，未下载或运行文件。')
    return tuple(map(int, value.split('.')))


def preferences(store):
    value = store.read(PREFERENCES, {'schema': 1, 'auto_check': True})
    if not isinstance(value, dict) or value.get('schema') != 1 or type(value.get('auto_check')) is not bool:
        raise SPXError('更新偏好格式无效，请重新保存；未启用自动安装。')
    return value


def parse_release(raw, current=__version__):
    if not isinstance(raw, dict) or raw.get('draft') is not False or raw.get('prerelease') is not False:
        raise SPXError('更新信息不是正式版本，未使用。')
    tag = raw.get('tag_name', '')
    match = re.fullmatch(r'v(\d+\.\d+\.\d+)-windows', tag) if isinstance(tag, str) else None
    if not match:
        raise SPXError('更新标签无效，未使用。')
    candidate = match[1]
    if version(candidate) <= version(current):
        return None
    if raw.get('html_url') != PROJECT_URL + '/releases/tag/' + tag:
        raise SPXError('更新来源与官方仓库不一致，未使用。')
    assets = raw.get('assets')
    if not isinstance(assets, list) or len(assets) > 40:
        raise SPXError('更新文件清单无效。')
    result = {'version': candidate, 'url': raw['html_url'], 'assets': {}}
    for suffix in ('Portable.zip', 'Setup.exe'):
        name = 'ENGE-SPX-Windows-x64-' + candidate + '-' + suffix
        for filename in (name, name + '.sha256'):
            rows = [item for item in assets if isinstance(item, dict) and item.get('name') == filename]
            if len(rows) != 1:
                raise SPXError('正式版缺少唯一的程序包或校验文件，请稍后检查。')
            item = rows[0]
            expected = PROJECT_URL + '/releases/download/' + tag + '/' + filename
            size, checksum = item.get('size'), item.get('digest', '')
            if item.get('browser_download_url') != expected or item.get('state') != 'uploaded' or type(size) is not int or not 0 < size <= (512 if filename.endswith('.sha256') else MAX_PACKAGE):
                raise SPXError('更新地址或文件大小无效，未下载。')
            if not isinstance(checksum, str) or re.fullmatch(r'sha256:[a-f0-9]{64}', checksum) is None:
                raise SPXError('更新文件缺少 GitHub SHA-256，未下载。')
            result['assets'][filename] = {'url': expected, 'size': size, 'sha256': checksum[7:]}
    return result


def _read(session, url, maximum):
    with session.stream('GET', url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'ENGE-SPX/' + __version__}) as response:
        response.raise_for_status()
        result = bytearray()
        for block in response.iter_bytes(16384):
            result.extend(block)
            if len(result) > maximum:
                raise SPXError('更新服务返回内容过大，未使用。')
        return bytes(result)


def check(store, force=False, transport=None, current=__version__):
    try:
        cached = store.read('update-check.json', {}) if not force and (not (store.home / 'update-check.json').exists() or (store.home / 'update-check.json').stat().st_size <= 512 * 1024) else {}
    except (OSError, SPXError):
        cached = {}
    if not force and isinstance(cached, dict) and type(cached.get('checked')) in (int, float) and 0 <= time.time() - cached['checked'] < 86400:
        return parse_release(cached.get('release'), current)
    via, _ = download_proxy(store.settings()['relay'])
    try:
        with client(via, transport) as session:
            session.timeout = httpx.Timeout(8)
            raw = json.loads(_read(session, API, 256 * 1024))
        release = parse_release(raw, current)
        store.write('update-check.json', {'schema': 1, 'checked': time.time(), 'release': raw})
        return release
    except (httpx.RequestError, httpx.HTTPStatusError) as error:
        raise network_error(error, '检查软件更新') from error
    except (ValueError, TypeError) as error:
        raise SPXError('更新服务返回的清单格式无效。') from error


def _plain(path):
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        raise SPXError('更新路径包含符号链接或目录联接，已停止更新。')


def extract_package(archive, target):
    """Private empty destination; reject traversal, NTFS streams and ZIP bombs."""
    if target.exists():
        raise SPXError('更新暂存目录已存在，未覆盖。')
    with zipfile.ZipFile(archive) as bundle:
        items, names, total = bundle.infolist(), set(), 0
        if not 1 <= len(items) <= 12000:
            raise SPXError('更新包文件数量异常。')
        for item in items:
            path = PurePosixPath(item.filename)
            parts = path.parts
            if not parts or path.is_absolute() or '\\' in item.filename or any(part in ('.', '..') or ':' in part or part.endswith((' ', '.')) or any(ord(c) < 32 for c in part) or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part) for part in parts) or parts[0] not in ROOTS:
                raise SPXError('更新包包含不安全的路径。')
            kind = (item.external_attr >> 16) & 0o170000
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or item.flag_bits & 1 or item.file_size > MAX_PACKAGE:
                raise SPXError('更新包包含链接、加密或异常文件。')
            name = '/'.join(parts).casefold()
            if name in names:
                raise SPXError('更新包路径重复。')
            names.add(name)
            total += item.file_size
            if total > 1024**3:
                raise SPXError('更新包解压体积超过限制。')
        if not {'enge-spx.exe', 'spx.exe'} <= names or not any(name.startswith('_internal/') for name in names):
            raise SPXError('更新包不完整，未修改当前软件。')
        target.mkdir(mode=0o700)
        try:
            for item in items:
                path = target.joinpath(*PurePosixPath(item.filename).parts)
                if item.is_dir():
                    path.mkdir(mode=0o700, parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with bundle.open(item) as source, path.open('xb') as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise


def application_directory():
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        raise SPXError('源码运行模式请通过 Git 更新；软件内安装更新支持 Windows 安装版和便携版。')
    root = Path(sys.executable).parent
    for parent in (root, *root.parents):
        _plain(parent)
    if root == root.parent or root == Path.home() or not all((root / name).is_file() for name in ('ENGE-SPX.exe', 'spx.exe')):
        raise SPXError('无法确认当前程序目录，请使用完整 Windows 安装版或便携版。')
    return root


def prepare(store, release, progress, cancel, root=None):
    root = Path(root) if root is not None else application_directory()
    try:
        fd, probe = tempfile.mkstemp(prefix='._spx-write-', dir=root)
        os.close(fd)
        Path(probe).unlink()
    except OSError as error:
        raise SPXError('当前程序目录不可写；未停止工作区或修改程序，请使用可写的当前用户目录。') from error
    # Re-validate cached UI metadata before using addresses or names.
    candidate = release['version']
    version(candidate)
    raw = {'tag_name': 'v' + candidate + '-windows', 'html_url': release['url'], 'draft': False, 'prerelease': False,
           'assets': [{'name': name, 'browser_download_url': item['url'], 'state': 'uploaded', 'size': item['size'],
                       'digest': 'sha256:' + item['sha256']} for name, item in release['assets'].items()]}
    release = parse_release(raw, '0.0.0')
    via, _ = download_proxy(store.settings()['relay'])
    cache = store.home / 'updates'
    for path in (cache, *cache.parents):
        _plain(path)
    cache.mkdir(mode=0o700, exist_ok=True)
    from .storage import _private_directory
    _private_directory(cache)
    # Only remove completed scratch work from this private update cache.
    for old in cache.glob('stage-*'):
        if not old.is_symlink() and not getattr(old, 'is_junction', lambda: False)() and (old / 'finished.json').is_file() and time.time() - old.stat().st_mtime > 300:
            shutil.rmtree(old, ignore_errors=True)
    for old in cache.glob('ENGE-SPX-Windows-x64-*'):
        if old.is_file() and candidate not in old.name and time.time() - old.stat().st_mtime > 86400:
            old.unlink(missing_ok=True)
    installed = (root / 'unins000.exe').is_file()
    selected = ['Portable.zip', *(['Setup.exe'] if installed else [])]
    files = {}
    for index, suffix in enumerate(selected):
        name = 'ENGE-SPX-Windows-x64-' + candidate + '-' + suffix
        asset = release['assets'][name]
        checksum = release['assets'][name + '.sha256']
        try:
            with client(via) as session:
                text = _read(session, checksum['url'], 512).decode('ascii').strip()
            if text != asset['sha256'] + '  ' + name:
                raise SPXError('发布清单与 SHA-256 文件不一致，未使用更新包。')
        except (httpx.RequestError, httpx.HTTPStatusError) as error:
            raise network_error(error, '获取更新校验信息') from error
        except UnicodeError as error:
            raise SPXError('更新校验文件格式异常。') from error
        def report(value):
            progress({'progress': (index + (value.get('bytes', 0) / max(1, value.get('total', 1)))) * 80 / len(selected),
                      'message': '正在下载并校验 ' + suffix + '…'})
        files[suffix] = download(asset['url'], cache / name, asset['sha256'], asset['size'], report, cancel, via)
    if cancel.is_set():
        raise DownloadPaused('软件更新已取消，已下载内容保留。')
    stage = cache / ('stage-' + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    payload = stage / 'payload'
    progress({'progress': 85, 'message': '正在准备更新，原程序及用户数据保持。'})
    try:
        extract_package(files['Portable.zip'], payload)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    if cancel.is_set():
        shutil.rmtree(stage, ignore_errors=True)
        raise DownloadPaused('软件更新已取消，已下载的安装包保留。')
    for name in ROOTS:
        destination = root / name
        for private in (store.home, *(Path(path) for path in store.settings()['projects'])):
            if private == destination or destination in private.parents:
                raise SPXError('用户数据或项目位于程序文件目录内，已停止自动覆盖；请先迁移数据。')
    plan = {'schema': 1, 'version': candidate, 'from_version': __version__, 'root': str(root), 'data': str(store.home), 'instance': store.instance,
            'payload': str(payload), 'archive': str(files['Portable.zip']), 'archive_sha256': release['assets'][files['Portable.zip'].name]['sha256'],
            'installer': str(files['Setup.exe']) if installed else None,
            'installer_sha256': release['assets'][files['Setup.exe'].name]['sha256'] if installed else None,
            'parent_pid': os.getpid()}
    atomic_json(stage / 'plan.json', plan)
    return stage / 'plan.json'


def launch_helper(plan_path):
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    helper = Path(plan['payload']) / 'spx.exe'
    child = subprocess.Popen([str(helper), '--apply-update', str(plan_path)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=str(helper.parent),
                             env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'},
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    messages = queue.Queue()
    def read():
        messages.put(child.stdout.readline(256))
    threading.Thread(target=read, daemon=True).start()
    try:
        if messages.get(timeout=30).strip() != b'SPX_UPDATE_READY':
            raise SPXError('更新助手没有通过预检查；软件保留，可重试。')
    except Exception:
        if child.poll() is None:
            child.terminate()
        raise SPXError('无法准备更新助手。工作区已停止，当前程序保留；可重试更新。') from None
    finally:
        child.stdout.close()
