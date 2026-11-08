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
versioned prerelease. The publication script is scoped to engeeeee/-enge-spx.
