param(
    [string]$ImagePath = "",

    [double]$MinScore = 0.30,

    [ValidateSet("best", "merge")]
    [string]$Mode = "best",

    [switch]$NoClipboardCopy,

    [switch]$NoPrintText
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$toolsDir = $PSScriptRoot
$repoRoot = Split-Path $toolsDir -Parent
$readImageScript = Join-Path $toolsDir "read-image.ps1"

if (-not (Test-Path $readImageScript)) {
    throw "Missing script: $readImageScript"
}

$outDir = Join-Path $repoRoot "logs/clipboard_ocr"
if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$resolvedImagePath = $ImagePath

function Resolve-ClipboardImagePath {
    param(
        [string]$OutPath
    )

    $img = $null
    try {
        $img = Get-Clipboard -Format Image
    }
    catch {
        $img = $null
    }

    if ($null -ne $img) {
        $img.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
        return $OutPath
    }

    return ""
}

if ([string]::IsNullOrWhiteSpace($resolvedImagePath)) {
    $clipboardPng = Join-Path $outDir ("clipboard_" + $timestamp + ".png")
    $resolvedImagePath = Resolve-ClipboardImagePath -OutPath $clipboardPng
}

if ([string]::IsNullOrWhiteSpace($resolvedImagePath)) {
    throw "No image found. Copy an image to clipboard first (Snipping Tool/Print Screen), or pass -ImagePath explicitly."
}

if (-not (Test-Path $resolvedImagePath)) {
    throw "Image path does not exist: $resolvedImagePath"
}

$txtPath = Join-Path $outDir ("ocr_" + $timestamp + ".txt")
$jsonPath = Join-Path $outDir ("ocr_" + $timestamp + ".json")
$latestTxtPath = Join-Path $outDir "latest.txt"
$latestJsonPath = Join-Path $outDir "latest.json"
$latestImagePath = Join-Path $outDir "latest_source.txt"

& $readImageScript `
    -ImagePath $resolvedImagePath `
    -MinScore $MinScore `
    -Mode $Mode `
    -SaveTxt $txtPath `
    -SaveJson $jsonPath | Out-Null

if (Test-Path $txtPath) {
    Copy-Item -Path $txtPath -Destination $latestTxtPath -Force
}
if (Test-Path $jsonPath) {
    Copy-Item -Path $jsonPath -Destination $latestJsonPath -Force
}
"$resolvedImagePath" | Set-Content -Path $latestImagePath -Encoding UTF8

$textPayload = ""
if (Test-Path $txtPath) {
    $textPayload = Get-Content -Path $txtPath -Raw -Encoding UTF8
}

if (-not $NoClipboardCopy -and -not [string]::IsNullOrWhiteSpace($textPayload)) {
    Set-Clipboard -Value $textPayload
}

Write-Output "OCR complete."
Write-Output ("Image: " + $resolvedImagePath)
Write-Output ("Text:  " + $txtPath)
Write-Output ("JSON:  " + $jsonPath)
Write-Output ""

if (-not $NoPrintText) {
    Write-Output "----- OCR TEXT START -----"
    Write-Output $textPayload
    Write-Output "----- OCR TEXT END -----"
}

if (-not $NoClipboardCopy -and -not [string]::IsNullOrWhiteSpace($textPayload)) {
    Write-Output "OCR text copied to clipboard. Paste directly into chat."
}
elseif (-not $NoClipboardCopy) {
    Write-Output "OCR produced no text payload to copy. Check image quality or lower -MinScore."
}
