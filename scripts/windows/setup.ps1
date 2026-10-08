<#
.SYNOPSIS
    One-time installation of KorGoz on Windows: Python, packages, PostgreSQL, Qdrant, models,
    dashboard.

.DESCRIPTION
    Everything goes into the project folder (.venv and .local); no admin rights, no
    system services, no Docker. Safe to re-run: finished steps are skipped and
    interrupted downloads resume.

.EXAMPLE
    .\scripts\windows\setup.ps1
    .\scripts\windows\setup.ps1 -Proxy http://127.0.0.1:10809
    .\scripts\windows\setup.ps1 -SkipPostgres      # use your own PostgreSQL (set DATABASE_URL in .env)
#>
param(
    [string]$Proxy = '',
    [switch]$SkipPostgres,
    [switch]$SkipQdrant,
    [switch]$NoSamples,
    [switch]$SkipDashboard
)

. (Join-Path $PSScriptRoot 'common.ps1')
Set-Location $Root
Set-Proxy $Proxy
Ensure-Dir $LocalDir

# ---------------------------------------------------------------- Python 3.12
Write-Step 'Python 3.12'

function Find-Python312 {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { $candidates += (& py -3.12 -c 'import sys; print(sys.executable)' 2>$null) } catch { }
        $ErrorActionPreference = $previous
    }
    $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
    $candidates += 'C:\Program Files\Python312\python.exe'
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            $version = & $candidate -c 'import sys; print("%d.%d" % sys.version_info[:2])'
            if ($version -eq '3.12') { return $candidate }
        }
    }
    return $null
}

$python = Find-Python312
if (-not $python) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Note 'Installing Python 3.12 with winget (per-user) ...'
        & winget install --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
        $python = Find-Python312
    }
}
if (-not $python) {
    Write-Note "Installing Python $PythonVersion from python.org (per-user) ..."
    $installer = Join-Path $Downloads "python-$PythonVersion-amd64.exe"
    Get-File "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe" $installer
    $process = Start-Process $installer -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_launcher=1', 'Include_test=0' -Wait -PassThru
    if ($process.ExitCode -ne 0) { Fail "Python installer exited with $($process.ExitCode)" }
    $python = Find-Python312
}
if (-not $python) { Fail 'Python 3.12 not found. Install it from https://www.python.org/downloads/ and re-run.' }
Write-Ok $python

# ---------------------------------------------------------------- venv + packages
Write-Step 'Virtual environment and Python packages'
if (-not (Test-Path $VenvPy)) {
    & $python -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { Fail 'Cannot create .venv' }
}
& $VenvPy -m pip install --upgrade pip --quiet --retries 10
& $VenvPy -m pip install -r (Join-Path $Root 'requirements-dev.txt') --quiet --retries 10
if ($LASTEXITCODE -ne 0) { Fail 'pip install failed (network?). Re-run, optionally with -Proxy.' }
Write-Ok 'packages installed'

# ---------------------------------------------------------------- .env
Write-Step 'Configuration (.env)'
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Root '.env.example') $EnvFile
    Write-Ok '.env created from .env.example'
} else {
    Write-Ok '.env exists, keeping your values'
}

