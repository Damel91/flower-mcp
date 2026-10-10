#Requires -Version 5.1
<#
.SYNOPSIS
Install a pinned Flower MCP release on Windows.
.DESCRIPTION
Reuses the canonical Python installer. Existing Python 3.11+ is preferred;
otherwise managed Python is prepared without persistent PATH or registry changes.
Choose -Platform codex|claude-code|cursor or -NoRegister. The Python backend owns
installation receipts, explicit upgrades and client registration.
.EXAMPLE
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Platform codex
.EXAMPLE
.\install.ps1 -NoRegister -Venv 'C:\Users\tester\Flower test\venv'
#>
[CmdletBinding()]
param(
    [ValidateSet('codex', 'claude-code', 'cursor')][string]$Platform,
    [switch]$NoRegister,
    [string]$Version = '0.2.0',
    [string]$Venv,
    [switch]$Upgrade,
    [string]$ClientConfig,
    [string]$Profile = 'default',
    [string]$ProfileRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-Selection {
    param([string]$SelectedPlatform, [bool]$WithoutRegistration, [string]$SelectedClientConfig,
          [string]$SelectedVersion)
    if ([bool]$SelectedPlatform -eq $WithoutRegistration) {
        throw 'Choose exactly one of -Platform codex|claude-code|cursor or -NoRegister.'
    }
    if ($WithoutRegistration -and $SelectedClientConfig) {
        throw '-ClientConfig requires -Platform.'
    }
    if ($SelectedVersion -cnotmatch '\A(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\z') {
        throw '-Version must be a stable MAJOR.MINOR.PATCH version, for example 0.1.0.'
    }
}

function Get-BackendArguments {
    param([string]$SelectedVersion, [string]$SelectedPlatform, [bool]$WithoutRegistration,
          [string]$SelectedVenv, [bool]$DoUpgrade, [string]$SelectedClientConfig,
          [string]$SelectedProfile, [string]$SelectedProfileRoot)
    $items = @('--version', $SelectedVersion, '--profile', $SelectedProfile)
    if ($WithoutRegistration) { $items += '--no-register' }
    else { $items += @('--platform', $SelectedPlatform) }
    if ($SelectedVenv) { $items += @('--venv', $SelectedVenv) }
    if ($DoUpgrade) { $items += '--upgrade' }
    if ($SelectedClientConfig) { $items += @('--client-config', $SelectedClientConfig) }
    if ($SelectedProfileRoot) { $items += @('--profile-root', $SelectedProfileRoot) }
    return ,$items
}

function Get-InstallerChecksum {
    param([string]$Manifest)
    $entries = [Collections.Generic.Dictionary[string, string]]::new([StringComparer]::Ordinal)
    foreach ($line in [IO.File]::ReadAllLines($Manifest)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $match = [regex]::Match($line, '\A([A-Fa-f0-9]{64}) [ *]([A-Za-z0-9_.-]+)\z')
        if (-not $match.Success -or $match.Groups[2].Value -in @('.', '..')) {
            throw 'SHA256SUMS contains an invalid checksum entry.'
        }
        $name = $match.Groups[2].Value
        if ($entries.ContainsKey($name)) { throw 'SHA256SUMS contains a duplicate filename.' }
        $entries.Add($name, $match.Groups[1].Value.ToLowerInvariant())
    }
    if (-not $entries.ContainsKey('install_flower.py')) {
        throw 'SHA256SUMS does not identify install_flower.py.'
    }
    return $entries['install_flower.py']
}

function Assert-HTTPS {
    param([uri]$Address)
    if (-not $Address.IsAbsoluteUri -or $Address.Scheme -ne 'https' -or
        -not $Address.Host -or $Address.UserInfo) {
        throw 'Installer downloads require HTTPS without embedded credentials.'
    }
}

function Receive-Asset {
    param([uri]$Address, [string]$Destination, [long]$MaxBytes)
    # Follow each redirect explicitly: PS5.1 automatic redirection cannot enforce
    # the Bash installer's HTTPS-only redirect contract. No HTML is parsed.
    $current = $Address
    for ($hop = 0; $hop -le 5; $hop++) {
        Assert-HTTPS $current
        $request = [Net.HttpWebRequest]::Create($current)
        $request.AllowAutoRedirect = $false
        $request.Timeout = 120000
        $request.ReadWriteTimeout = 120000
        $request.UserAgent = 'Flower-MCP-Windows-Installer'
        $response = $null
        $inputStream = $null
        $outputStream = $null
        try {
            $response = $request.GetResponse()
            $status = [int]$response.StatusCode
            if ($status -in @(301, 302, 303, 307, 308)) {
                $location = $response.Headers['Location']
                if (-not $location -or $hop -eq 5) { throw 'Release redirect limit reached.' }
                $current = [uri]::new($current, $location)
                Assert-HTTPS $current
                continue
            }
            if ($status -ne 200) { throw "Download returned HTTP $status." }
            if ($response.ContentLength -gt $MaxBytes) { throw 'Release asset exceeds the download limit.' }
            $inputStream = $response.GetResponseStream()
            $outputStream = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew,
                [IO.FileAccess]::Write, [IO.FileShare]::None)
            $buffer = New-Object byte[] 65536
            [long]$total = 0
            while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $total += $count
                if ($total -gt $MaxBytes) { throw 'Release asset exceeds the download limit.' }
                $outputStream.Write($buffer, 0, $count)
            }
            return
        }
        finally {
            if ($outputStream) { $outputStream.Dispose() }
            if ($inputStream) { $inputStream.Dispose() }
            if ($response) { $response.Dispose() }
        }
    }
    throw 'Release redirect limit reached.'
}

