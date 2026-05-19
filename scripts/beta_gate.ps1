param(
  [switch]$RequireHarness = $false
)

$ErrorActionPreference = "Stop"

$ROOT = Split-Path -Parent $PSScriptRoot
$BACKEND = Join-Path $ROOT "HR APP BACKEND"
$FRONTEND = Join-Path $ROOT "HR APP FRONTEND"

function Run-Step {
  param(
    [string]$Name,
    [scriptblock]$Block
  )
  Write-Host ""
  Write-Host "==> $Name" -ForegroundColor Cyan
  & $Block
}

function Latest-LinkedReport {
  $dir = Join-Path $FRONTEND "e2e_artifacts"
  if (!(Test-Path $dir)) { return $null }
  return Get-ChildItem -Path $dir -Recurse -Filter "qa_linked_realtime_report.json" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
}

$summary = [ordered]@{
  backend_compile = $false
  frontend_build = $false
  connectivity_probe = $false
  linked_e2e = $false
  harness_ready = $null
  linked_report = ""
}

Run-Step "Backend compile checks" {
  Push-Location $BACKEND
  try {
    python -m py_compile app\config.py app\main.py app\routers\candidate_portal.py app\routers\quiz.py app\routers\jd.py app\services\file_service.py
    $summary.backend_compile = $true
  } finally {
    Pop-Location
  }
}

Run-Step "Frontend production build" {
  Push-Location $FRONTEND
  try {
    npm.cmd run build
    $summary.frontend_build = $true
  } finally {
    Pop-Location
  }
}

Run-Step "Backend/frontend connectivity probe" {
  Push-Location $BACKEND
  try {
    $probeOut = python .\scratch\probe_frontend_backend_connectivity.py
    $probe = $probeOut | ConvertFrom-Json
    if ($probe.health_status -eq 200 -and $probe.openapi_status -eq 200) {
      $summary.connectivity_probe = $true
    }
  } finally {
    Pop-Location
  }
}

Run-Step "Linked recruiter-candidate E2E runtime" {
  Push-Location $FRONTEND
  try {
    node .\qa_linked_realtime_e2e.mjs | Out-Host
    $latest = Latest-LinkedReport
    if ($latest) {
      $summary.linked_report = $latest.FullName
      $json = Get-Content -Path $latest.FullName -Raw | ConvertFrom-Json
      if ($json.pass -eq $true) {
        $summary.linked_e2e = $true
      }
    }
  } finally {
    Pop-Location
  }
}

if ($RequireHarness) {
  Run-Step "Harness production readiness check (required)" {
    Push-Location $BACKEND
    try {
      $hOut = python .\scratch\validate_harness_production_readiness.py
      $h = $hOut | ConvertFrom-Json
      $summary.harness_ready = ($h.summary.checks_fail_like -eq 0)
    } finally {
      Pop-Location
    }
  }
} else {
  $summary.harness_ready = "not_required_for_beta"
}

Write-Host ""
Write-Host "===== BETA GATE SUMMARY =====" -ForegroundColor Yellow
$summary.GetEnumerator() | ForEach-Object { Write-Host ("{0}: {1}" -f $_.Key, $_.Value) }

$hardFail = -not ($summary.backend_compile -and $summary.frontend_build -and $summary.connectivity_probe -and $summary.linked_e2e)
if ($hardFail) {
  Write-Error "Beta gate FAILED."
  exit 1
}
if ($RequireHarness -and ($summary.harness_ready -ne $true)) {
  Write-Error "Beta gate FAILED (Harness required but not ready)."
  exit 1
}

Write-Host "Beta gate PASSED." -ForegroundColor Green
exit 0
