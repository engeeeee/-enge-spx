"""Two final-exit zones on the same real project layer and readonly image."""
import argparse
import json
from pathlib import Path
import tempfile

from enge_spx.engine import Engine
from enge_spx.exit_timezone import apply_verified_exit
from enge_spx.state import Store
from enge_spx.workspace_timezone import browser_image, prepare_project, probe, ready


def run(report, output):
    base_image = json.loads(report.read_text())['images']['work']
    containers, images, checks = [], [], []
    with tempfile.TemporaryDirectory(prefix='spx-auto-zone-') as folder:
        store = Store(Path(folder) / 'data')
        store.write('settings.json', {**store.settings(), 'context': 'default', 'timezone_mode': 'exit'})
        engine = Engine(store, print)
        try:
            project = engine.docker.run('run', '-d', '--network', 'none', '--user', '1000:1000',
                                        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                                        '--label', engine.owner + '=' + store.instance, '--label', engine.role + '=project',
                                        '--env', 'TZ=America/Los_Angeles', base_image, 'sleep', 'infinity')
            containers.append(project)
            before = engine.inspect('project', project)
            engine.docker.run('exec', project, 'python3', '-c', "from pathlib import Path;Path('/tmp/keep-project-layer').write_text('keep')")
            for zone in ('America/Los_Angeles', 'Asia/Tokyo'):
                selected = apply_verified_exit(engine, {'ip': '8.8.8.8', 'timezone': zone, 'line_timezone': 'Europe/London'})
                assert selected == zone
                assert ready(prepare_project(engine, before))
                assert ready(probe(engine, project, zone))
                assert engine.docker.run('exec', project, 'cat', '/tmp/keep-project-layer') == 'keep'
                after = engine.inspect('project', project)
                assert after['Id'] == before['Id'] and after['HostConfig'] == before['HostConfig']
                image = browser_image(engine, base_image)
                images.append(image)
                browser = engine.docker.run('run', '-d', '--network', 'none', '--user', '1000:1000', '--read-only',
                                           '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                                           '--label', engine.owner + '=' + store.instance, '--label', engine.role + '=browser',
                                           '--env', 'TZ=' + zone, image)
                containers.append(browser)
                assert ready(probe(engine, browser, zone))
                assert browser_image(engine, base_image) == image
                assert engine.inspect('browser', browser)['HostConfig']['ReadonlyRootfs'] is True
                checks.append({'selected_from_final_exit': zone, 'project_id_and_layer_kept': True,
                               'cli_process_and_system_files_consistent': True, 'readonly_browser_consistent': True})
            output.write_text(json.dumps({'schema': 1, 'checks': checks}, indent=2))
        finally:
            for identifier in containers:
                engine.docker.run('rm', '-f', identifier)
            for image in dict.fromkeys(images):
                engine.docker.run('image', 'rm', '-f', image)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.runtime_report, args.output)
