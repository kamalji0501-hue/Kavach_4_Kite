param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath,

    [double]$MinScore = 0.35,

    [ValidateSet("best", "merge")]
    [string]$Mode = "merge",

    [switch]$Json,

    [string]$SaveTxt = "",

    [string]$SaveJson = ""
)

$scriptPath = Join-Path $PSScriptRoot "read_image_ocr.py"

# Resolve repo-root python venv relative to this tools folder.
$repoRoot = Split-Path $PSScriptRoot -Parent
$pythonExe = Join-Path $repoRoot ".venv/Scripts/python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at $pythonExe"
}

$cmd = @(
    "--image", $ImagePath,
    "--min-score", $MinScore,
    "--mode", $Mode
)

if ($Json) {
    $cmd += "--json"
}
if ($SaveTxt -ne "") {
    $cmd += @("--save-txt", $SaveTxt)
}
if ($SaveJson -ne "") {
    $cmd += @("--save-json", $SaveJson)
}

& $pythonExe $scriptPath @cmd
