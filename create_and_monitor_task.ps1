<#
.SYNOPSIS
    Login, create a task, and monitor progress with live worker logs.

.PARAMETER Instruction
    Task instruction sent to the planner.

.PARAMETER StartServices
    If set, starts all services before creating the task (same as start_all.ps1).

.EXAMPLE
    .\create_and_monitor_task.ps1
    .\create_and_monitor_task.ps1 -StartServices
#>
param(
    [string]$Email = "test@example.com",
    [string]$Password = "test12345",
    [string]$Instruction = "Write a comprehensive business plan for an AI-powered education platform",
    [switch]$StartServices,
    [int]$TimeoutMinutes = 30
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\platform-lib.ps1"

$services = @()

try {
  if ($StartServices) {
        $services = Start-PlatformServices
    } else {
        Write-PlatformMsg "system" "Assuming services are already running..." "Gray"
        Wait-PlatformReady -TimeoutSeconds 15
    }

    $token = Get-PlatformAuthToken -Email $Email -Password $Password
    $task  = New-PlatformTask -Token $token -Instruction $Instruction

    if ($services.Count -eq 0) {
        # Attach to existing log files if services were started earlier
        $services = @(
            @{ Name = "api"; OutLog = (Join-Path $LogsDir "api.log"); ErrLog = (Join-Path $LogsDir "api.err.log"); OutOffset = 0L; ErrOffset = 0L; Process = [PSCustomObject]@{ HasExited = $false } }
        )
        foreach ($w in $WorkerModules) {
            $services += [PSCustomObject]@{
                Name      = $w.Name
                OutLog    = (Join-Path $LogsDir "$($w.Name).log")
                ErrLog    = (Join-Path $LogsDir "$($w.Name).err.log")
                OutOffset = 0L
                ErrOffset = 0L
                Process   = [PSCustomObject]@{ HasExited = $false }
            }
        }
    }

    Monitor-PlatformTask -Token $token -TaskId $task.id -TimeoutMinutes $TimeoutMinutes -Services $services
} catch {
    Write-PlatformMsg "system" "ERROR: $($_.Exception.Message)" "Red"
    exit 1
}
