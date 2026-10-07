[CmdletBinding()]
param(
    [ValidateSet('install', 'uninstall', 'reinstall', 'update', 'update-deps')]
    [string]$Action = 'install',
    [string]$Directory,
    [string]$Venv,
    [ValidateSet('main', 'develop')]
    [string]$Branch = $(if ($env:SPIRIT_PET_BRANCH) { $env:SPIRIT_PET_BRANCH } else { 'main' }),
    [string]$ListenHost = '127.0.0.1',
    [ValidateRange(1, 65535)][int]$Port = 8080,
    [switch]$Yes,
    [switch]$NoStart,
    [switch]$SkipSystem
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Repository = 'liyw0205/nonebot_plugin_spirit_pet'
$LocalProject = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$InstallerPath = $PSCommandPath

function Test-Project([string]$Path) {
    return (Test-Path -LiteralPath (Join-Path $Path 'pyproject.toml')) -and
        (Test-Path -LiteralPath (Join-Path $Path 'requirements.txt')) -and
        (Test-Path -LiteralPath (Join-Path $Path 'src/plugins/nonebot_plugin_spirit_pet/__init__.py')) -and
        (Test-Path -LiteralPath (Join-Path $Path 'scripts/install.ps1')) -and
        (Test-Path -LiteralPath (Join-Path $Path 'scripts/xiupet.ps1'))
}

function Get-ProjectPath {
    if ($Directory) { $Value = $Directory }
    elseif (Test-Project $LocalProject) { $Value = $LocalProject }
    else { $Value = Join-Path $HOME 'spirit-pet' }
    $Full = [IO.Path]::GetFullPath($Value)
    if (Test-Path -LiteralPath $Full) {
        $Item = Get-Item -LiteralPath $Full -Force
        if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing a linked installation path: $Full" }
    }
    return $Full
}

function Find-Python {
    $Candidates = @()
    if ($env:SPIRIT_PET_PYTHON) { $Candidates += $env:SPIRIT_PET_PYTHON }
    $Candidates += @('python', (Join-Path $env:LOCALAPPDATA 'Programs/Python/Python312/python.exe'))
    foreach ($Candidate in $Candidates) {
        $Command = Get-Command $Candidate -ErrorAction SilentlyContinue
        if (-not $Command) { continue }
        $Version = & $Command.Source --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $Version -match '^Python\s+(\d+)\.(\d+)(?:\.\d+)?$') {
            if ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 10) { return $Command.Source }
        }
    }
    return $null
}

