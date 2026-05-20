# Shared helpers for Multi-Agent Platform PowerShell scripts
$ErrorActionPreference = "Stop"

$script:PlatformRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$script:BackendDir   = Join-Path $PlatformRoot "backend"
$script:LogsDir      = Join-Path $PlatformRoot "logs"
$script:PidsFile     = Join-Path $LogsDir "service-pids.txt"
$script:ApiBase      = "http://127.0.0.1:8000/api/v1"
$script:PythonExe    = Join-Path $BackendDir "venv\Scripts\python.exe"
$script:UvicornExe   = Join-Path $BackendDir "venv\Scripts\uvicorn.exe"

$script:WorkerModules = @(
    @{ Name = "planner";    Module = "workers.planner_worker" }
    @{ Name = "research";   Module = "workers.research_worker" }
    @{ Name = "content";    Module = "workers.content_worker" }
    @{ Name = "email";      Module = "workers.email_worker" }
    @{ Name = "analytics";  Module = "workers.analytics_worker" }
    @{ Name = "aggregator"; Module = "workers.aggregator_worker" }
)

$script:LogColors = @{
    "api"        = "Cyan"
    "redis"      = "DarkGray"
    "planner"    = "Yellow"
    "research"   = "Green"
    "content"    = "Blue"
    "email"      = "Magenta"
    "analytics"  = "DarkCyan"
    "aggregator" = "DarkYellow"
    "task"       = "White"
    "system"     = "Gray"
}

function Write-PlatformMsg {
    param(
        [string]$Tag,
        [string]$Message,
        [string]$Color = "White"
    )
    $ts = Get-Date -Format "HH:mm:ss"
    $tagPadded = $Tag.PadRight(10)
    Write-Host "[$ts] " -NoNewline -ForegroundColor DarkGray
    Write-Host "[$tagPadded] " -NoNewline -ForegroundColor $Color
    Write-Host $Message
}

function Test-PlatformPrereqs {
    if (-not (Test-Path $PythonExe)) {
        throw "Python venv not found at: $PythonExe`nRun: cd backend; python -m venv venv; .\venv\Scripts\pip install -r requirements.txt"
    }
    if (-not (Test-Path (Join-Path $BackendDir ".env"))) {
        throw ".env file missing in backend/. Copy .env.example and configure API keys."
    }
    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
}

function Test-RedisAvailable {
    $redisCli = Get-Command redis-cli -ErrorAction SilentlyContinue
    if ($redisCli) {
        try {
            $pong = & redis-cli ping 2>$null
            if ($pong -eq "PONG") { return $true }
        } catch {}
    }
    return $false
}

function Start-RedisService {
    Write-PlatformMsg "redis" "Checking Redis..." "DarkGray"

    if (Test-RedisAvailable) {
        Write-PlatformMsg "redis" "Redis is already running (PONG)" "Green"
        return $true
    }

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-PlatformMsg "redis" "Redis not running and Docker not found. Start Redis manually." "Red"
        return $false
    }

    Write-PlatformMsg "redis" "Starting Redis + Chroma via Docker Compose..." "Yellow"
    Push-Location $PlatformRoot
    try {
        docker compose up -d redis chroma 2>&1 | ForEach-Object { Write-PlatformMsg "redis" $_ "DarkGray" }
    } finally {
        Pop-Location
    }

    $maxWait = 30
    for ($i = 0; $i -lt $maxWait; $i++) {
        Start-Sleep -Seconds 1
        if (Test-RedisAvailable) {
            Write-PlatformMsg "redis" "Redis is ready" "Green"
            return $true
        }
    }

    Write-PlatformMsg "redis" "Redis did not become ready in ${maxWait}s" "Red"
    return $false
}

function Start-LoggedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory
    )

    $outLog = Join-Path $LogsDir "$Name.log"
    $errLog = Join-Path $LogsDir "$Name.err.log"
    "" | Set-Content $outLog -Encoding UTF8
    "" | Set-Content $errLog -Encoding UTF8

    $proc = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog

    Start-Sleep -Milliseconds 300

    if ($proc.HasExited) {
        $err = Get-Content $errLog -Raw -ErrorAction SilentlyContinue
        $out = Get-Content $outLog -Raw -ErrorAction SilentlyContinue
        throw "Process '$Name' exited immediately (code $($proc.ExitCode)).`nSTDERR: $err`nSTDOUT: $out"
    }

    return [PSCustomObject]@{
        Name      = $Name
        Process   = $proc
        OutLog    = $outLog
        ErrLog    = $errLog
        OutOffset = 0L
        ErrOffset = 0L
    }
}

function Stop-PlatformServices {
    Write-PlatformMsg "system" "Stopping platform services..." "Yellow"

    if (Test-Path $PidsFile) {
        Get-Content $PidsFile | ForEach-Object {
            if ($_ -match '^\d+$') {
                Stop-Process -Id ([int]$_) -Force -ErrorAction SilentlyContinue
            }
        }
        Remove-Item $PidsFile -Force -ErrorAction SilentlyContinue
    }

    Get-Process -Name "python","uvicorn" -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($BackendDir) } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

