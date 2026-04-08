# Example 06 (PowerShell sibling) — CLI walkthrough for the v0.0.5
# `--type ingest` subcommand on native Windows.
#
# This is the PowerShell port of `06_cli_walkthrough.sh` for users who
# want to run the walkthrough on Windows without installing WSL or
# Git Bash. The Python CLI itself is platform-agnostic — only the
# shell wrapper differs.
#
# Prerequisites:
#   pip install 'bankstatementparser[hybrid-vision]'
#   python examples\hybrid\generate_sample_pdfs.py
#
# Optional (only required for the live LLM commands):
#   ollama serve
#   ollama pull llama3
#   ollama pull llava
#
# Run the whole walkthrough:
#   pwsh examples\hybrid\06_cli_walkthrough.ps1
#
# Tested with PowerShell 7.x on Windows 11. Should also work on
# PowerShell Core 6.x and on macOS/Linux PowerShell installs.

$ErrorActionPreference = 'Stop'

$ExampleDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot    = Resolve-Path (Join-Path $ExampleDir '..\..')
$SampleDir   = Join-Path $ExampleDir 'sample_data'
$DigitalPdf  = Join-Path $SampleDir  'digital.pdf'
$ScannedPdf  = Join-Path $SampleDir  'scanned.pdf'
$CamtFixture = Join-Path $RepoRoot   'tests\test_data\camt.053.001.02.xml'

Set-Location $RepoRoot

function Banner($Title) {
    Write-Host ''
    Write-Host '========================================================'
    Write-Host $Title
    Write-Host '========================================================'
}

Banner '1) Path A — Deterministic CAMT.053 (free, fastest)'
Write-Host 'Command:'
Write-Host "  bankstatementparser --type ingest --input $($CamtFixture.Substring($RepoRoot.Path.Length + 1))"
Write-Host ''
try {
    & bankstatementparser --type ingest --input $CamtFixture
} catch {
    Write-Warning $_
}

Banner '2) Path B — Text-LLM on a digital PDF'
if (-not $env:BSP_HYBRID_MODEL) {
    Write-Host 'Skipped: set $env:BSP_HYBRID_MODEL = "ollama/llama3" (and run `ollama serve`)'
    Write-Host 'to call a real model. Without it, the CLI cannot fall through to'
    Write-Host 'the live LLM path. The mock-mode example is in 02_smart_ingest_text_llm.py.'
} else {
    if (-not (Test-Path $DigitalPdf)) {
        Write-Host 'Generating sample PDFs first...'
        & python (Join-Path $ExampleDir 'generate_sample_pdfs.py')
    }
    Write-Host 'Command:'
    Write-Host "  bankstatementparser --type ingest --input $($DigitalPdf.Substring($RepoRoot.Path.Length + 1))"
    Write-Host ''
    & bankstatementparser --type ingest --input $DigitalPdf
}

Banner '3) Path C — Vision-LLM on a scanned PDF'
if (-not $env:BSP_HYBRID_VISION_MODEL) {
    Write-Host 'Skipped: set $env:BSP_HYBRID_VISION_MODEL = "ollama/llava" (and run `ollama serve`)'
    Write-Host 'to call a real multimodal model. Without it, the CLI raises a'
    Write-Host 'VisionExtractorError telling you exactly what to set.'
    Write-Host ''
    Write-Host 'You can still observe the error path:'
    Write-Host "  bankstatementparser --type ingest --input $($ScannedPdf.Substring($RepoRoot.Path.Length + 1))"
    Write-Host '  -> Error: Vision model required for processing. Set BSP_HYBRID_VISION_MODEL...'
} else {
    if (-not (Test-Path $ScannedPdf)) {
        Write-Host 'Generating sample PDFs first...'
        & python (Join-Path $ExampleDir 'generate_sample_pdfs.py')
    }
    Write-Host 'Command:'
    Write-Host "  bankstatementparser --type ingest --input $($ScannedPdf.Substring($RepoRoot.Path.Length + 1))"
    Write-Host ''
    & bankstatementparser --type ingest --input $ScannedPdf
}

Banner '4) Write the unified ledger straight to CSV'
$OutCsv = Join-Path $SampleDir 'out.csv'
New-Item -ItemType Directory -Force -Path $SampleDir | Out-Null
Write-Host 'Command:'
Write-Host "  bankstatementparser --type ingest --input <file> --output $($OutCsv.Substring($RepoRoot.Path.Length + 1))"
Write-Host ''
& bankstatementparser --type ingest --input $CamtFixture --output $OutCsv
Write-Host ''
Write-Host 'First 6 rows of the CSV:'
Get-Content $OutCsv -TotalCount 6

Banner 'Done'
Write-Host 'Inspect the columns: transaction_hash, source_method, booking_date,'
Write-Host 'description, amount, currency, reference, confidence.'
Write-Host ''
Write-Host 'All rows can be safely re-imported into a downstream system —'
Write-Host 'the transaction_hash column is the idempotent dedupe key.'
