"""System timezone provisioning without replacing project writable layers."""
import io
import json
import subprocess
import tarfile
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .brand import PACKAGE_RESOURCES
from .state import SPXError, fingerprint

LABEL = 'io.enge.spx.timezone'
BASE = 'io.enge.spx.timezone-base'
FORMAT = 'io.enge.spx.timezone-format'


def zone_name(engine):
    name = engine.store.settings()['timezone']
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
        raise SPXError('工作区时区不是有效 IANA 名称，未修改环境。') from error
    if ',' in name or '\n' in name or '..' in name or name.startswith('/'):
        raise SPXError('工作区时区名称无效。')
    return name


def probe(engine, container, zone):
    script = (PACKAGE_RESOURCES / 'checks/timezone_probe.py').read_text(encoding='utf-8')
    try:
        value = json.loads(engine.docker.run('exec', '--env', 'TZ=' + zone, container, 'python3', '-I', '-c', script, zone, timeout=12))
        if value.get('schema') != 1 or value.get('zone') != zone or type(value.get('tzif_matches')) is not bool:
            raise ValueError()
        return value
    except (ValueError, SPXError) as error:
        raise SPXError('无法核验工作容器的系统时区，未启动 CLI；请保留数据并重新准备环境。') from error


def archive(zone):
    # Fixed archive members only. Replacing the symlink itself preserves the
    # original UTC TZif; never write Los Angeles data into Etc/UTC.
    ZoneInfo(zone)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as package:
        localtime = tarfile.TarInfo('localtime')
        localtime.type, localtime.linkname = tarfile.SYMTYPE, '/usr/share/zoneinfo/' + zone
        localtime.uid = localtime.gid = 0
        package.addfile(localtime)
        body = (zone + '\n').encode('ascii')
        item = tarfile.TarInfo('timezone')
        item.size, item.mode, item.uid, item.gid = len(body), 0o644, 0, 0
        package.addfile(item, io.BytesIO(body))
    return buffer.getvalue()


def ready(value):
    return all(value.get(key) is True for key in ('tzif_matches', 'timezone_text_matches', 'process_tz_matches'))


def prepare_project(engine, obj):
    engine.owned(obj, 'project')
    zone = zone_name(engine)
    before = probe(engine, obj['Id'], zone)
    if ready(before):
        return before
    if (obj.get('HostConfig') or {}).get('ReadonlyRootfs') is True:
        raise SPXError('项目根文件系统为只读，无法更新系统时区；未放宽目录权限。')
    # Docker's archive endpoint deploys two public configuration entries. No
    # root exec, image commit of user data, host mount or new capability.
    try:
        result = subprocess.run(engine.docker.command('cp', '-', obj['Id'] + ':/etc'), input=archive(zone),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                                env=engine.docker.environment(), creationflags=subprocess.CREATE_NO_WINDOW if __import__('os').name == 'nt' else 0)
        if result.returncode:
            raise SPXError('工作区系统时区部署失败，原项目和账号数据未删除。')
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SPXError('工作区系统时区部署未完成，请重试；不会使用不一致的环境启动新 CLI。') from error
    after = probe(engine, obj['Id'], zone)
    if not ready(after) or before['utc_tzif_sha256'] != after['utc_tzif_sha256']:
        raise SPXError('工作区系统时区核验未通过，未启动 CLI；请保留数据并重试。')
    engine.log('项目 TZ、系统时区文件已统一；容器、项目及账号数据保持。')
    return after


PREPARE = '''import os,sys
from pathlib import Path
from zoneinfo import ZoneInfo
name=sys.argv[1];ZoneInfo(name)
root=Path('/usr/share/zoneinfo').resolve();target=(root/name).resolve(strict=True)
assert target.is_relative_to(root) and not Path('/etc').is_symlink()
with target.open('rb') as stream:data=stream.read(131073)
assert data.startswith(b'TZif') and len(data)<=131072
for path in ('/etc/localtime.spx-next','/etc/timezone.spx-next'):
 try:os.unlink(path)
 except FileNotFoundError:pass
os.symlink('/usr/share/zoneinfo/'+name,'/etc/localtime.spx-next')
Path('/etc/timezone.spx-next').write_text(name+'\\n',encoding='ascii')
os.chmod('/etc/timezone.spx-next',0o644)
os.replace('/etc/localtime.spx-next','/etc/localtime')
os.replace('/etc/timezone.spx-next','/etc/timezone')
'''


def browser_image(engine, base):
    zone = zone_name(engine)
    key = fingerprint({'base': base, 'zone': zone, 'prepare': PREPARE})[:24]
    tag = 'enge-spx/timezone-' + engine.store.instance + ':' + key
    image = engine.docker.inspect('image', base)
    config = image.get('Config') or {}
    if config.get('Volumes') or not config.get('Entrypoint') or str(config.get('User', '')).split(':')[0] != '1000':
        raise SPXError('浏览器基础镜像不符合离线时区准备条件。')
    def valid_configuration(candidate):
        actual = candidate.get('Config') or {}
        return all(actual.get(key) == config.get(key) for key in ('User', 'Entrypoint', 'Cmd'))
    existing = engine.docker.inspect('image', tag)
    if existing:
        labels = (existing.get('Config') or {}).get('Labels') or {}
        if labels.get(LABEL) != zone or labels.get(BASE) != base or labels.get(FORMAT) != key or labels.get(engine.owner) != engine.store.instance or not valid_configuration(existing):
            raise SPXError('浏览器时区镜像记录不符，已拒绝使用。')
        return existing['Id']
    name = engine.prefix + '-timezone-build-' + uuid.uuid4().hex[:8]
    identifier = None
    engine.log('正在离线准备浏览器系统时区；不下载文件、不挂载项目或账号。')
    try:
        identifier = engine.docker.run('create', '--name', name, '--label', engine.owner + '=' + engine.store.instance,
                                       '--label', engine.role + '=timezone-builder', '--label', LABEL + '=' + zone,
                                       '--label', BASE + '=' + base, '--label', FORMAT + '=' + key,
                                       '--network', 'none', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                                       '--pids-limit', '32', '--memory', '128m', '--cpus', '1', '--user', '0:0',
                                       '--entrypoint', 'python3', base, '-I', '-c', PREPARE, zone)
        engine.docker.run('start', '--attach', identifier, timeout=30)
        state = engine.owned(engine.docker.inspect('container', identifier), 'timezone-builder')
        if state['State'].get('ExitCode') != 0:
            raise SPXError('浏览器离线时区准备失败，未更改正在使用的镜像。')
        engine.docker.run('commit', '--change', 'USER ' + config['User'],
                          '--change', 'ENTRYPOINT ' + json.dumps(config.get('Entrypoint') or []),
                          '--change', 'CMD ' + json.dumps(config.get('Cmd') or []),
                          '--change', 'ENV TZ=' + zone, identifier, tag, timeout=30)
        created = engine.docker.inspect('image', tag)
        if not created or not valid_configuration(created):
            raise SPXError('浏览器时区镜像未能保持原用户和启动命令，已拒绝启动。')
        return created['Id']
    finally:
        if identifier:
            owned = engine.docker.inspect('container', identifier)
            if owned:
                engine.owned(owned, 'timezone-builder')
                engine.docker.run('rm', '-f', identifier)
