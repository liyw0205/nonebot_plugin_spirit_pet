[CmdletBinding()]
param(
    [ValidateSet('install', 'uninstall', 'reinstall', 'update', 'update-deps')][string]$Action = 'install',
    [string]$Directory,
    [string]$Venv,
    [ValidateSet('main', 'develop')][string]$Branch = $(if ($env:SPIRIT_PET_BRANCH) { $env:SPIRIT_PET_BRANCH } else { 'main' }),
    [string]$ListenHost = '127.0.0.1',
    [ValidateRange(1, 65535)][int]$Port = 8080,
    [switch]$Yes,
    [switch]$NoStart,
    [switch]$SkipSystem
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Find-Python {
    $Candidates = @()
    if ($env:SPIRIT_PET_PYTHON) { $Candidates += $env:SPIRIT_PET_PYTHON }
    $Candidates += @('python', (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'))
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $Found = & py -3 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $Found) { $Candidates += $Found }
    }
    foreach ($Candidate in $Candidates) {
        if (Get-Command $Candidate -ErrorAction SilentlyContinue) {
            & $Candidate -c 'import sys; sys.exit(not ((3,10)<=sys.version_info[:2]<(4,0)))' 2>$null
            if ($LASTEXITCODE -eq 0) { return $Candidate }
        }
    }
    return $null
}

function Install-Python {
    $InstallerUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
    $Temporary = Join-Path ([IO.Path]::GetTempPath()) ('spirit-pet-python-' + [Guid]::NewGuid().ToString('N'))
    $Installer = Join-Path $Temporary 'python-installer.exe'
    $Target = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312'
    $null = New-Item -ItemType Directory -Path $Temporary
    try {
        Write-Host 'Downloading the official Python 3.12.10 installer from python.org...'
        Invoke-WebRequest -UseBasicParsing -Uri $InstallerUrl -OutFile $Installer
        $Signature = Get-AuthenticodeSignature -FilePath $Installer
        if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            throw 'The Python installer signature is invalid or is not from the Python Software Foundation.'
        }
        $Arguments = "/quiet InstallAllUsers=0 TargetDir=`"$Target`" PrependPath=0 Include_launcher=1 Include_pip=1 Include_test=0 Shortcuts=0"
        $Process = Start-Process -FilePath $Installer -ArgumentList $Arguments -Wait -PassThru
        if ($Process.ExitCode -notin @(0, 3010)) {
            throw "Python installation failed with exit code $($Process.ExitCode)."
        }
    } finally {
        Remove-Item -LiteralPath $Temporary -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$Python = Find-Python
if (-not $Python) {
    if ($Action -eq 'uninstall') {
        throw 'Uninstall requires an existing Python >=3.10 installation; no system packages were changed.'
    }
    if ($SkipSystem) {
        throw 'No usable Python was found and -SkipSystem was specified. Install Python >=3.10,<4.0, then rerun.'
    }
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        & winget install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) { $Python = Find-Python }
        else { Write-Host 'winget could not install Python; trying the signed python.org installer.' }
    }
    if (-not $Python) { Install-Python }
    $Python = Find-Python
    if (-not $Python) { throw 'Python installation completed but no usable Python was found.' }
}
$Arguments = @($Action, '--branch', $Branch, '--host', $ListenHost, '--port', "$Port")
if ($Directory) { $Arguments += @('--directory', $Directory) }
if ($Venv) { $Arguments += @('--venv', $Venv) }
if ($Yes) { $Arguments += '--yes' }
if ($NoStart) { $Arguments += '--no-start' }
$PreviousSkipSystem = $env:SPIRIT_PET_SKIP_SYSTEM
if ($SkipSystem) { $env:SPIRIT_PET_SKIP_SYSTEM = '1' }
$Bootstrap = Join-Path $PSScriptRoot 'install_bootstrap.py'
if (Test-Path -LiteralPath $Bootstrap -PathType Leaf) {
    try {
        & $Python $Bootstrap @Arguments
        exit $LASTEXITCODE
    } finally {
        $env:SPIRIT_PET_SKIP_SYSTEM = $PreviousSkipSystem
    }
}

$Temporary = Join-Path ([IO.Path]::GetTempPath()) ('spirit-pet-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $Temporary
try {
    $Sources = @('', 'https://gh-proxy.com/', 'https://gh.jasonzeng.dev/', 'https://git.yylx.win/', 'https://wget.la/')
    $Url = "https://raw.githubusercontent.com/liyw0205/nonebot_plugin_spirit_pet/$Branch/scripts/install_bootstrap.py"
    $Best = $null
    $BestTime = [double]::PositiveInfinity
    $Downloader = @'
import ast
from pathlib import Path
import sys
from urllib.request import HTTPRedirectHandler, Request, build_opener

class HTTPSOnlyRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        if not newurl.startswith("https://"):
            raise ValueError("insecure download redirect")
        return super().redirect_request(request, response, code, message, headers, newurl)

request = Request(sys.argv[1], headers={"User-Agent": "spirit-pet-installer/1"})
with build_opener(HTTPSOnlyRedirect()).open(request, timeout=15) as response:
    if response.status != 200:
        raise ValueError("unexpected HTTP status")
    payload = response.read(131073)
if len(payload) > 131072:
    raise ValueError("response exceeds size limit")
source = payload.decode("utf-8")
assert source.startswith("# spirit-pet-installer-bootstrap-v1\n")
ast.parse(source)
Path(sys.argv[2]).write_bytes(payload)
'@
    for ($Index = 0; $Index -lt $Sources.Count; $Index++) {
        $Name = $Sources[$Index]
        if (-not $Name) { $Name = 'GitHub' }
        $File = Join-Path $Temporary "bootstrap-$Index.py"
        $Watch = [Diagnostics.Stopwatch]::StartNew()
        try {
            $Downloader | & $Python - ($Sources[$Index] + $Url) $File
            if ($LASTEXITCODE -ne 0) { throw 'Invalid Python content, possibly an HTML error page' }
            $Watch.Stop()
            Write-Host "[$($Index+1)/5] ${Name}: OK $($Watch.ElapsedMilliseconds) ms, Python content validated"
            if ($Watch.Elapsed.TotalMilliseconds -lt $BestTime) {
                $BestTime = $Watch.Elapsed.TotalMilliseconds
                $Best = $File
            }
        } catch {
            Write-Host "[$($Index+1)/5] ${Name}: FAILED $($_.Exception.Message)"
        }
    }
    if (-not $Best) { throw 'All five sources failed. Check DNS/TLS/network or use a complete local checkout.' }
    Write-Host "Selected validated bootstrap: $([int]$BestTime) ms"
    & $Python $Best @Arguments
    $Code = $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath $Temporary -Recurse -Force
}
exit $Code