function Invoke-CheckedNative {
    param([string]$Executable, [string[]]$Arguments, [string]$Stage)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Stage failed with exit code $LASTEXITCODE." }
}

function Find-SuitablePython {
    $probe = 'import sys, ssl, venv, ensurepip; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
    foreach ($name in @('py.exe', 'python3.exe', 'python.exe')) {
        $application = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if (-not $application -or $application.Source -match '[\\/]WindowsApps[\\/]') { continue }
        $prefix = @()
        if ($name -eq 'py.exe') { $prefix = @('-3') }
        $probeArguments = $prefix + @('-I', '-c', $probe)
        # Old or broken candidates are not installation success. Probe only;
        # normal execution below retains stderr and checks every native exit.
        $ErrorActionPreference = 'Continue'
        try {
            $succeeded = $false
            try {
                & $application.Source @probeArguments 1>$null 2>$null
                $succeeded = $? -and ($LASTEXITCODE -eq 0)
            }
            catch { $succeeded = $false }
            if ($succeeded) {
                return @{ Executable = $application.Source; Prefix = $prefix }
            }
        }
        finally { $ErrorActionPreference = 'Stop' }
    }
    return $null
}

$scratch = $null
$exitCode = 1
$savedEnvironment = @{}
$environmentNames = @('UV_INSTALL_DIR', 'CARGO_DIST_FORCE_INSTALL_DIR', 'UV_UNMANAGED_INSTALL',
    'UV_NO_MODIFY_PATH', 'UV_DOWNLOAD_URL', 'INSTALLER_DOWNLOAD_URL', 'UV_INSTALLER_GHE_BASE_URL',
    'UV_INSTALLER_GITHUB_BASE_URL', 'UV_GITHUB_TOKEN', 'UV_PYTHON_INSTALL_DIR', 'UV_CACHE_DIR',
    'UV_PYTHON_NO_REGISTRY', 'TEMP', 'TMP')
