param(
    [string]$WorkspaceRoot = "",
    [string]$PythonExe = "",
    [string]$DhanClientCode = "",
    [string]$DhanAccessToken = "",
    [int]$WarmupSeconds = 20,
    [int]$SecondWarmupSeconds = 12
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) {
    $WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $PythonExe = Join-Path $WorkspaceRoot ".venv\Scripts\python.exe"
}

if (-not [string]::IsNullOrWhiteSpace($DhanClientCode)) {
    [Environment]::SetEnvironmentVariable("DHAN_CLIENT_CODE", $DhanClientCode, "Process")
}
if (-not [string]::IsNullOrWhiteSpace($DhanAccessToken)) {
    [Environment]::SetEnvironmentVariable("DHAN_ACCESS_TOKEN", $DhanAccessToken, "Process")
}

$runId = Get-Date -Format "yyyyMMdd_HHmmss"
$runDir = Join-Path $WorkspaceRoot "data\analytics\vps_validation\$runId"
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

$results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param(
        [string]$Check,
        [string]$Status,
        [string]$Detail
    )
    $results.Add([PSCustomObject]@{
            check  = $Check
            status = $Status
            detail = $Detail
        }) | Out-Null
}

function Probe-Write {
    param([string]$TargetFolder)

    New-Item -ItemType Directory -Path $TargetFolder -Force | Out-Null
    $probe = Join-Path $TargetFolder "_write_probe_$runId.tmp"
    "probe $runId" | Out-File -FilePath $probe -Encoding utf8
    Remove-Item -Path $probe -Force
}

function Start-Batman {
    param(
        [string]$Tag,
        [int]$WaitSeconds
    )

    $stdout = Join-Path $runDir "main_${Tag}_stdout.log"
    $stderr = Join-Path $runDir "main_${Tag}_stderr.log"

    $proc = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList "main.py" `
        -WorkingDirectory $WorkspaceRoot `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru

    Start-Sleep -Seconds $WaitSeconds

    return [PSCustomObject]@{
        process = $proc
        stdout  = $stdout
        stderr  = $stderr
    }
}

function Stop-Batman {
    param($Proc)

    if ($null -eq $Proc) {
        return
    }

    if (-not $Proc.HasExited) {
        Stop-Process -Id $Proc.Id -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }

    if (-not $Proc.HasExited) {
        Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue
    }
}

$first = $null
$second = $null

