param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$spxRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $spxRoot
$spxBasePython = (Get-Command $Python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$spxBaseVersion = & $spxBasePython -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect the selected build Python.' }
$spxPython = Join-Path $spxRoot '.venv-build\Scripts\python.exe'
$spxExistingVersion = if (Test-Path $spxPython) { & $spxPython -c "import sys; print('.'.join(map(str, sys.version_info[:2])))" } else { '' }
if ($spxExistingVersion -ne $spxBaseVersion) {
    & $spxBasePython -m venv --clear .venv-build
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}
Write-Output "Building with the selected Python $spxBaseVersion"
& $spxPython -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Build dependencies failed to install.' }
$spxVersion = & $spxPython -c "import sys; sys.path.insert(0, 'src'); from enge_spx import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0) { throw 'Unable to determine ENGE SPX version.' }
& $spxPython -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/windows/SPX.spec
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
foreach ($spxNotice in @('README.md','README.zh-CN.md','README.en.md','LICENSE','NOTICE.md','THIRD_PARTY_NOTICES.md','AUTHORS.md','CONTRIBUTING.md','SECURITY.md','SUPPORT.md','CHANGELOG.md')) {
    Copy-Item $spxNotice "dist\ENGE-SPX\$spxNotice" -Force
}
Copy-Item docs 'dist\ENGE-SPX\docs' -Recurse -Force
Copy-Item licenses 'dist\ENGE-SPX\licenses' -Recurse -Force
Expand-Archive -Path 'licenses\qt-6.12.0-notices.zip' -DestinationPath 'dist\ENGE-SPX\THIRD-PARTY-LICENSES\Qt' -Force
New-Item -ItemType Directory -Path 'dist\ENGE-SPX\assets' -Force | Out-Null
Copy-Item assets/logo.svg 'dist\ENGE-SPX\assets\logo.svg' -Force
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