function Install-Python {
    if ($SkipSystem) { throw 'No usable Python was found and -SkipSystem was specified. Install Python 3.10+ and retry.' }
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        & winget install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) {
            $Found = Find-Python
            if ($Found) { return $Found }
        }
        Write-Host 'winget could not install Python; trying the signed python.org installer.'
    }
    $Url = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
    $Temporary = Join-Path ([IO.Path]::GetTempPath()) ('spirit-pet-python-' + [Guid]::NewGuid().ToString('N'))
    $Installer = Join-Path $Temporary 'python-installer.exe'
    $Target = Join-Path $env:LOCALAPPDATA 'Programs/Python/Python312'
    New-Item -ItemType Directory -Path $Temporary | Out-Null
    try {
        Write-Host 'Downloading the official Python 3.12.10 installer from python.org...'
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Installer
        $Signature = Get-AuthenticodeSignature -FilePath $Installer
        if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            throw 'The Python installer signature is invalid or is not from the Python Software Foundation.'
        }
        $Arguments = "/quiet InstallAllUsers=0 TargetDir=`"$Target`" PrependPath=0 Include_launcher=1 Include_pip=1 Include_test=0 Shortcuts=0"
        $Process = Start-Process -FilePath $Installer -ArgumentList $Arguments -Wait -PassThru
        if ($Process.ExitCode -notin @(0, 3010)) { throw "Python installation failed with exit code $($Process.ExitCode)." }
    } finally {
        Remove-Item -LiteralPath $Temporary -Recurse -Force -ErrorAction SilentlyContinue
    }
    $Found = Find-Python
    if (-not $Found) { throw 'Python installation completed but no usable Python was found.' }
    return $Found
}

function Stop-InstalledBot([string]$Path) {
    $Manager = Join-Path $Path 'scripts/xiupet.ps1'
    if (Test-Path -LiteralPath $Manager) {
        $PreviousProject = $env:XIUPET_PROJECT
        $env:XIUPET_PROJECT = $Path
        try { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Manager stop }
        finally { $env:XIUPET_PROJECT = $PreviousProject }
    }
}

function Uninstall-Project([string]$Path) {
    if (-not (Test-Project $Path)) { throw "Not a Spirit Pet project: $Path" }
    if ((Test-Path -LiteralPath (Join-Path $Path '.git')) -and -not $Yes) {
        throw 'Refusing to remove a Git checkout without -Yes and -Directory.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Path '.xiupet-install')) -and -not $Yes) {
        throw 'Refusing to remove an unmarked source checkout without -Yes.'
    }
    if (-not $Yes) {
        if (-not [Environment]::UserInteractive) { throw 'Uninstall is destructive; pass -Yes in a non-interactive shell.' }
        $Answer = Read-Host "Remove $Path and its project environment/data? [y/N]"
        if ($Answer -notin @('y', 'Y', 'yes', 'YES')) { Write-Host 'Uninstall cancelled.'; return }
    }
    Stop-InstalledBot $Path
    $CommandFile = Join-Path $Path '.xiupet-command'
    $Shortcut = if (Test-Path -LiteralPath $CommandFile) { (Get-Content -Raw -LiteralPath $CommandFile).Trim() } else { '' }
    if ($Shortcut -and [IO.Path]::GetFileName($Shortcut) -eq 'xiupet.cmd' -and (Test-Path -LiteralPath $Shortcut)) {
        $Text = Get-Content -Raw -LiteralPath $Shortcut
        if ($Text.Contains($Path)) { Remove-Item -LiteralPath $Shortcut -Force }
        Remove-Item -LiteralPath ([IO.Path]::ChangeExtension($Shortcut, '.ps1')) -Force -ErrorAction SilentlyContinue
    }
    if ($InstallerPath.StartsWith($Path, [StringComparison]::OrdinalIgnoreCase)) {
        $LiteralPath = $Path.Replace("'", "''")
        $Cleanup = "Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$LiteralPath' -Recurse -Force"
        if ($Shortcut) {
            $ShortcutLiteral = $Shortcut.Replace("'", "''")
            $Cleanup += "; Remove-Item -LiteralPath '$ShortcutLiteral' -Force -ErrorAction SilentlyContinue"
        }
        $Encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Cleanup))
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @('-NoProfile', '-NonInteractive', '-EncodedCommand', $Encoded)
        Write-Host "Uninstall scheduled for $Path after the current PowerShell process exits."
        return
    }
    Remove-Item -LiteralPath $Path -Recurse -Force
    Write-Host "Uninstalled Spirit Pet from $Path"
}

function Test-Archive([string]$ArchivePath) {
    $Names = @(& tar.exe -tzf $ArchivePath 2>$null)
    if ($LASTEXITCODE -ne 0 -or $Names.Count -eq 0) { return $false }
    $Root = $null
    $Seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($Entry in $Names) {
        $Name = $Entry.TrimEnd('/')
        if (-not $Name -or $Name.StartsWith('/') -or $Name.Contains('\') -or $Name -match '^[A-Za-z]:' -or $Name -match '(^|/)\.\.?($|/)') { return $false }
        $Parts = $Name.Split('/')
        if (-not $Root) { $Root = $Parts[0] }
        if ($Parts[0] -ne $Root -or -not $Seen.Add($Name)) { return $false }
        foreach ($Part in $Parts) {
            if ($Part.EndsWith('.') -or $Part.EndsWith(' ') -or $Part.Split('.')[0] -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$') { return $false }
        }
    }
    $Verbose = @(& tar.exe -tvzf $ArchivePath 2>$null)
    if ($LASTEXITCODE -ne 0 -or $Verbose.Count -ne $Names.Count) { return $false }
    $Expanded = [int64]0
    foreach ($Entry in $Verbose) {
        if ($Entry[0] -notin @('-', 'd')) { return $false }
        $Fields = $Entry -split '\s+'
        $Size = 0L
        if ($Entry -match '^\S+\s+\S+/\S+\s+(\d+)\s') { $Size = [int64]$Matches[1] }
        elseif ($Entry -match '^\S+\s+\d+\s+\d+\s+(\d+)\s') { $Size = [int64]$Matches[1] }
        $Expanded += $Size
        if ($Expanded -gt 104857600) { return $false }
    }
    return $true
}

function Download-Project([string]$Temporary) {
    $Sources = @('', 'https://gh-proxy.com/', 'https://gh.jasonzeng.dev/', 'https://git.yylx.win/', 'https://wget.la/')
    $Url = "https://github.com/$Repository/archive/refs/heads/$Branch.tar.gz"
    $Available = @()
    for ($Index = 0; $Index -lt $Sources.Count; $Index++) {
        $Name = if ($Sources[$Index]) { $Sources[$Index] } else { 'GitHub' }
        $Archive = Join-Path $Temporary "source-$Index.tar.gz"
        $Watch = [Diagnostics.Stopwatch]::StartNew()
        try {
            Invoke-WebRequest -UseBasicParsing -Uri ($Sources[$Index] + $Url) -OutFile $Archive -TimeoutSec 60
            if ((Get-Item -LiteralPath $Archive).Length -gt 20971520 -or -not (Test-Archive $Archive)) { throw 'Archive validation failed or size limit exceeded' }
            $Watch.Stop()
            Write-Host "[$($Index+1)/5] $Name`: OK $([int]$Watch.Elapsed.TotalMilliseconds) ms, archive validated"
            $Available += [pscustomobject]@{ Milliseconds = $Watch.Elapsed.TotalMilliseconds; Name = $Name; Archive = $Archive }
        } catch {
            Write-Host "[$($Index+1)/5] $Name`: FAILED $($_.Exception.Message)"
            Remove-Item -LiteralPath $Archive -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not $Available) { throw 'All source downloads failed. Check DNS/TLS/network or use a complete local checkout.' }
    $Selected = $Available | Sort-Object Milliseconds | Select-Object -First 1
    Write-Host "Selected source: $($Selected.Name)"
    $Extract = Join-Path $Temporary 'source'
    New-Item -ItemType Directory -Path $Extract | Out-Null
    $Root = (@(& tar.exe -tzf $Selected.Archive)[0]).Split('/')[0]
    & tar.exe -xzf $Selected.Archive -C $Extract --strip-components=1 $Root
    if ($LASTEXITCODE -ne 0 -or -not (Test-Project $Extract)) { throw 'Downloaded archive is missing required project files.' }
    return $Extract
}

