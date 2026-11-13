"""Actual npm update permissions and binary resolution in a protected workspace.

Use image-pinned package versions, not a moving latest tag. This tests replacing
the root-owned image fallback with user installations, without real AI accounts.
"""
from pathlib import Path
import re
import subprocess


def verify_updates(engine, project, worker):
    def call(arguments, timeout=40):
        command = engine.tool_command(str(project), arguments, interactive=False, browser=False)
        assert engine.prepared_container == worker["Id"], "Tool update must reuse the existing project container"
        result = subprocess.run(command, env=engine.docker.environment(), capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout)
        assert result.returncode == 0, engine.docker.redact(result.stderr[-2500:])
        return result.stdout.strip()

    recipe = Path(__file__).resolve().parents[1] / "src/enge_spx/resources/containers/Dockerfile.work"
    versions = dict(re.findall(r"ARG (CODEX|CLAUDE)_VERSION=([0-9.]+)", recipe.read_text()))
    assert set(versions) == {"CODEX", "CLAUDE"}
    inspection = "import os,json; from pathlib import Path; p=Path(os.environ['NPM_CONFIG_PREFIX']); assert os.getuid()==1000; assert p==Path('/home/workspace/.local'); assert not os.access('/usr/local/lib/node_modules',os.W_OK); print('ROOTLESS_PREFIX')"
    assert call(["python3", "-c", inspection]) == "ROOTLESS_PREFIX"
    call(["npm", "install", "-g", "--no-audit", "--no-fund", "--fetch-retries=0", "--fetch-timeout=30000",
          "--allow-scripts=@anthropic-ai/claude-code", "@openai/codex@" + versions["CODEX"],
          "@anthropic-ai/claude-code@" + versions["CLAUDE"]], timeout=240)
    expected = {"codex": versions["CODEX"], "claude": versions["CLAUDE"]}
    for tool, version in expected.items():
        assert version in call([tool, "--version"])
    code = "import os,shutil; from pathlib import Path\nfor tool in ('codex','claude'):\n p=Path(shutil.which(tool)); assert str(p).startswith('/home/workspace/.local/bin/'); assert p.resolve().is_relative_to('/home/workspace/.local'); assert p.resolve().stat().st_uid==1000\nprint('USER_BINARIES')"
    assert call(["python3", "-c", code]) == "USER_BINARIES"
    return {"packages": expected, "uid": 1000, "prefix": "/home/workspace/.local",
            "system_install_writable": False, "network": "existing controlled gateway",
            "real_accounts_used": False, "test": "npm install and subsequent real executable resolution"}


def verify_persisted_updates(engine, project, expected):
    for tool, version in expected["packages"].items():
        command = engine.tool_command(str(project), [tool, "--version"], interactive=False, browser=False)
        result = subprocess.run(command, env=engine.docker.environment(), capture_output=True,
                                text=True, timeout=40)
        assert result.returncode == 0 and version in result.stdout
