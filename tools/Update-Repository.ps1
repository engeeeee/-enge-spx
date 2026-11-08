[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = 'Stop'
$spxMetadataPath = Join-Path $PSScriptRoot '../.github/repository.json'
$spxMetadata = Get-Content -LiteralPath $spxMetadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($spxMetadata.repository -cne 'engeeeee/ENGE-SPX') { throw 'Unexpected target repository.' }
if ([string]::IsNullOrWhiteSpace($spxMetadata.description) -or $spxMetadata.description.Length -gt 350) { throw 'Description must contain 1-350 characters.' }
if ($spxMetadata.homepage -cne 'https://github.com/engeeeee/ENGE-SPX#readme') { throw 'Unexpected homepage.' }
if ($spxMetadata.topics.Count -gt 20) { throw 'Too many topics.' }
foreach ($spxTopic in $spxMetadata.topics) {
    if ($spxTopic -cnotmatch '^[a-z0-9][a-z0-9-]{0,49}$') { throw "Invalid topic: $spxTopic" }
}

if ($PSCmdlet.ShouldProcess($spxMetadata.repository, 'Update About description, homepage and add topics')) {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'Install GitHub CLI and run gh auth login first.' }
    $spxTarget = & gh repo view $spxMetadata.repository --json nameWithOwner --jq '.nameWithOwner'
    if ($LASTEXITCODE -ne 0 -or $spxTarget -cne $spxMetadata.repository) { throw 'Unable to verify the target repository.' }
    $spxArguments = @('repo', 'edit', $spxMetadata.repository, '--description', $spxMetadata.description, '--homepage', $spxMetadata.homepage)
    foreach ($spxTopic in $spxMetadata.topics) { $spxArguments += @('--add-topic', $spxTopic) }
    & gh @spxArguments
    if ($LASTEXITCODE -ne 0) { throw 'Repository About update failed.' }
    Write-Output 'Updated ENGE SPX About from .github/repository.json.'
}
