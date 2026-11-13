param(
    [string]$Project = (Join-Path $env:TEMP ('ENGE-SPX-Clipboard-' + [guid]::NewGuid().ToString('N'))),
    [switch]$RunNativeApiTests
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows -and $PSVersionTable.PSEdition -eq 'Core') { throw '需要 Windows 测试桌面。' }
$root = [IO.Path]::GetFullPath($Project)
if (Test-Path -LiteralPath $root) { throw '请指定全新测试目录，避免覆盖已有项目。' }
[IO.Directory]::CreateDirectory($root) | Out-Null
$nonce = [guid]::NewGuid().ToString('N').Substring(0, 12)
$utf8 = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $root '日志-中文.txt'), "Smart Clipboard fixture: $nonce`r`n第二行 Unicode 🦄`r`n", $utf8)
[IO.File]::WriteAllText((Join-Path $root 'fixture.py'), "# synthetic fixture $nonce`nprint('clipboard test')`n", $utf8)
Add-Type -AssemblyName System.Drawing
foreach ($index in 1, 2) {
    $bitmap = New-Object Drawing.Bitmap(960, 540)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $font = New-Object Drawing.Font('Arial', 28)
    try {
        $graphics.Clear([Drawing.Color]::FromArgb(28, 26, 24))
        $graphics.FillRectangle([Drawing.Brushes]::Coral, 60, 60, (160 * $index), 100)
        $graphics.DrawString("SPX $nonce / IMAGE $index", $font, [Drawing.Brushes]::White, 60, 220)
        $bitmap.Save((Join-Path $root "图片-$index.png"), [Drawing.Imaging.ImageFormat]::Png)
        $bitmap.Save((Join-Path $root "picture-$index.jpg"), [Drawing.Imaging.ImageFormat]::Jpeg)
    } finally {
        $font.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
    }
}
# A genuine small PDF containing a fixture nonce, without a PDF dependency.
$content = "BT /F1 20 Tf 40 740 Td (SPX PDF fixture $nonce) Tj ET"
$objects = @(
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    "<< /Length $($content.Length) >>`nstream`n$content`nendstream"
)
$pdf = New-Object Text.StringBuilder
[void]$pdf.Append("%PDF-1.4`n")
$offsets = @()
for ($i = 0; $i -lt $objects.Count; $i++) {
    $offsets += $pdf.Length
    [void]$pdf.Append("$($i+1) 0 obj`n$($objects[$i])`nendobj`n")
}
$xref = $pdf.Length
[void]$pdf.Append("xref`n0 6`n0000000000 65535 f `n")
foreach ($offset in $offsets) { [void]$pdf.Append(($offset.ToString('D10') + " 00000 n `n")) }
[void]$pdf.Append("trailer`n<< /Size 6 /Root 1 0 R >>`nstartxref`n$xref`n%%EOF`n")
[IO.File]::WriteAllBytes((Join-Path $root 'fixture.pdf'), [Text.Encoding]::ASCII.GetBytes($pdf.ToString()))
[IO.File]::WriteAllText((Join-Path $root 'manual-results.json'), (@{
    schema = 1; fixture_nonce = $nonce; status = 'not_run'; platform = [Environment]::OSVersion.VersionString
    screenshot_claude = 'pending'; screenshot_codex = 'pending'; pdf = 'pending'
    mixed_order = 'pending'; native_keyboard = 'pending'; readonly = 'pending'; isolation = 'pending'
    restart = 'pending'; external_terminals = 'pending'; performance = 'not_measured'
} | ConvertTo-Json), $utf8)
if ($RunNativeApiTests) {
    Push-Location (Split-Path -Parent $PSScriptRoot)
    try {
        $env:PYTHONPATH = 'src'
        Write-Host '以下测试替换并清空测试桌面的剪贴板，不备份个人剪贴板。'
        python -m unittest discover -s tests -p test_windows_clipboard.py -v
        if ($LASTEXITCODE -ne 0) { throw 'Windows 原生接口测试未通过。' }
    } finally { Pop-Location }
}
Write-Host "测试项目：$root"
Write-Host "合成数据标识：$nonce"
Write-Host '在 ENGE SPX 选择该测试项目及智能粘贴终端。先输入一段文字，再截图/复制图片 Ctrl+V，确认原生图片标记；自行回车验证模型读取。'
Write-Host '复制 PDF/日志/代码文件，核对路径和实际读取内容；另测只读、多项目、容器重启及 Windows Terminal/PowerShell。'
Write-Host 'manual-results.json 初始全为 pending；只有亲自完成并记录证据后才能改为 passed。'
