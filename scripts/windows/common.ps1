# Shared helpers for the KorGoz Windows scripts.
# Compatible with Windows PowerShell 5.1 (built into Windows 10/11) and PowerShell 7.
# Messages are ASCII-only so they render on any console code page.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is very slow with progress bars

$Root      = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$LocalDir  = Join-Path $Root '.local'          # everything installed by these scripts
$Downloads = Join-Path $LocalDir 'downloads'
$PgHome    = Join-Path $LocalDir 'pgsql'
$PgData    = Join-Path $LocalDir 'pgdata'
$PgLog     = Join-Path $LocalDir 'logs\postgres.log'
$QdrantDir = Join-Path $LocalDir 'qdrant'
$RunDir    = Join-Path $LocalDir 'run'
$LogDir    = Join-Path $LocalDir 'logs'
$VenvPy    = Join-Path $Root '.venv\Scripts\python.exe'
$EnvFile   = Join-Path $Root '.env'

# Pinned versions (checked to exist on 2026-10-07).
$PgVersion      = '18.6-1'
$PgPort         = 55432          # not 5432, so an existing PostgreSQL is not disturbed
$PgUser         = 'korgoz'
$QdrantVersion  = 'v1.19.2'
$QdrantSha256   = '7d86596f16c6e85d45a50312f5e16ccb51e059b62e3d7308110cb65b4c799a4d'
$PythonVersion  = '3.12.10'

function Invoke-Quiet([string]$Exe, [string[]]$Arguments) {
    # Runs a native command with all output discarded and returns its exit code.
    # (In Windows PowerShell 5.1 redirected stderr + ErrorActionPreference=Stop would throw.)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Exe @Arguments *> $null } finally { $ErrorActionPreference = $previous }
    return $LASTEXITCODE
}

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message)   { Write-Host "    OK  $Message" -ForegroundColor Green }
function Write-Note([string]$Message) { Write-Host "    $Message" -ForegroundColor Yellow }

function Fail([string]$Message) {
    Write-Host ''
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Ensure-Dir([string]$Path) {
    if (-not (Test-Path $Path)) { New-Item -ItemType Directory -Path $Path | Out-Null }
}

function Set-Proxy([string]$Proxy) {
    # pip, httpx (model downloads) and curl.exe all honour these variables.
    if ($Proxy) {
        $env:HTTPS_PROXY = $Proxy
        $env:HTTP_PROXY = $Proxy
        Write-Note "Using proxy $Proxy"
    }
}

function Get-File([string]$Url, [string]$Destination, [string]$Sha256 = '') {
    # Resumable download via curl.exe (bundled with Windows 10 1803+), optional SHA-256 check.
    Ensure-Dir (Split-Path $Destination)
    if (Test-Path $Destination) {
        # Completed downloads are renamed from .part, so an existing file is complete.
        if (-not $Sha256 -or (Get-FileHash $Destination -Algorithm SHA256).Hash.ToLower() -eq $Sha256) {
            Write-Ok "$(Split-Path $Destination -Leaf) already downloaded"
            return
        }
    }
    $partial = "$Destination.part"
    Write-Note "Downloading $(Split-Path $Destination -Leaf) ..."
    $curlArgs = @('-L', '--fail', '--retry', '10', '--retry-all-errors', '--retry-delay', '3',
                  '-C', '-', '-o', $partial, $Url)
    & curl.exe @curlArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "Download failed: $Url (curl exit $LASTEXITCODE). Check the internet/VPN or pass -Proxy http://host:port and run again; the download resumes."
    }
    if ($Sha256) {
        $actual = (Get-FileHash $partial -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $Sha256) {
            Remove-Item $partial -Force
            Fail "Checksum mismatch for $Url (got $actual)"
        }
    }
    Move-Item $partial $Destination -Force
    Write-Ok "$(Split-Path $Destination -Leaf) downloaded"
}

function Read-DotEnv {
    $values = @{}
    if (Test-Path $EnvFile) {
        foreach ($line in Get-Content $EnvFile) {
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $values[$Matches[1]] = $Matches[2] }
        }
    }
    return $values
}

function Set-DotEnvValue([string]$Key, [string]$Value) {
    # Writes UTF-8 *without* BOM (Windows PowerShell 5.1 Set-Content would add one).
    $lines = @()
    if (Test-Path $EnvFile) { $lines = @(Get-Content $EnvFile) }
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*#?\s*$Key\s*=") { $lines[$i] = "$Key=$Value"; $found = $true; break }
    }
    if (-not $found) { $lines += "$Key=$Value" }
    [System.IO.File]::WriteAllLines($EnvFile, [string[]]$lines, (New-Object System.Text.UTF8Encoding $false))
}

function Test-LocalPostgres { return (Test-Path (Join-Path $PgHome 'bin\pg_ctl.exe')) -and (Test-Path $PgData) }

function Start-LocalPostgres {
    $pgCtl = Join-Path $PgHome 'bin\pg_ctl.exe'
    if ((Invoke-Quiet $pgCtl @('status', '-D', $PgData)) -eq 0) {
        Write-Ok "PostgreSQL already running on port $PgPort"
        return
    }
    Ensure-Dir $LogDir
    & $pgCtl start -D $PgData -l $PgLog -w -t 60 -o "-p $PgPort -c listen_addresses=127.0.0.1" | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "PostgreSQL did not start, see $PgLog" }
    Write-Ok "PostgreSQL started on 127.0.0.1:$PgPort"
}

function Stop-LocalPostgres {
    $pgCtl = Join-Path $PgHome 'bin\pg_ctl.exe'
    if (-not (Test-Path $pgCtl)) { return }
    if ((Invoke-Quiet $pgCtl @('status', '-D', $PgData)) -eq 0) {
        Invoke-Quiet $pgCtl @('stop', '-D', $PgData, '-m', 'fast', '-w') | Out-Null
        Write-Ok 'PostgreSQL stopped'
    }
}

function Save-Pid([string]$Name, [int]$ProcessId) {
    Ensure-Dir $RunDir
    Set-Content -Path (Join-Path $RunDir "$Name.pid") -Value $ProcessId
}

function Stop-Saved([string]$Name) {
    $file = Join-Path $RunDir "$Name.pid"
    if (-not (Test-Path $file)) { return }
    $processId = [int](Get-Content $file)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        # /T also stops child processes (uvicorn --reload spawns one).
        Invoke-Quiet 'taskkill.exe' @('/PID', "$processId", '/T', '/F') | Out-Null
        Write-Ok "$Name stopped (pid $processId)"
    }
    Remove-Item $file -Force
}

function Wait-Http([string]$Url, [int]$Seconds = 60) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -lt 500) { return $true }
        } catch {
            # Health returns 503 while the database is unavailable; keep waiting.
            if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -lt 500) { return $true }
        }
        Start-Sleep -Milliseconds 700
    }
    return $false
}
