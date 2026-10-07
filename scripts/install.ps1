[CmdletBinding()]
param(
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

$Python = Find-Python
if (-not $Python) {
    if ($SkipSystem -or -not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Install Python >=3.10,<4.0 from python.org, reopen PowerShell, then rerun.'
    }
    & winget install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Python installation failed. No project files were changed.' }
    $Python = Find-Python
    if (-not $Python) { throw 'Python installed but not found. Reopen PowerShell and rerun.' }
}
$Arguments = @('--branch', $Branch, '--host', $ListenHost, '--port', "$Port")
if ($Directory) { $Arguments += @('--directory', $Directory) }
if ($Venv) { $Arguments += @('--venv', $Venv) }
if ($Yes) { $Arguments += '--yes' }
if ($NoStart) { $Arguments += '--no-start' }
$Bootstrap = Join-Path $PSScriptRoot 'install_bootstrap.py'
if (Test-Path -LiteralPath $Bootstrap -PathType Leaf) {
    & $Python $Bootstrap @Arguments
    exit $LASTEXITCODE
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
