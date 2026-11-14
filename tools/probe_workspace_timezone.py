"""Disposable real Docker timezone check; no accounts or public proxy needed."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from enge_spx.engine import Engine
from enge_spx.state import Store
from enge_spx.workspace_timezone import prepare_project, browser_image, probe, ready


with tempfile.TemporaryDirectory(prefix='spx-timezone-probe-') as folder:
    root = Path(folder)
    dockerfile = root / 'Dockerfile'
    dockerfile.write_text('FROM python:3.12-slim-bookworm\nRUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*\nRUN useradd -m -u 1000 workspace\nUSER 1000:1000\nENTRYPOINT ["/usr/bin/env"]\nCMD ["sleep","infinity"]\n')
    store = Store(root / 'data')
    store.write('settings.json', {**store.settings(), 'context': 'default'})
    engine = Engine(store, print)
    base = 'spx-timezone-test:' + uuid.uuid4().hex[:12]
    engine.docker.run('build', '-t', base, str(root), timeout=180)
    images, containers = [], []
    try:
        base_id = engine.docker.inspect('image', base)['Id']
        for role, image, readonly in (('project', base_id, False), ('browser', None, True)):
            if role == 'browser':
                image = browser_image(engine, base_id)
                images.append(image)
                assert browser_image(engine, base_id) == image
            identifier = engine.docker.run('run', '-d', '--network', 'none', '--user', '1000:1000',
                                          '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                                          '--label', engine.owner + '=' + engine.store.instance,
                                          '--label', engine.role + '=' + role, '--env', 'TZ=America/Los_Angeles',
                                          *(['--read-only'] if readonly else []), image)
            containers.append(identifier)
            before = engine.inspect(role, identifier)
            if role == 'project':
                engine.docker.run('exec', identifier, 'python3', '-I', '-c', "from pathlib import Path;Path('/tmp/keep-layer').write_text('preserved')")
                assert not ready(probe(engine, identifier, 'America/Los_Angeles'))
                result = prepare_project(engine, before)
                assert ready(result)
                assert engine.docker.run('exec', identifier, 'cat', '/tmp/keep-layer') == 'preserved'
                assert prepare_project(engine, before) == result
            else:
                assert ready(probe(engine, identifier, 'America/Los_Angeles'))
            assert engine.docker.run('exec', identifier, 'readlink', '-f', '/etc/localtime') == '/usr/share/zoneinfo/America/Los_Angeles'
            assert engine.docker.run('exec', identifier, 'cat', '/etc/timezone') == 'America/Los_Angeles'
            after = engine.inspect(role, identifier)
            assert after['Id'] == before['Id'] and after['Config']['User'] == '1000:1000'
            assert after['HostConfig'] == before['HostConfig']
        result = {'schema': 1, 'project_layer_preserved': True, 'container_id_preserved': True,
                  'project_and_readonly_browser_consistent': True, 'runtime_uid': 1000,
                  'new_ports_or_mounts': False, 'utc_database_unchanged': True}
        print(json.dumps(result))
        output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
        if output:
            output.write_text(json.dumps(result, indent=2))
    finally:
        for identifier in containers:
            engine.docker.run('rm', '-f', identifier)
        for image in images:
            engine.docker.run('image', 'rm', '-f', image)
        engine.docker.run('image', 'rm', '-f', base)
