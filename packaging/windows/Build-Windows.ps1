$ErrorActionPreference = 'Stop'
$spxRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $spxRoot
if (-not (Test-Path '.venv-build\Scripts\python.exe')) {
    py -3 -m venv .venv-build
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}
$spxPython = Join-Path $spxRoot '.venv-build\Scripts\python.exe'
& $spxPython -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Build dependencies failed to install.' }
$spxVersion = & $spxPython -c "import sys; sys.path.insert(0, 'src'); from enge_spx import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0) { throw 'Unable to determine ENGE SPX version.' }
& $spxPython -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/windows/SPX.spec
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
foreach ($spxNotice in @('README.zh-CN.md','LICENSE','NOTICE.md','THIRD_PARTY_NOTICES.md','AUTHORS.md')) {
    Copy-Item $spxNotice "dist\ENGE-SPX\$spxNotice" -Force
}
Compress-Archive -Path dist\ENGE-SPX\* -DestinationPath "dist\ENGE-SPX-Windows-x64-$spxVersion-Portable.zip" -Force
$spxCompiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
$spxIscc = if ($spxCompiler) { $spxCompiler.Source } else { "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $spxIscc)) { throw 'Install Inno Setup 6 to build the setup executable.' }
& $spxIscc "/DAppVersion=$spxVersion" packaging/windows/Installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Windows setup build failed.' }
Get-ChildItem dist -File | Where-Object { $_.Name -like "ENGE-SPX-Windows-x64-$spxVersion-*" -and $_.Extension -in '.zip','.exe' } | ForEach-Object {
    $spxDigest = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    [IO.File]::WriteAllText($_.FullName + '.sha256', "$spxDigest  $($_.Name)`n", [Text.UTF8Encoding]::new($false))
}

