<#
.SYNOPSIS
    ONE COMMAND: start everything, create a test task, stream logs, show final output.

.EXAMPLE
    .\run-all.ps1

    Press Ctrl+C to stop viewing logs. Services keep running.
    To stop all services: .\start_all.ps1 -Stop
#>
param(
    [string]$Email = "test@example.com",
    [string]$Password = "test12345",
    [string]$Instruction = "Write a comprehensive business plan for an AI-powered education platform",
    [int]$TimeoutMinutes = 30
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\platform-lib.ps1"

Write-Host ""
Write-Host "################################################################" -ForegroundColor Cyan
Write-Host "#  MULTI-AGENT PLATFORM - FULL RUN (start + task + monitor)      #" -ForegroundColor Cyan
Write-Host "################################################################" -ForegroundColor Cyan
Write-Host ""

try {
    # Step 1: Start all services
    Write-PlatformMsg "system" "STEP 1/3 - Starting Redis, API, and 6 workers..." "Cyan"
    $services = Start-PlatformServices

    # Step 2: Create task
    Write-Host ""
    Write-PlatformMsg "system" "STEP 2/3 - Authenticating and creating task..." "Cyan"
    $token = Get-PlatformAuthToken -Email $Email -Password $Password
    $task  = New-PlatformTask -Token $token -Instruction $Instruction

    # Step 3: Monitor with live logs
    Write-Host ""
    Write-PlatformMsg "system" "STEP 3/3 - Streaming worker logs + task progress..." "Cyan"
    Write-PlatformMsg "system" "Watch for [planner] -> [research/content/email/analytics] -> [aggregator]" "Gray"
    Write-Host ""

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $lastStatus = ""
    $terminal = @("COMPLETED", "FAILED", "FALLBACK")
    $finished = $false

    while (-not $finished -and (Get-Date) -lt $deadline) {
        foreach ($svc in $services) {
            if ($svc.Process.HasExited) {
                Write-PlatformMsg $svc.Name "PROCESS EXITED (code $($svc.Process.ExitCode))" "Red"
            }
            Read-NewLogLines -Service $svc
        }

        try {
            $data = Get-PlatformTaskStatus -Token $token -TaskId $task.id
            $lastStatus = Show-TaskProgress -Task $data.Task -Dag $data.Dag -LastStatus $lastStatus

            if ($lastStatus -in $terminal) {
                $finished = $true
                Write-Host ""
                Write-Host "################################################################" -ForegroundColor Green
                Write-PlatformMsg "task" "DONE - Final status: $lastStatus" "Green"
                Write-Host "################################################################" -ForegroundColor Green

                if ($data.Task.final_output) {
                    Write-Host ""
                    Write-Host "==================== FINAL OUTPUT ====================" -ForegroundColor Cyan
                    if ($data.Task.final_output.sections) {
                        foreach ($key in $data.Task.final_output.sections.PSObject.Properties.Name) {
                            Write-Host ""
                            Write-Host "--- $key ---" -ForegroundColor Yellow
                            $val = $data.Task.final_output.sections.$key
                            if ($val -is [string]) {
                                Write-Host $val.Substring(0, [Math]::Min(2000, $val.Length))
                            } else {
                                Write-Host ($val | ConvertTo-Json -Depth 5)
                            }
                        }
                    } else {
                        Write-Host ($data.Task.final_output | ConvertTo-Json -Depth 8)
                    }
                    Write-Host ""
                    Write-Host "=======================================================" -ForegroundColor Cyan
                }
            }
        } catch {
            Write-PlatformMsg "task" "Poll error: $($_.Exception.Message)" "Red"
        }

        Start-Sleep -Milliseconds 500
    }

    if (-not $finished) {
        throw "Task did not complete within $TimeoutMinutes minutes. Check logs in: $LogsDir"
    }

    Write-Host ""
    Write-PlatformMsg "system" "Services still running. API: http://127.0.0.1:8000/docs" "Green"
    Write-PlatformMsg "system" "Stop services: .\start_all.ps1 -Stop" "Gray"
    Write-Host ""

} catch {
    Write-Host ""
    Write-PlatformMsg "system" "FAILED: $($_.Exception.Message)" "Red"
    Write-PlatformMsg "system" "Check logs in: $LogsDir" "Yellow"
    exit 1
}
