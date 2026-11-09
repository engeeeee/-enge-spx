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

`theme.py` holds the shared colors and reusable UI surfaces. `window_frame.py`
provides custom title bars and the native Windows non-client message adapter;
`dialogs.py` keeps the controller's modal API while using the shared appearance.
Window callbacks remain alive until the HWND is destroyed and restore the
previous procedure during teardown. Container recipes are unchanged by the UI.

Windows tests exercise client/window bounds, resize hit tests, monitor work-area
maximization, taskbar styles and minimize/restore behavior. GUI smoke checks
cover visible card content, modal confirmation/cancellation and restored grabs.
The `ENGE-SPX-UI-<version>` artifact contains actual Windows source screenshots
and a small result JSON. This still does not replace interactive acceptance on
each user's display, DPI, terminal and Docker Desktop combination.

Use Python 3.12 or newer with Tcl/Tk. Install `requirements.txt` to run from the
source tree, or `python -m pip install -e .` for an editable installation. The
installed command is `spx`; `python -m enge_spx` exposes the same interface.

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
python tools/smoke_gui.py
python -m enge_spx --self-test
```

On Linux, use `PYTHONPATH=src`; the Tk smoke test requires a display or Xvfb.
Recreate the artwork with `python tools/render_brand.py` after installing Pillow
and CairoSVG. Artwork dependencies are not included in the distributed app.

Build on x64 Windows with Inno Setup 6 installed:

```powershell
.\packaging\windows\Build-Windows.ps1
```

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

The CI workflow builds and tests on Windows and Linux, runs actual Linux x64
containers and tests both Docker image stores. On the independent maintained
repository's main branch, successful Windows and container jobs enable a
versioned prerelease. The publication script is scoped to engeeeee/ENGE-SPX.

The default README is Chinese; keep the English README consistent when changing
startup behavior or security claims. Repository About metadata lives in
`.github/repository.json`; an authorized maintainer can apply it with
`tools/Update-Repository.ps1`. The dedicated `repository-about.yml` workflow can
sync description and homepage on main-branch metadata changes after the
repository-scoped `SPX_ABOUT_TOKEN` secret is configured. A file commit without
that authorization does not change GitHub settings. See the repository settings
guide for the required Administration permission and setup instructions.

The startup unit suite covers readiness, legacy CLI fallback, bounded waiting,
cancellation, context restrictions, existing-image reuse and explicit exit
review. Windows CI compiles an isolated fake Desktop/CLI pair to exercise real
process launching from a custom path with spaces; it never launches the runner's
actual Docker Desktop. This is not a substitute for first-install WSL/permission
dialogs or a physical Windows + Docker Desktop + v2ray + Pebrel acceptance run.