$savedTLS = [Net.ServicePointManager]::SecurityProtocol
try {
    Assert-Selection $Platform $NoRegister.IsPresent $ClientConfig $Version
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'This PowerShell installer supports Windows; macOS/Linux use install.sh.'
    }
    $scratch = Join-Path ([IO.Path]::GetTempPath()) ('flower-release-' + [guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($scratch)
    [Net.ServicePointManager]::SecurityProtocol = $savedTLS -bor [Net.SecurityProtocolType]::Tls12
    $releaseURL = "https://github.com/Damel91/flower-mcp/releases/download/v$Version"
    $manifest = Join-Path $scratch 'SHA256SUMS'
    $backend = Join-Path $scratch 'install_flower.py'
    Receive-Asset "$releaseURL/SHA256SUMS" $manifest 1048576
    Receive-Asset "$releaseURL/install_flower.py" $backend 8388608
    $expected = Get-InstallerChecksum $manifest
    $actual = (Get-FileHash -LiteralPath $backend -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -cne $expected) { throw 'Python installer checksum does not match the pinned release.' }

    $python = Find-SuitablePython
    if (-not $python) {
        Write-Host 'Preparing managed Python 3.11 for Flower MCP...'
        $uvVersion = '0.12.21'
        $uvInstaller = Join-Path $scratch 'uv-installer.ps1'
        Receive-Asset "https://astral.sh/uv/$uvVersion/install.ps1" $uvInstaller 8388608
        foreach ($name in $environmentNames) {
            $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
            [Environment]::SetEnvironmentVariable($name, $null, 'Process')
        }
        $base = $env:LOCALAPPDATA
        if (-not $base) { $base = Join-Path ([Environment]::GetFolderPath('UserProfile')) 'AppData\Local' }
        $installationBase = Join-Path $base 'Flower MCP Install'
        $env:UV_UNMANAGED_INSTALL = Join-Path $scratch 'uv'
        $env:UV_NO_MODIFY_PATH = '1'
        $env:UV_PYTHON_NO_REGISTRY = '1'
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $installationBase 'python'
        $env:UV_CACHE_DIR = Join-Path $scratch 'uv-cache'
        $env:TEMP = $scratch
        $env:TMP = $scratch
        $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        Invoke-CheckedNative $shell @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', $uvInstaller) 'uv bootstrap'
        $uv = Join-Path $env:UV_UNMANAGED_INSTALL 'uv.exe'
        $uvIdentity = & $uv --version
        if ($LASTEXITCODE -ne 0 -or $uvIdentity -cnotmatch
            ('\Auv ' + [regex]::Escape($uvVersion) + '(?: [^\r\n]*)?\z')) {
            throw 'uv bootstrap version differs from the pinned version.'
        }
        $bootstrap = Join-Path $scratch 'bootstrap'
        Invoke-CheckedNative $uv @('--no-config', '--directory', $scratch, 'venv', '--seed',
            '--managed-python', '--python', '3.11', $bootstrap) 'managed Python preparation'
        $python = @{ Executable = (Join-Path $bootstrap 'Scripts\python.exe'); Prefix = @() }
    }
    $backendArguments = Get-BackendArguments $Version $Platform $NoRegister.IsPresent $Venv `
        $Upgrade.IsPresent $ClientConfig $Profile $ProfileRoot
    $arguments = $python.Prefix + @('-I', $backend) + $backendArguments
    & $python.Executable @arguments
    $exitCode = $LASTEXITCODE
}
catch {
    [Console]::Error.WriteLine(('Flower installation failed: ' + $_.Exception.Message))
    $exitCode = 1
}
finally {
    [Net.ServicePointManager]::SecurityProtocol = $savedTLS
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
    if ($scratch -and (Test-Path -LiteralPath $scratch)) {
        try { Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction Stop }
        catch {
            [Console]::Error.WriteLine('Flower temporary files could not be removed; remove the reported task directory manually.')
            [Console]::Error.WriteLine($scratch)
            if ($exitCode -eq 0) { $exitCode = 1 }
        }
    }
}
exit $exitCode