function Copy-Project([string]$Source, [string]$Destination) {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    foreach ($Name in @('pyproject.toml', 'requirements.txt', '.env.example', 'README.md', 'LICENSE', 'src', 'scripts', 'docs')) {
        $Origin = Join-Path $Source $Name
        if (-not (Test-Path -LiteralPath $Origin)) { continue }
        $Target = Join-Path $Destination $Name
        if (Test-Path -LiteralPath $Origin -PathType Container) {
            New-Item -ItemType Directory -Path $Target -Force | Out-Null
            Copy-Item -Path (Join-Path $Origin '*') -Destination $Target -Recurse -Force
        } else { Copy-Item -LiteralPath $Origin -Destination $Target -Force }
    }
}

function Set-EnvironmentFile([string]$Path) {
    if (Test-Path -LiteralPath (Join-Path $Path '.env')) {
        Write-Host "Keeping existing configuration unchanged: $(Join-Path $Path '.env')"
        return
    }
    $Destination = Join-Path $Path '.env'
    $Temporary = Join-Path $Path ('.env.' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $Bytes = New-Object byte[] 32
    $Random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $Random.GetBytes($Bytes) } finally { $Random.Dispose() }
    $Token = [BitConverter]::ToString($Bytes).Replace('-', '').ToLowerInvariant()
    $Text = [IO.File]::ReadAllText((Join-Path $Path '.env.example'))
    $Text = [regex]::Replace($Text, '(?m)^HOST=.*$', "HOST=$ListenHost")
    $Text = [regex]::Replace($Text, '(?m)^PORT=.*$', "PORT=$Port")
    $Text = $Text.TrimEnd([char[]]@("`r", "`n")) + "`r`nONEBOT_V11_ACCESS_TOKEN=$Token`r`n"
    [IO.File]::WriteAllText($Temporary, $Text, (New-Object Text.UTF8Encoding($false)))
    try { [IO.File]::Move($Temporary, $Destination) }
    finally { Remove-Item -LiteralPath $Temporary -Force -ErrorAction SilentlyContinue }
    Write-Host "Created private configuration: $Destination"
}