function Start-PlatformServices {
    param(
        [switch]$SkipRedis
    )

    Test-PlatformPrereqs
    Stop-PlatformServices
    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "  Multi-Agent Platform - Starting Services" -ForegroundColor Cyan
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""

    if (-not $SkipRedis) {
        $redisOk = Start-RedisService
        if (-not $redisOk) {
            throw "Cannot start without Redis. Fix Redis or run: docker compose up -d redis"
        }
    }

    $services = @()

    Write-PlatformMsg "api" "Starting API on http://127.0.0.1:8000 ..." "Cyan"
    $api = Start-LoggedProcess `
        -Name "api" `
        -FilePath $UvicornExe `
        -ArgumentList @("main:app", "--host", "127.0.0.1", "--port", "8000", "--reload") `
        -WorkingDirectory $BackendDir
    $services += $api

    foreach ($w in $WorkerModules) {
        Write-PlatformMsg $w.Name "Starting worker..." ($script:LogColors[$w.Name])
        $svc = Start-LoggedProcess `
            -Name $w.Name `
            -FilePath $PythonExe `
            -ArgumentList @("-m", $w.Module) `
            -WorkingDirectory $BackendDir
        $services += $svc
    }

    @($services | ForEach-Object { $_.Process.Id }) | Set-Content $PidsFile -Encoding ASCII

    Write-Host ""
    Write-PlatformMsg "system" "All processes launched. Waiting for API health..." "Gray"
    Wait-PlatformReady -TimeoutSeconds 90

    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host "  All services started successfully" -ForegroundColor Green
    Write-Host "  API docs: http://127.0.0.1:8000/docs" -ForegroundColor Green
    Write-Host "  Logs dir: $LogsDir" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host ""

    return $services
}

function Wait-PlatformReady {
    param([int]$TimeoutSeconds = 60)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri "$ApiBase/health" -Method Get -TimeoutSec 5
            if ($health.status -eq "ok" -and $health.services.redis -eq "ok") {
                Write-PlatformMsg "api" "Health OK (postgres=$($health.services.postgres), redis=$($health.services.redis))" "Green"
                return $true
            }
            Write-PlatformMsg "api" "Health degraded: $($health | ConvertTo-Json -Compress)" "Yellow"
        } catch {
            Write-PlatformMsg "api" "Waiting for API... ($($_.Exception.Message))" "DarkGray"
        }
        Start-Sleep -Seconds 2
    }
    throw "Platform not ready within ${TimeoutSeconds}s. Check logs\api.err.log"
}

function Read-NewLogLines {
    param([PSCustomObject]$Service)

    foreach ($kind in @("Out", "Err")) {
        $path = if ($kind -eq "Out") { $Service.OutLog } else { $Service.ErrLog }
        $offsetProp = if ($kind -eq "Out") { "OutOffset" } else { "ErrOffset" }

        if (-not (Test-Path $path)) { continue }

        $fs = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            $fs.Seek($Service.$offsetProp, [System.IO.SeekOrigin]::Begin) | Out-Null
            $reader = New-Object System.IO.StreamReader($fs)
            while (-not $reader.EndOfStream) {
                $line = $reader.ReadLine()
                if ($null -eq $line) { break }
                $tag = if ($kind -eq "Err") { "$($Service.Name)!" } else { $Service.Name }
                $color = if ($kind -eq "Err") { "Red" } else { $script:LogColors[$Service.Name] }
                if (-not $color) { $color = "Gray" }
                Write-PlatformMsg $tag $line $color
            }
            $Service.$offsetProp = $fs.Position
        } finally {
            $fs.Close()
        }
    }
}

function Watch-PlatformLogs {
    param(
        [PSCustomObject[]]$Services,
        [scriptblock]$OnTick = $null,
        [int]$PollMs = 400
    )

    Write-PlatformMsg "system" "Streaming logs (Ctrl+C to stop viewing; services keep running)" "Gray"
    Write-Host ""

    try {
        while ($true) {
            foreach ($svc in $Services) {
                if ($svc.Process.HasExited) {
                    Write-PlatformMsg $svc.Name "PROCESS EXITED (code $($svc.Process.ExitCode))" "Red"
                }
                Read-NewLogLines -Service $svc
            }
            if ($OnTick) { & $OnTick }
            Start-Sleep -Milliseconds $PollMs
        }
    } catch [System.Management.Automation.PipelineStoppedException] {
        Write-Host ""
        Write-PlatformMsg "system" "Log streaming stopped." "Yellow"
    }
}

