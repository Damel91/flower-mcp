#Requires -Version 5.1
# Deterministic frontend checks; never download, install or register a client.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$source = Join-Path $PSScriptRoot 'install.ps1'
$tokens = $null
$parseErrors = $null
$tree = [Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw ($parseErrors | Out-String) }

# Load only the checked helper definitions, never the script's entry point.
foreach ($function in $tree.FindAll({param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst]
}, $false)) {
    . ([scriptblock]::Create($function.Extent.Text))
}

function Assert-True {
    param([bool]$Condition, [string]$Description)
    if (-not $Condition) { throw $Description }
}
function Assert-Rejected {
    param([scriptblock]$Action, [string]$Reason)
    $rejected = $false
    try { & $Action }
    catch {
        Assert-True ($_.Exception.Message -like "*$Reason*") "Wrong rejection: $($_.Exception.Message)"
        $rejected = $true
    }
    Assert-True $rejected "Expected rejection: $Reason"
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('flower-installer-check-' + [guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($temporary)
try {
    Assert-Selection 'codex' $false '' '0.1.0'
    Assert-Selection '' $true '' '10.20.30'
    Assert-Rejected { Assert-Selection '' $false '' '0.1.0' } 'exactly one'
    Assert-Rejected { Assert-Selection 'codex' $true '' '0.1.0' } 'exactly one'
    Assert-Rejected { Assert-Selection '' $true 'private config.json' '0.1.0' } 'ClientConfig'
    foreach ($version in @('v0.1.0', '01.1.0', '0.1', '0.1.0-rc1', "0.1.0`n")) {
        Assert-Rejected { Assert-Selection '' $true '' $version } 'MAJOR.MINOR.PATCH'
    }
    $manifest = Join-Path $temporary 'SHA256SUMS'
    $digest = 'A' * 64
    [IO.File]::WriteAllText($manifest, "$digest  install_flower.py`r`n")
    Assert-True ((Get-InstallerChecksum $manifest) -ceq $digest.ToLowerInvariant()) 'Valid checksum failed.'
    foreach ($invalid in @(
        "$digest  install_flower.py`n$digest  install_flower.py`n",
        "$digest  other.whl`n", "$digest  ../install_flower.py`n",
        "$digest  ..`n", "wrong  install_flower.py`n")) {
        [IO.File]::WriteAllText($manifest, $invalid)
        Assert-Rejected { Get-InstallerChecksum $manifest } 'SHA256SUMS'
    }
    Assert-HTTPS ([uri]'https://github.com/Damel91/flower-mcp')
    Assert-Rejected { Assert-HTTPS ([uri]'http://github.com/file') } 'HTTPS'
    Assert-Rejected { Assert-HTTPS ([uri]'https://secret@example.com/file') } 'credentials'
    $arguments = Get-BackendArguments '0.1.0' 'codex' $false 'C:\Flower test\venv' `
        $true 'C:\Agent config\config.json' 'friend-test' 'C:\Flower test\data'
    $expected = @('--version', '0.1.0', '--profile', 'friend-test', '--platform', 'codex',
        '--venv', 'C:\Flower test\venv', '--upgrade', '--client-config',
        'C:\Agent config\config.json', '--profile-root', 'C:\Flower test\data')
    Assert-True ($arguments.Count -eq $expected.Count) 'Argument count changed.'
    for ($index = 0; $index -lt $expected.Count; $index++) {
        Assert-True ($arguments[$index] -ceq $expected[$index]) 'Literal argument or ordering changed.'
    }
    $withoutClient = Get-BackendArguments '0.1.0' '' $true '' $false '' 'default' ''
    Assert-True (($withoutClient -contains '--no-register') -and
        -not ($withoutClient -contains '--platform')) 'No-register route changed.'
    $shell = (Get-Process -Id $PID).Path
    Invoke-CheckedNative $shell @('-NoProfile', '-NonInteractive', '-Command', 'exit 0') 'test native success'
    Assert-Rejected {
        Invoke-CheckedNative $shell @('-NoProfile', '-NonInteractive', '-Command', 'exit 7') 'test native failure'
    } 'exit code 7'
    # A launch failure must never reuse a previous successful native exit code.
    Invoke-CheckedNative $shell @('-NoProfile', '-NonInteractive', '-Command', 'exit 0') 'probe baseline'
    $missingApplication = Join-Path $temporary 'missing-python.exe'
    function Get-Command {
        param($Name, $CommandType, $ErrorAction)
        return [pscustomobject]@{ Source = $missingApplication }
    }
    try { Assert-True ($null -eq (Find-SuitablePython)) 'Broken Python candidate was admitted.' }
    finally { Remove-Item Function:Get-Command }
    Write-Host 'Windows installer syntax and deterministic helper checks passed; no installation effects.'
}
finally { Remove-Item -LiteralPath $temporary -Recurse -Force }