function Install-Xiupet([string]$Path, [string]$Environment) {
    $Bin = Join-Path $HOME 'bin'
    New-Item -ItemType Directory -Path $Bin -Force | Out-Null
    $Command = Join-Path $Bin 'xiupet.cmd'
    $PowerShellCommand = Join-Path $Bin 'xiupet.ps1'
    $ProjectLiteral = "'" + $Path.Replace("'", "''") + "'"
    $ManagerLiteral = "'" + (Join-Path $Path 'scripts/xiupet.ps1').Replace("'", "''") + "'"
    $PowerShellText = "`$env:XIUPET_PROJECT = $ProjectLiteral`r`n& $ManagerLiteral @args`r`nexit `$LASTEXITCODE`r`n"
    $CommandText = "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%~dp0xiupet.ps1`" %*`r`n"
    if ((Test-Path -LiteralPath $PowerShellCommand) -and
        -not (Get-Content -Raw -LiteralPath $PowerShellCommand).Contains($Path)) {
        throw "Refusing to overwrite an existing command: $PowerShellCommand"
    }
    if ((Test-Path -LiteralPath $Command) -and -not (Test-Path -LiteralPath $PowerShellCommand)) {
        throw "Refusing to overwrite an existing command: $Command"
    }
    [IO.File]::WriteAllText($PowerShellCommand, $PowerShellText, [Text.Encoding]::ASCII)
    [IO.File]::WriteAllText($Command, $CommandText, [Text.Encoding]::ASCII)
    Set-Content -LiteralPath (Join-Path $Path '.xiupet-command') -Value $Command -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $Path '.xiupet-venv') -Value $Environment -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $Path '.xiupet-install') -Value 'source-install' -Encoding ASCII
    $UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $Parts = @($UserPath -split ';' | Where-Object { $_ })
    if ($Parts -notcontains $Bin) {
        [Environment]::SetEnvironmentVariable('Path', (($Parts + $Bin) -join ';'), 'User')
        $env:Path += ";$Bin"
        Write-Host "Added $Bin to the user PATH. Open a new terminal to use xiupet."
    }
    Write-Host "Generated management command: $Command"
}

$Target = Get-ProjectPath
if ($Action -eq 'uninstall') { Uninstall-Project $Target; exit 0 }

$NeedsDownload = $false
if ($Action -eq 'update' -and (Test-Path -LiteralPath (Join-Path $Target '.git'))) { }
elseif ($Action -eq 'update-deps') {
    if (-not (Test-Project $Target)) { throw "Not a Spirit Pet project: $Target" }
} elseif ($Action -eq 'update' -and (Test-Project $Target)) { $NeedsDownload = $true }
elseif (-not (Test-Project $Target) -and -not (Test-Project $LocalProject)) { $NeedsDownload = $true }

$Python = Find-Python
if (-not $Python) { $Python = Install-Python }
if (-not $Python) { throw 'No usable Python >=3.10,<4.0 was found.' }