function Get-PlatformAuthToken {
    param(
        [string]$Email = "test@example.com",
        [string]$Password = "test12345"
    )

    $loginBody = @{ email = $Email; password = $Password } | ConvertTo-Json

    try {
        $resp = Invoke-RestMethod -Uri "$ApiBase/auth/login" -Method Post -Body $loginBody -ContentType "application/json" -TimeoutSec 30
        Write-PlatformMsg "task" "Logged in as $Email" "Green"
        return $resp.access_token
    } catch {
        Write-PlatformMsg "task" "Login failed - registering test user..." "Yellow"
        $regBody = @{
            name     = "Test User"
            email    = $Email
            password = $Password
        } | ConvertTo-Json
        try {
            Invoke-RestMethod -Uri "$ApiBase/auth/register" -Method Post -Body $regBody -ContentType "application/json" -TimeoutSec 30 | Out-Null
        } catch {
            if ($_.Exception.Response.StatusCode.value__ -ne 409) { throw }
        }
        $resp = Invoke-RestMethod -Uri "$ApiBase/auth/login" -Method Post -Body $loginBody -ContentType "application/json" -TimeoutSec 30
        Write-PlatformMsg "task" "Registered and logged in as $Email" "Green"
        return $resp.access_token
    }
}

function New-PlatformTask {
    param(
        [string]$Token,
        [string]$Instruction
    )

    $headers = @{ Authorization = "Bearer $Token" }
    $body = @{ instruction = $Instruction } | ConvertTo-Json

    $task = Invoke-RestMethod -Uri "$ApiBase/tasks" -Method Post -Body $body -ContentType "application/json" -Headers $headers -TimeoutSec 30
    Write-PlatformMsg "task" "Created task $($task.id) - status: $($task.status)" "Magenta"
    Write-PlatformMsg "task" "Instruction: $Instruction" "Gray"
    return $task
}

function Get-PlatformTaskStatus {
    param(
        [string]$Token,
        [string]$TaskId
    )

    $headers = @{ Authorization = "Bearer $Token" }
    $task = Invoke-RestMethod -Uri "$ApiBase/tasks/$TaskId" -Method Get -Headers $headers -TimeoutSec 15
    $dag = Invoke-RestMethod -Uri "$ApiBase/tasks/$TaskId/dag" -Method Get -Headers $headers -TimeoutSec 15
    return @{ Task = $task; Dag = $dag }
}

function Show-TaskProgress {
    param(
        [object]$Task,
        [object]$Dag,
        [string]$LastStatus
    )

    $status = $Task.status
    if ($status -ne $LastStatus) {
        Write-PlatformMsg "task" "Task status: $LastStatus -> $status" "Magenta"
    }

    $active = @($Dag.nodes | Where-Object { $_.status -eq "IN_PROGRESS" })
    $queued = @($Dag.nodes | Where-Object { $_.status -eq "QUEUED" })
    $done   = @($Dag.nodes | Where-Object { $_.status -in @("COMPLETED","FALLBACK","DLQ","FAILED") })

    if ($active.Count -gt 0) {
        $names = ($active | ForEach-Object { $_.agent_role }) -join ", "
        Write-PlatformMsg "task" "Active workers: $names" "Yellow"
        foreach ($n in $active) {
            Write-PlatformMsg "task" "  -> $($n.agent_role) ($($n.task_type)) [$($n.status)]" "Yellow"
        }
    } elseif ($queued.Count -gt 0 -and $status -notin @("COMPLETED","FAILED","FALLBACK")) {
        $next = ($queued | Select-Object -First 3 | ForEach-Object { $_.agent_role }) -join ", "
        Write-PlatformMsg "task" "Queued next: $next ($($queued.Count) nodes waiting)" "DarkGray"
    }

    $completed = ($done | ForEach-Object { "$($_.agent_role):$($_.status)" }) -join " | "
    if ($completed) {
        Write-PlatformMsg "task" "DAG progress: $completed" "DarkGray"
    }

    return $status
}

function Monitor-PlatformTask {
    param(
        [string]$Token,
        [string]$TaskId,
        [int]$TimeoutMinutes = 30,
        [PSCustomObject[]]$Services = @()
    )

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $lastStatus = ""
    $terminal = @("COMPLETED", "FAILED", "FALLBACK")

    Write-Host ""
    Write-PlatformMsg "task" "Monitoring task $TaskId ..." "Magenta"
    Write-Host ""

    while ((Get-Date) -lt $deadline) {
        foreach ($svc in $Services) { Read-NewLogLines -Service $svc }

        try {
            $data = Get-PlatformTaskStatus -Token $Token -TaskId $TaskId
            $lastStatus = Show-TaskProgress -Task $data.Task -Dag $data.Dag -LastStatus $lastStatus

            if ($lastStatus -in $terminal) {
                Write-Host ""
                Write-Host "================================================================" -ForegroundColor Green
                Write-PlatformMsg "task" "TASK FINISHED - Status: $lastStatus" "Green"
                Write-Host "================================================================" -ForegroundColor Green

                if ($data.Task.final_output) {
                    Write-Host ""
                    Write-Host "--- FINAL OUTPUT ---" -ForegroundColor Cyan
                    $output = $data.Task.final_output | ConvertTo-Json -Depth 10
                    Write-Host $output
                } else {
                    Write-PlatformMsg "task" "No final_output payload on task record yet." "Yellow"
                }
                return $data.Task
            }
        } catch {
            Write-PlatformMsg "task" "Status poll error: $($_.Exception.Message)" "Red"
        }

        Start-Sleep -Seconds 3
    }

    throw "Task monitoring timed out after $TimeoutMinutes minutes"
}
