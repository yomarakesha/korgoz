<#
.SYNOPSIS
    Starts KorGoz on Windows: PostgreSQL, Qdrant, API and camera worker, then opens live view.

.EXAMPLE
    .\scripts\windows\start.ps1                       # laptop webcam
    .\scripts\windows\start.ps1 -Camera demo          # sample video with pedestrians
    .\scripts\windows\start.ps1 -Camera "rtsp://user:pass@192.168.1.10:554/stream1"
    .\scripts\windows\start.ps1 -Camera "C:\videos\hall.mp4"
    .\scripts\windows\start.ps1 -Camera none          # keep cameras already in the database
#>
param(
    [string]$Camera = 'webcam',
    [ValidateSet('anonymous', 'recognition')]
    [string]$Mode = 'anonymous',
    [switch]$NoQdrant,
    [switch]$NoBrowser
)

. (Join-Path $PSScriptRoot 'common.ps1')
Set-Location $Root

if (-not (Test-Path $VenvPy) -or -not (Test-Path $EnvFile)) {
    Fail 'Not installed yet. Run scripts\windows\setup.bat first.'
}
foreach ($name in 'api', 'worker') {
    $file = Join-Path $RunDir "$name.pid"
    if ((Test-Path $file) -and (Get-Process -Id ([int](Get-Content $file)) -ErrorAction SilentlyContinue)) {
        Fail 'KorGoz is already running. Run scripts\windows\stop.bat first.'
    }
}
Ensure-Dir $LogDir
$env:VISION_MODE = $Mode   # environment variables override .env

# ---------------------------------------------------------------- PostgreSQL
Write-Step 'PostgreSQL'
if (Test-LocalPostgres) {
    Start-LocalPostgres
} else {
    Write-Note 'No local PostgreSQL in .local; using DATABASE_URL from .env as is.'
}

# ---------------------------------------------------------------- Qdrant
$qdrantExe = Join-Path $QdrantDir 'qdrant.exe'
if (-not $NoQdrant -and (Test-Path $qdrantExe)) {
    Write-Step 'Qdrant'
    $env:QDRANT__STORAGE__STORAGE_PATH = Join-Path $QdrantDir 'storage'
    $env:QDRANT__SERVICE__HOST = '127.0.0.1'
    $env:QDRANT__TELEMETRY_DISABLED = 'true'      # local-first: no usage telemetry
    $qdrant = Start-Process $qdrantExe -WorkingDirectory $QdrantDir -PassThru `
        -RedirectStandardOutput (Join-Path $LogDir 'qdrant.log') -RedirectStandardError (Join-Path $LogDir 'qdrant.err.log')
    Save-Pid 'qdrant' $qdrant.Id
    if (Wait-Http 'http://127.0.0.1:6333/healthz' 30) { Write-Ok 'Qdrant on 127.0.0.1:6333' }
    else { Write-Note "Qdrant did not answer, see $LogDir\qdrant.err.log (only needed for recognition)" }
}

# ---------------------------------------------------------------- API
Write-Step 'API (new window "uvicorn")'
$api = Start-Process $VenvPy -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000' `
    -WorkingDirectory $Root -PassThru
Save-Pid 'api' $api.Id
if (-not (Wait-Http 'http://127.0.0.1:8000/health' 60)) { Fail 'API did not start; look at its window for the error.' }
Write-Ok 'API on http://127.0.0.1:8000'

# ---------------------------------------------------------------- camera
$cameraId = $null
if ($Camera -ne 'none') {
    Write-Step 'Camera'
    switch ($Camera) {
        'webcam' { $source = '0'; $cameraName = 'Webcam' }
        'demo'   { $source = 'data/samples/vtest.avi'; $cameraName = 'Demo video' }
        default  { $source = $Camera; $cameraName = 'Camera' }
    }
    if ($Camera -eq 'demo' -and -not (Test-Path (Join-Path $Root 'data\samples\vtest.avi'))) {
        Fail 'Sample video missing: run  .venv\Scripts\python -m scripts.download_models --samples'
    }
    $existing = @(Invoke-RestMethod 'http://127.0.0.1:8000/cameras') | Where-Object { $_.name -eq $cameraName }
    if ($existing) {
        $cameraId = $existing[0].id
        Write-Ok "using existing camera #$cameraId ($cameraName)"
    } else {
        $body = @{ name = $cameraName; stream_url = $source } | ConvertTo-Json
        $created = Invoke-RestMethod 'http://127.0.0.1:8000/cameras' -Method Post -ContentType 'application/json' -Body $body
        $cameraId = $created.id
        Write-Ok "camera #$cameraId added ($cameraName, $($created.source_kind))"
    }
}

# ---------------------------------------------------------------- worker
# Started after the camera is added: the worker reads the camera list at start-up.
Write-Step 'Camera worker (new window "python -m app.worker")'
$worker = Start-Process $VenvPy -ArgumentList '-m', 'app.worker' -WorkingDirectory $Root -PassThru
Save-Pid 'worker' $worker.Id
Write-Ok "worker started (mode: $Mode)"

if ($cameraId) {
    $snapshot = "http://127.0.0.1:8000/cameras/$cameraId/snapshot"
    if (Wait-Http $snapshot 45) {
        Write-Ok 'frames are coming in'
    } else {
        Write-Note 'No frames yet. Check the worker window (camera busy? wrong URL?).'
    }
}

Write-Host ''
Write-Host 'KorGoz is running.' -ForegroundColor Green
if (Test-Path (Join-Path $Root 'frontend\dist\index.html')) { Write-Host '  Dashboard : http://127.0.0.1:8000/ui/' }
if ($cameraId) { Write-Host "  Live view : http://127.0.0.1:8000/cameras/$cameraId/stream" }
Write-Host '  API docs  : http://127.0.0.1:8000/docs'
Write-Host '  Health    : http://127.0.0.1:8000/health'
Write-Host '  Tracks    : http://127.0.0.1:8000/tracks?active=true'
Write-Host '  Stop      : scripts\windows\stop.bat'

if ($cameraId -and -not $NoBrowser) { Start-Process "http://127.0.0.1:8000/cameras/$cameraId/stream" }