try {
    Add-Result -Check "preflight.workspace" -Status "PASS" -Detail "Workspace: $WorkspaceRoot"

    if (-not (Test-Path (Join-Path $WorkspaceRoot "main.py"))) {
        throw "main.py not found in workspace root"
    }
    Add-Result -Check "preflight.main_py" -Status "PASS" -Detail "main.py exists"

    if (-not (Test-Path $PythonExe)) {
        throw "Python executable not found: $PythonExe"
    }
    Add-Result -Check "preflight.python" -Status "PASS" -Detail "Python found: $PythonExe"

    $settingsPath = Join-Path $WorkspaceRoot "config\settings.json"
    $settingsRaw = Get-Content -Path $settingsPath -Raw -Encoding UTF8
    $placeholderMatches = [regex]::Matches($settingsRaw, "\$\{([A-Z0-9_]+)\}")
    $requiredVars = @($placeholderMatches | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)

    $missingVars = New-Object System.Collections.Generic.List[string]
    foreach ($varName in $requiredVars) {
        $value = [Environment]::GetEnvironmentVariable($varName)
        if ([string]::IsNullOrWhiteSpace($value)) {
            $missingVars.Add($varName) | Out-Null
        }
    }

    if ($missingVars.Count -gt 0) {
        $missingText = ($missingVars | Sort-Object) -join ", "
        Add-Result -Check "preflight.env_placeholders" -Status "FAIL" -Detail "Missing required env vars for config placeholders: $missingText"
        throw "Config placeholder env vars are missing"
    }

    Add-Result -Check "preflight.env_placeholders" -Status "PASS" -Detail "All config placeholder env vars are available"

    Probe-Write -TargetFolder (Join-Path $WorkspaceRoot "logs\runtime")
    Add-Result -Check "permissions.logs_runtime" -Status "PASS" -Detail "Writable"

    Probe-Write -TargetFolder (Join-Path $WorkspaceRoot "data\analytics\incidents")
    Add-Result -Check "permissions.incidents" -Status "PASS" -Detail "Writable"

    Probe-Write -TargetFolder (Join-Path $WorkspaceRoot "data\deployments")
    Add-Result -Check "permissions.deployments" -Status "PASS" -Detail "Writable"

    $first = Start-Batman -Tag "first" -WaitSeconds $WarmupSeconds

    if ($first.process.HasExited) {
        Add-Result -Check "startup.first" -Status "FAIL" -Detail "Exited early with code $($first.process.ExitCode). See $($first.stderr)"
        throw "First startup failed"
    }
    Add-Result -Check "startup.first" -Status "PASS" -Detail "Process alive after $WarmupSeconds seconds"

    $today = Get-Date
    $dayPath = Join-Path $WorkspaceRoot ("logs\runtime\{0}\{1}\logs" -f $today.ToString("yyyy-MM"), $today.ToString("yyyy-MM-dd"))
    $runtimeLogs = @()
    $moduleLogs = @()
    if (Test-Path $dayPath) {
        $runtimeLogs = @(Get-ChildItem -Path $dayPath -Filter "runtime_*.log" -ErrorAction SilentlyContinue)
        $moduleLogs = @(Get-ChildItem -Path $dayPath -Filter "*_*.log" -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike "runtime_*" })
    }

    if ($runtimeLogs.Count -gt 0) {
        Add-Result -Check "logging.runtime_files" -Status "PASS" -Detail "$($runtimeLogs.Count) runtime files under $dayPath"
    }
    else {
        Add-Result -Check "logging.runtime_files" -Status "FAIL" -Detail "No runtime_*.log files found under $dayPath"
    }

    if ($moduleLogs.Count -gt 0) {
        Add-Result -Check "logging.module_files" -Status "PASS" -Detail "$($moduleLogs.Count) module files under $dayPath"
    }
    else {
        Add-Result -Check "logging.module_files" -Status "FAIL" -Detail "No module log files found under $dayPath"
    }

    $bytesBefore = 0
    if ($runtimeLogs.Count -gt 0) {
        $bytesBefore = ($runtimeLogs | Measure-Object -Property Length -Sum).Sum
    }

    Stop-Batman -Proc $first.process
    Add-Result -Check "shutdown.first" -Status "PASS" -Detail "Stopped first process"

    $second = Start-Batman -Tag "second" -WaitSeconds $SecondWarmupSeconds

    if ($second.process.HasExited) {
        Add-Result -Check "startup.second" -Status "FAIL" -Detail "Exited early with code $($second.process.ExitCode). See $($second.stderr)"
        throw "Second startup failed"
    }
    Add-Result -Check "startup.second" -Status "PASS" -Detail "Process alive after restart"

    $runtimeLogsAfter = @()
    if (Test-Path $dayPath) {
        $runtimeLogsAfter = @(Get-ChildItem -Path $dayPath -Filter "runtime_*.log" -ErrorAction SilentlyContinue)
    }
    $bytesAfter = 0
    if ($runtimeLogsAfter.Count -gt 0) {
        $bytesAfter = ($runtimeLogsAfter | Measure-Object -Property Length -Sum).Sum
    }

    if ($bytesAfter -ge $bytesBefore) {
        Add-Result -Check "restart.logging_growth" -Status "PASS" -Detail "Runtime log bytes before=$bytesBefore after=$bytesAfter"
    }
    else {
        Add-Result -Check "restart.logging_growth" -Status "FAIL" -Detail "Runtime log bytes shrank before=$bytesBefore after=$bytesAfter"
    }

    $incidentCsv = Join-Path $WorkspaceRoot ("data\analytics\incidents\incident_ledger_{0}.csv" -f $today.ToString("yyyyMMdd"))
    $incidentXlsx = Join-Path $WorkspaceRoot ("data\analytics\incidents\incident_ledger_{0}.xlsx" -f $today.ToString("yyyyMMdd"))
    $incidentStream = Join-Path $WorkspaceRoot ("data\analytics\incidents\incident_ledger_{0}.log" -f $today.ToString("yyyyMMdd"))

    $incidentExists = (Test-Path $incidentCsv) -or (Test-Path $incidentXlsx) -or (Test-Path $incidentStream)
    if ($incidentExists) {
        Add-Result -Check "incidents.artifacts" -Status "PASS" -Detail "Found one or more incident artifacts for today"
    }
    else {
        Add-Result -Check "incidents.artifacts" -Status "WARN" -Detail "No incident artifacts yet (expected unless incidents or suppressions were emitted)"
    }

    Stop-Batman -Proc $second.process
    Add-Result -Check "shutdown.second" -Status "PASS" -Detail "Stopped second process"
}
catch {
    Add-Result -Check "runner.exception" -Status "FAIL" -Detail $_.Exception.Message
}
finally {
    if ($null -ne $first -and $null -ne $first.process) {
        Stop-Batman -Proc $first.process
    }
    if ($null -ne $second -and $null -ne $second.process) {
        Stop-Batman -Proc $second.process
    }
}

$reportJson = Join-Path $runDir "report.json"
$reportTxt = Join-Path $runDir "report.txt"

$results | ConvertTo-Json -Depth 4 | Out-File -FilePath $reportJson -Encoding utf8
$results | Format-Table -AutoSize | Out-String | Out-File -FilePath $reportTxt -Encoding utf8

$failCount = @($results | Where-Object { $_.status -eq "FAIL" }).Count
$warnCount = @($results | Where-Object { $_.status -eq "WARN" }).Count
$passCount = @($results | Where-Object { $_.status -eq "PASS" }).Count

Write-Host ""
Write-Host "Batman Windows VPS smoke report"
Write-Host "Run folder: $runDir"
Write-Host "PASS=$passCount WARN=$warnCount FAIL=$failCount"
Write-Host "Report JSON: $reportJson"
Write-Host "Report TXT : $reportTxt"
Write-Host ""

if ($failCount -gt 0) {
    exit 1
}

exit 0