# ---------------------------------------------------------------- PostgreSQL (portable)
if (-not $SkipPostgres) {
    Write-Step "PostgreSQL $PgVersion (portable, inside .local)"
    if (-not (Test-Path (Join-Path $PgHome 'bin\pg_ctl.exe'))) {
        $zip = Join-Path $Downloads "postgresql-$PgVersion-windows-x64-binaries.zip"
        Write-Note 'The archive is about 340 MB (it also contains pgAdmin).'
        Get-File "https://get.enterprisedb.com/postgresql/postgresql-$PgVersion-windows-x64-binaries.zip" $zip
        Write-Note 'Extracting ...'
        & tar.exe -xf $zip -C $LocalDir      # bsdtar ships with Windows 10+, much faster than Expand-Archive
        if ($LASTEXITCODE -ne 0) { Fail 'Cannot extract the PostgreSQL archive' }
    }
    Write-Ok "binaries in $PgHome"

    if (-not (Test-Path $PgData)) {
        $password = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
        $pwFile = Join-Path $LocalDir 'pw.tmp'
        [System.IO.File]::WriteAllText($pwFile, $password)
        & (Join-Path $PgHome 'bin\initdb.exe') -D $PgData -U $PgUser --pwfile=$pwFile -A scram-sha-256 -E UTF8 --no-locale | Out-Null
        $initdbExit = $LASTEXITCODE
        Remove-Item $pwFile -Force
        if ($initdbExit -ne 0) { Fail 'initdb failed' }
        Set-DotEnvValue 'DATABASE_URL' "postgresql+psycopg://${PgUser}:$password@127.0.0.1:$PgPort/korgoz"
        Write-Ok 'cluster initialised, random password written to .env (DATABASE_URL)'

        Start-LocalPostgres
        $env:PGPASSWORD = $password
        & (Join-Path $PgHome 'bin\createdb.exe') -h 127.0.0.1 -p $PgPort -U $PgUser korgoz
        if ($LASTEXITCODE -ne 0) { Fail 'createdb failed' }
        Remove-Item Env:\PGPASSWORD
        Write-Ok 'database "korgoz" created'
    } else {
        Start-LocalPostgres
    }
} else {
    Write-Step 'PostgreSQL: skipped (-SkipPostgres), DATABASE_URL in .env must point to your server'
}

# ---------------------------------------------------------------- migrations
Write-Step 'Database tables (alembic upgrade head)'
& $VenvPy -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { Fail 'Migrations failed: is PostgreSQL running and DATABASE_URL in .env correct?' }
Write-Ok 'schema up to date'

# ---------------------------------------------------------------- AI models
Write-Step 'AI models (YOLOX, YuNet) and sample media'
$modelArgs = @('-m', 'scripts.download_models')
if (-not $NoSamples) { $modelArgs += '--samples' }
& $VenvPy @modelArgs
if ($LASTEXITCODE -ne 0) { Fail 'Model download failed. Re-run (optionally with -Proxy); finished files are kept.' }

# ---------------------------------------------------------------- Qdrant
if (-not $SkipQdrant) {
    Write-Step "Qdrant $QdrantVersion"
    if (-not (Test-Path (Join-Path $QdrantDir 'qdrant.exe'))) {
        $zip = Join-Path $Downloads "qdrant-$QdrantVersion-windows.zip"
        Get-File "https://github.com/qdrant/qdrant/releases/download/$QdrantVersion/qdrant-x86_64-pc-windows-msvc.zip" $zip $QdrantSha256
        Ensure-Dir $QdrantDir
        & tar.exe -xf $zip -C $QdrantDir
        if ($LASTEXITCODE -ne 0) { Fail 'Cannot extract Qdrant' }
        if (-not (Test-Path (Join-Path $QdrantDir 'qdrant.exe'))) {
            $found = Get-ChildItem $QdrantDir -Recurse -Filter 'qdrant.exe' | Select-Object -First 1
            if (-not $found) { Fail 'qdrant.exe not found in the archive' }
            Move-Item $found.FullName (Join-Path $QdrantDir 'qdrant.exe')
        }
    }
    Ensure-Dir (Join-Path $QdrantDir 'storage')
    Write-Ok (Join-Path $QdrantDir 'qdrant.exe')
}

# ---------------------------------------------------------------- dashboard
if (-not $SkipDashboard) {
    Write-Step 'Dashboard (React, built once with Node.js)'
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) {
        Write-Note 'Node.js not found: dashboard skipped. Install Node.js 22 LTS and re-run setup.'
    } else {
        Push-Location (Join-Path $Root 'frontend')
        try {
            & $npm.Source ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { Fail 'npm ci failed (network? try -Proxy)' }
            & $npm.Source run build
            if ($LASTEXITCODE -ne 0) { Fail 'Dashboard build failed' }
        } finally {
            Pop-Location
        }
        Write-Ok 'frontend\dist (served by the API at http://127.0.0.1:8000/ui/)'
    }
}

if (-not $SkipPostgres) { Stop-LocalPostgres }

Write-Host ''
Write-Host 'Setup complete.' -ForegroundColor Green
Write-Host 'Next:  scripts\windows\start.bat            (webcam)'
Write-Host '       scripts\windows\start.bat -Camera demo   (sample video, no camera needed)'