if ($Action -eq 'update' -and (Test-Path -LiteralPath (Join-Path $Target '.git'))) {
    $Status = & git -C $Target status --porcelain
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect Git checkout.' }
    if ($Status) { throw 'Git checkout has local changes; save them before update.' }
    $CurrentBranch = (& git -C $Target branch --show-current).Trim()
    if (-not $CurrentBranch) { throw 'Cannot update a detached Git checkout.' }
    Stop-InstalledBot $Target
    & git -C $Target pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'Fast-forward update failed.' }
} elseif ($Action -ne 'update-deps' -and -not (Test-Project $Target)) {
    $Temporary = Join-Path ([IO.Path]::GetTempPath()) ('spirit-pet-install-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Temporary | Out-Null
    try {
        if ((Test-Project $Target) -and $Action -ne 'update') { $Source = $Target }
        elseif ((Test-Project $LocalProject) -and $LocalProject -ne $Target) { $Source = $LocalProject }
        else { $Source = Download-Project $Temporary }
        if (Test-Path -LiteralPath $Target) {
            $Children = @(Get-ChildItem -LiteralPath $Target -Force)
            if ($Children.Count -gt 0 -and -not (Test-Project $Target)) { throw "Refusing to overwrite a non-project directory: $Target" }
        }
        Copy-Project $Source $Target
    } finally {
        Remove-Item -LiteralPath $Temporary -Recurse -Force -ErrorAction SilentlyContinue
    }
} elseif ($Action -eq 'update' -and (Test-Project $Target)) {
    $Temporary = Join-Path ([IO.Path]::GetTempPath()) ('spirit-pet-update-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Temporary | Out-Null
    try {
        if ((Test-Project $LocalProject) -and $LocalProject -ne $Target) { $Source = $LocalProject }
        else { $Source = Download-Project $Temporary }
        Stop-InstalledBot $Target
        Copy-Project $Source $Target
    } finally {
        Remove-Item -LiteralPath $Temporary -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Project $Target)) { throw "Incomplete project directory: $Target" }
if ($Action -in @('update', 'reinstall')) { Stop-InstalledBot $Target }
if ($Venv) { $Environment = [IO.Path]::GetFullPath($Venv) }
elseif (Test-Path -LiteralPath (Join-Path $Target '.xiupet-venv')) { $Environment = (Get-Content -Raw -LiteralPath (Join-Path $Target '.xiupet-venv')).Trim() }
else { $Environment = Join-Path $Target '.venv' }
$Environment = [IO.Path]::GetFullPath($Environment)
$VenvPython = Join-Path $Environment 'Scripts/python.exe'
$VenvPip = Join-Path $Environment 'Scripts/pip.exe'
if ($Action -eq 'reinstall' -and (Test-Path -LiteralPath $Environment)) {
    if (-not (Test-Path -LiteralPath (Join-Path $Environment 'pyvenv.cfg')) -or -not (Test-Path -LiteralPath $VenvPython)) {
        throw "Refusing to replace an invalid environment: $Environment"
    }
    Remove-Item -LiteralPath $Environment -Recurse -Force
}
if (Test-Path -LiteralPath $Environment) {
    if (-not (Test-Path -LiteralPath (Join-Path $Environment 'pyvenv.cfg')) -or -not (Test-Path -LiteralPath $VenvPython)) {
        throw "Not a usable virtual environment: $Environment"
    }
} else {
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($Environment)) -Force | Out-Null
    & $Python -m venv $Environment
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the project virtual environment.' }
}
if (-not (Test-Path -LiteralPath $VenvPip)) { throw "pip is missing from the virtual environment: $Environment" }
& $VenvPip install --disable-pip-version-check --no-input 'nb-cli==1.5.0'
if ($LASTEXITCODE -ne 0) { throw 'Could not install NoneBot CLI.' }
& $VenvPip install --disable-pip-version-check --no-input -r (Join-Path $Target 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install project dependencies.' }
& $VenvPip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed.' }
& (Join-Path $Environment 'Scripts/nb.exe') --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'NoneBot CLI verification failed.' }

Set-EnvironmentFile $Target
Install-Xiupet $Target $Environment
Write-Host "Project: $Target"
Write-Host "Foreground start: Set-Location '$Target'; & '$Environment/Scripts/nb.exe' run"
Write-Host 'Background management: xiupet start|stop|restart|status|logs|update|update-deps|uninstall'
if (-not $NoStart -and $Action -notin @('update', 'update-deps', 'reinstall')) {
    Push-Location $Target
    try { & (Join-Path $Environment 'Scripts/nb.exe') run; exit $LASTEXITCODE }
    finally { Pop-Location }
}
