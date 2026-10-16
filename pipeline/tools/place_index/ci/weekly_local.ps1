# The fallback for the weekly place-index refresh (docs/place-search-2026-10.md §8).
#
# Runs the SAME command as the public repository's workflow (python -m tools.place_index.weekly), but only
# when the cloud run has not published for 8 days - so registering it once is enough and it never doubles
# a release. Register it (once, as yourself; it runs Tuesdays 03:30 when the machine is on):
#
#   schtasks /Create /TN "RouteMind place index" /SC WEEKLY /D TUE /ST 03:30 /F /TR "powershell -NoProfile -ExecutionPolicy Bypass -File G:\grad_all\maps-mobile-application\cairoWay\tools\place_index\ci\weekly_local.ps1"
#
# Needs: Python with tools/place_index/requirements.txt installed, and PLACES_PUBLISH_TOKEN in the user
# environment (it is read from there, never written). Work data goes to G: (multi-GB while it runs) and
# is deleted afterwards; the log is G:\grad_all\.p5work\places-weekly\weekly.log.
$ErrorActionPreference = "Continue"
$repo = "ibrahim212-wq/routemind-places"
$app = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$work = "G:\grad_all\.p5work\places-weekly"
New-Item -ItemType Directory -Force $work | Out-Null
$logFile = Join-Path $work "weekly.log"

function Write-Log($msg) { Add-Content -Path $logFile -Value ("{0:u} {1}" -f (Get-Date), $msg) }

try {
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/latest" -Headers @{ "User-Agent" = "routemind-weekly" } -TimeoutSec 60
    $age = (Get-Date) - [datetime]$rel.published_at
    if ($age.TotalDays -lt 8) {
        Write-Log ("latest release {0} is {1:N1} days old - the cloud run is healthy, nothing to do" -f $rel.tag_name, $age.TotalDays)
        exit 0
    }
    Write-Log ("latest release {0} is {1:N1} days old - building here" -f $rel.tag_name, $age.TotalDays)
} catch {
    Write-Log "could not read the latest release ($($_.Exception.Message)) - building here"
}

if (-not $env:PLACES_PUBLISH_TOKEN) {
    $env:PLACES_PUBLISH_TOKEN = [Environment]::GetEnvironmentVariable("PLACES_PUBLISH_TOKEN", "User")
}
if (-not $env:PLACES_PUBLISH_TOKEN) { Write-Log "PLACES_PUBLISH_TOKEN is not set - stopping"; exit 2 }

Set-Location $app
python -m tools.place_index.weekly --work $work --repo $repo --publish --keep 3 *>> $logFile
$code = $LASTEXITCODE
Write-Log "weekly exited $code"
Remove-Item -Recurse -Force (Join-Path $work "data") -ErrorAction SilentlyContinue
exit $code
