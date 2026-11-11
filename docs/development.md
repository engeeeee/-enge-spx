# Developing ENGE SPX

The repository separates application code, runtime resources and packaging:

```text
src/enge_spx/                 Host control plane and UI
src/enge_spx/resources/       Container recipes and application icons
packaging/windows/           PyInstaller, Inno Setup and executable metadata
assets/logo.svg              Original ENGE SPX vector source
tests/                       Unit, migration and explicit Docker integration tests
tools/                       GUI smoke test, artwork, runtime export and release
```

`ui/controller.py` owns desktop state, bounded worker delivery and UI actions;
`ui/window.py` constructs native Qt pages on first use. `ui/style.py` and
`ui/widgets.py` share the warm-charcoal/clay palette, controls and dialogs.
Qt owns the native window procedure, scaling, movement and resize operations;
no Python WNDPROC callback is installed. Container recipes are unchanged.

Windows tests exercise complete branding, idle state, window reveal, monitor
work-area maximization, minimize/restore and compact navigation. GUI smoke
checks cover visible content, real model bindings, asynchronous preparation,
data migration and default-Cancel modal confirmation. Additional processes
check 125%, 150% and 200% Qt scaling with the main action still visible.
The `ENGE-SPX-UI-<version>` artifact contains actual Windows source screenshots
and a small result JSON. This still does not replace interactive acceptance on
each user's display, DPI, terminal and Docker Desktop combination.

