# Shared one-directory runtime: both entry points use the same DLLs and assets.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parents[1]
resources = root / 'src/enge_spx/resources'
data = [(str(resources), 'enge_spx/resources')]
data += collect_data_files('tzdata')
data += collect_data_files('PySide6', includes=['**/LICENSES/**', '**/licenses/**'])
a = Analysis([str(root / 'src/entry.py')], pathex=[str(root / 'src')], binaries=[], datas=data, hiddenimports=[], hookspath=[], runtime_hooks=[], excludes=['PIL', 'cairosvg', 'pytest', 'tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml', 'PySide6.QtQuick'])
pyz = PYZ(a.pure)
common = dict(exclude_binaries=True, debug=False, strip=False, upx=False,
              icon=str(resources / 'icons/app.ico'))
gui = EXE(pyz, a.scripts, [], name='ENGE-SPX', console=False, version=str(root / 'packaging/windows/version-info.txt'), **common)
cli = EXE(pyz, a.scripts, [], name='spx', console=True, version=str(root / 'packaging/windows/cli-version-info.txt'), **common)
coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name='ENGE-SPX')
