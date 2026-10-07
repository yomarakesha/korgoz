<#
.SYNOPSIS
    Stops everything started by start.ps1 (worker, API, Qdrant, local PostgreSQL).

.NOTES
    The worker is terminated, not asked to shut down, so open tracks are closed on its
    next start. For a graceful stop press Ctrl+C in the worker window first.
#>
. (Join-Path $PSScriptRoot 'common.ps1')

Write-Step 'Stopping KorGoz'
Stop-Saved 'worker'
Stop-Saved 'api'
Stop-Saved 'qdrant'
if (Test-LocalPostgres) { Stop-LocalPostgres }
Write-Host 'Stopped.' -ForegroundColor Green
