param(
    [ValidateSet('start', 'stop', 'restart', 'status', 'logs', 'update', 'update-deps', 'uninstall')]
    [string]$Action = 'status',
    [switch]$Yes,
    [ValidateRange(1, 10000)][int]$Lines = 80
)
$ErrorActionPreference = 'Stop'

$Project = $env:XIUPET_PROJECT
if (-not $Project) { $Project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path }
$Project = [IO.Path]::GetFullPath($Project)
$Runtime = Join-Path $Project '.xiupet'
$PidFile = Join-Path $Runtime 'pid'
$LogFile = Join-Path $Runtime 'run.log'
$Venv = Join-Path $Project '.venv'
$VenvMarker = Join-Path $Project '.xiupet-venv'
if (Test-Path -LiteralPath $VenvMarker) { $Venv = (Get-Content -Raw -LiteralPath $VenvMarker).Trim() }
$Nb = Join-Path $Venv 'Scripts/nb.exe'

function Read-Pid {
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    $Value = (Get-Content -Raw -LiteralPath $PidFile).Trim()
    $Number = 0
    if (-not [int]::TryParse($Value, [ref]$Number) -or $Number -le 0) { return $null }
    return $Number
}

function Get-ProcessForPid([int]$Id) {
    try { return Get-Process -Id $Id -ErrorAction Stop } catch { return $null }
}

function Stop-Bot {
    $Id = Read-Pid
    if (-not $Id -or -not (Get-ProcessForPid $Id)) {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        Write-Host 'xiupet is already stopped'
        return
    }
    & taskkill.exe /PID $Id /T /F | Out-Null
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Write-Host "xiupet stopped (pid $Id)"
}

function Start-Bot {
    $Id = Read-Pid
    if ($Id -and (Get-ProcessForPid $Id)) {
        Write-Host "xiupet is already running (pid $Id)"
        return
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $Nb -PathType Leaf)) { throw "NoneBot CLI not found: $Nb. Run xiupet update-deps first." }
    New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
    $Process = Start-Process -FilePath $Nb -ArgumentList 'run' -WorkingDirectory $Project `
        -RedirectStandardOutput $LogFile -PassThru -WindowStyle Hidden
    Set-Content -LiteralPath $PidFile -Value $Process.Id -NoNewline -Encoding ascii
    Start-Sleep -Milliseconds 250
    if (-not (Get-ProcessForPid $Process.Id)) {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        throw "xiupet failed to start; inspect $LogFile"
    }
    Write-Host "xiupet started (pid $($Process.Id))"
    Write-Host "log: $LogFile"
}

function Invoke-Installer([string]$RequestedAction) {
    $Installer = Join-Path $Project 'scripts/install.ps1'
    if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) { throw "Installer not found: $Installer" }
    $Arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Installer,
        '-Action', $RequestedAction, '-Directory', $Project, '-Venv', $Venv, '-Yes', '-NoStart')
    & powershell.exe @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

switch ($Action) {
    'start' { Start-Bot }
    'stop' { Stop-Bot }
    'restart' { Stop-Bot; Start-Bot }
    'status' {
        $Id = Read-Pid
        if ($Id -and (Get-ProcessForPid $Id)) {
            Write-Host "xiupet is running (pid $Id)"
            Write-Host "log: $LogFile"
        } else {
            Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
            Write-Host 'xiupet is stopped'
            exit 1
        }
    }
    'logs' {
        if (Test-Path -LiteralPath $LogFile) { Get-Content -LiteralPath $LogFile -Tail $Lines }
        else { Write-Host "No log file yet: $LogFile" }
    }
    'update' { Stop-Bot; Invoke-Installer 'update' }
    'update-deps' { Stop-Bot; Invoke-Installer 'update-deps' }
    'uninstall' {
        Stop-Bot
        $Arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $Project 'scripts/install.ps1'),
            '-Action', 'uninstall', '-Directory', $Project)
        if ($Yes) { $Arguments += '-Yes' }
        & powershell.exe @Arguments
        exit $LASTEXITCODE
    }
}
