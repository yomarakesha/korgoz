<#
.SYNOPSIS
    Runs the KorGoz test suite on Windows.

.EXAMPLE
    .\scripts\windows\test.ps1          # unit tests (no camera, no services needed)
    .\scripts\windows\test.ps1 -All     # + AI model tests, PostgreSQL integration tests, ruff/black/mypy
#>
param([switch]$All)

. (Join-Path $PSScriptRoot 'common.ps1')
Set-Location $Root
if (-not (Test-Path $VenvPy)) { Fail 'Not installed yet. Run scripts\windows\setup.bat first.' }

$failed = @()

Write-Step 'Unit tests'
& $VenvPy -m pytest -q
if ($LASTEXITCODE -ne 0) { $failed += 'unit' }

if ($All) {
    Write-Step 'AI model tests (real YOLOX / YuNet)'
    & $VenvPy -m pytest -q -m ai
    if ($LASTEXITCODE -ne 0) { $failed += 'ai' }

    if (Test-LocalPostgres) {
        Write-Step 'Integration tests (local PostgreSQL, database korgoz_test)'
        Start-LocalPostgres
        $databaseUrl = (Read-DotEnv)['DATABASE_URL']
        $testUrl = $databaseUrl -replace '/korgoz$', '/korgoz_test'
        if ($testUrl -eq $databaseUrl) {
            Write-Note 'DATABASE_URL does not end with /korgoz, skipping integration tests'
        } else {
            $env:PGPASSWORD = ([uri]($databaseUrl -replace '^postgresql\+psycopg', 'http')).UserInfo.Split(':')[1]
            Invoke-Quiet (Join-Path $PgHome 'bin\createdb.exe') @('-h', '127.0.0.1', '-p', "$PgPort", '-U', $PgUser, 'korgoz_test') | Out-Null
            Remove-Item Env:\PGPASSWORD
            $env:TEST_DATABASE_URL = $testUrl
            & $VenvPy -m pytest -q -m integration
            if ($LASTEXITCODE -ne 0) { $failed += 'integration' }
            Remove-Item Env:\TEST_DATABASE_URL
        }
    } else {
        Write-Note 'No local PostgreSQL (.local), integration tests skipped'
    }

    Write-Step 'Code quality: ruff, black, mypy'
    & $VenvPy -m ruff check .
    if ($LASTEXITCODE -ne 0) { $failed += 'ruff' }
    & $VenvPy -m black --check -q .
    if ($LASTEXITCODE -ne 0) { $failed += 'black' }
    & $VenvPy -m mypy app tests scripts
    if ($LASTEXITCODE -ne 0) { $failed += 'mypy' }
}

Write-Host ''
if ($failed.Count -gt 0) {
    Write-Host "FAILED: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host 'All checks passed.' -ForegroundColor Green