Use Python 3.12 or newer. Install `requirements.txt` to run from the
source tree, or `python -m pip install -e .` for an editable installation. The
installed command is `spx`; `python -m enge_spx` exposes the same interface.

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
python tools/smoke_gui.py
python -m enge_spx --self-test
```

On Linux, use `PYTHONPATH=src`; GUI checks use Qt's offscreen platform when needed.
Minimal Debian/Ubuntu hosts also need `libegl1`, `libgl1` and `libxkbcommon0`
for Qt GUI modules, including offscreen checks. CI installs these system libraries.
Recreate the artwork with `python tools/render_brand.py` after installing Pillow
and CairoSVG. Artwork dependencies are not included in the distributed app.

Build on x64 Windows with Inno Setup 6 installed:

```powershell
.\packaging\windows\Build-Windows.ps1
```

The build uses `python` on the current PATH, or an explicit executable passed
with `-Python`. CI selects Python 3.12 and checks the frozen runtime reports
the same version. The script recreates its generated `.venv-build` when the
selected Python major/minor differs; it does not ask the Windows launcher to
choose the newest installed interpreter.

Outputs are `dist/ENGE-SPX-Windows-x64-<version>-Setup.exe`, a matching portable
ZIP and SHA-256 files. GUI and CLI share one runtime folder. The version is read
from `enge_spx.__version__`; Windows metadata and CI artifact names must be
updated in the same version change.

The explicit integration scripts contact public IP measurement providers and
create isolated temporary Docker resources. They do not use real service
accounts:

```powershell
python tests/integration_runtime.py --context default --output integration.json
python tests/integration_chain.py --context default
python tools/export_runtime.py --context default --report integration.json --output runtime-package
python tests/integration_prebuilt.py --context default --directory runtime-package
```

Runtime downloads verify the release manifest, exact image recipes, file size
and SHA-256. Both OCI manifest and classic configuration identifiers are recorded
for Docker image-store compatibility. Published assets are not silently replaced.

The release CI pins Linux jobs to `ubuntu-24.04` to avoid an implicit OS migration
through the `ubuntu-latest` label. It builds and tests on Windows and Linux, runs actual Linux x64
containers and tests both Docker image stores. On the independent maintained
repository's main branch, successful Windows and container jobs enable a
versioned full release marked as Latest. The publication script is scoped to
engeeeee/ENGE-SPX. Run `node --test tests/test_release_publication.cjs` with
Node.js 18+ to check release publication and immutable asset handling; Node is
only a development/CI tool and is not bundled with the application.

The UI uses PySide6 Essentials rather than Qt WebEngine. CLI/background entry
points do not import the GUI. The package keeps Qt's shared libraries as
replaceable files and includes license texts, upstream notices and exact source
links from `licenses/Qt-SOURCES.md`. The Windows build expands the notices ZIP.

The default README is Chinese; keep the English README consistent when changing
startup behavior or security claims. Repository About metadata lives in
`.github/repository.json`; an authorized maintainer can apply it with
`tools/Update-Repository.ps1`. The dedicated `repository-about.yml` workflow can
sync description and homepage on main-branch metadata changes after the
repository-scoped `SPX_ABOUT_TOKEN` secret is configured. A file commit without
that authorization does not change GitHub settings. See the repository settings
guide for the required Administration permission and setup instructions.

The P0 security branch keeps production protocol behavior unchanged. Read the
[source audit](security-p0-audit.zh-CN.md) and [security upgrade guide](security-hardening.zh-CN.md).
`tests/test_credentials.py` uses real current-user DPAPI on Windows; other platforms
exercise migration with a test-only opaque-handle provider, never a substitute cipher.
`tests/test_security_p0.py` covers privilege rejection, sandbox evidence, secret stdin,
redaction, deletion and stale terminal handoffs. Real Docker tests also verify the
renderer kernel state, VNC/X11 separation, login callbacks and persistent data.

Run the unprivileged sandbox feasibility probe explicitly on a Docker host:

```powershell
python tools/probe_sandbox.py --output sandbox.json
```

It does not alter host userns, AppArmor or other global policies. The isolated
`security-p0.yml` workflow repeats Windows/Linux regression and packaging checks
without publishing a release. `tools/benchmark_p0.py` compares a pinned 0.8.2 source
baseline and the candidate sequentially on one runner; its synthetic browser fixture
uses network none. Host process, container and WSL-wide measurements must be labeled
separately. Measurements do not assert a target speedup, anonymity or real-account access.

The startup unit suite covers readiness, legacy CLI fallback, bounded waiting,
cancellation, context restrictions, existing-image reuse and explicit exit
review. Windows CI compiles an isolated fake Desktop/CLI pair to exercise real
process launching from a custom path with spaces; it never launches the runner's
actual Docker Desktop. This is not a substitute for first-install WSL/permission
dialogs or a physical Windows + Docker Desktop + v2ray + custom terminal acceptance run.

`tests/test_gui_startup.py` also exercises the real application entry point,
and CI repeats it against `dist/ENGE-SPX/ENGE-SPX.exe` with `--packaged` after
freezing. Both automatic launch paths must reach engine readiness, survive a
separate foreground GUI's theme notifications, respond to Windows and close
normally. Fake-Desktop tests do not claim real Desktop/WSL acceptance.

`gui_diagnostics.py` keeps bounded local `logs/gui.log` and `logs/gui-fault.log`
records, including fatal stacks without stderr. It omits exception messages
and frame locals and closes its handles during data migration. Source GUI
checks have a bounded fatal-stack timer so a broken modal cannot hang CI.

The resource batch adds `resource_limits.py`, `process_metrics.py` and
`resource_monitor.py`: validated stopped-container budgets, read-only OS counters,
and scoped Docker stats. The resource page samples only while its overview is
visible. It does not replace guard or reduce security checks. See the
[resource guide](resources.zh-CN.md) and [validation record](validation-resources.zh-CN.md).
`resources-p1.yml` keeps three alternating-order host pairs; formal CI adds real
cgroup checks and `tools/benchmark_resources.py` after verified runtime tests.
The Docker fixture compares 0.9.0 normal, candidate normal and candidate low using
the same images. It labels tool startup, synthetic load and Chromium activity
separately and does not claim real AI account/noVNC/physical WSL acceptance.
