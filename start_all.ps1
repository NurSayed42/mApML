<#
.SYNOPSIS
    Start Redis, API (port 8000), and all 6 workers with unified log streaming.

.DESCRIPTION
    Services run as background processes. Logs stream in THIS terminal with tags:
    [api], [planner], [research], [content], [email], [analytics], [aggregator]

    Press Ctrl+C to stop viewing logs (services keep running).
    Run again with -Stop to shut down all services.

.EXAMPLE
    .\start_all.ps1
    .\start_all.ps1 -Stop
#>
param(
    [switch]$Stop,
    [switch]$SkipRedis,
    [switch]$NoLogs
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\platform-lib.ps1"

if ($Stop) {
    Stop-PlatformServices
    Write-PlatformMsg "system" "All services stopped." "Green"
    exit 0
}

try {
    $services = Start-PlatformServices -SkipRedis:$SkipRedis

    if ($NoLogs) {
        Write-PlatformMsg "system" "Services running in background. Logs: $LogsDir" "Green"
        exit 0
    }

    Watch-PlatformLogs -Services $services
} catch {
    Write-PlatformMsg "system" "ERROR: $($_.Exception.Message)" "Red"
    exit 1
}
