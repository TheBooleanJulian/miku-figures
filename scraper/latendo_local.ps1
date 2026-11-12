# Daily Latendo fetch, run from a home connection by Windows Task Scheduler.
#
# Latendo's Cloudflare returns 403 to GitHub Actions' cloud IPs, so this machine
# fetches instead. It commits only scraper/latendo_rows.json and
# scraper/latendo_skip.json straight to main (data commits, like the CI bot's);
# the scheduled CI scrape merges the rows into public/figures.json.
#
# Run it from a dedicated clone of main outside Google Drive (Drive file locks
# break git), e.g. C:\Users\Temp\dev\miku-figures-latendo. Output is appended to
# latendo_local.log in the clone root (*.log is gitignored).

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
Start-Transcript -Path (Join-Path $repo "latendo_local.log") -Append | Out-Null

function Fail($msg) {
    Write-Output "FAILED: $msg"
    Stop-Transcript | Out-Null
    exit 1
}

git checkout --quiet main
if ($LASTEXITCODE -ne 0) { Fail "git checkout main" }
git pull --quiet --rebase origin main
if ($LASTEXITCODE -ne 0) { Fail "git pull" }

$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
python scraper/latendo_scraper.py --fetch
if ($LASTEXITCODE -ne 0) { Fail "latendo_scraper.py --fetch (see log above)" }

git add scraper/latendo_rows.json scraper/latendo_skip.json
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Output "No Latendo changes."
    Stop-Transcript | Out-Null
    exit 0
}

$count = python -c "import json; print(len(json.load(open('scraper/latendo_rows.json', encoding='utf-8'))))"
$stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm 'UTC'")
git commit --quiet -m "chore(data): update Latendo rows ($count) [$stamp]"
if ($LASTEXITCODE -ne 0) { Fail "git commit" }

# The CI bot may have pushed figures.json meanwhile; our files never overlap with its.
$pushed = $false
foreach ($attempt in 1..3) {
    git pull --quiet --rebase origin main
    git push --quiet origin main
    if ($LASTEXITCODE -eq 0) { $pushed = $true; break }
    Start-Sleep -Seconds 10
}
if (-not $pushed) { Fail "git push" }

Write-Output "Pushed $count Latendo rows."
Stop-Transcript | Out-Null
exit 0
