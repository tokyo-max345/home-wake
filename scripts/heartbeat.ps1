# Desktop heartbeat for home-wake. Runs every 5 minutes as scheduled task "home-wake-heartbeat" (S4U, user info).
# 1) repo variable DESKTOP_LAST_SEEN = now (unix seconds)  -> watch.yml decides UP/DOWN from its age
# 2) if the home public IPv4 changed, update secret HOME_HOST so the wake packet still reaches the router
# ASCII only (PowerShell 5.1 reads BOM-less files as ANSI).
$ErrorActionPreference = 'Stop'
$repo = 'tokyo-max345/home-wake'
$gh = 'C:\Tools\gh\bin\gh.exe'
$dir = Join-Path $env:USERPROFILE 'jobs\home-wake'
$log = Join-Path $dir 'heartbeat.log'
$ipFile = Join-Path $dir 'public-ip.txt'
New-Item -ItemType Directory -Force $dir | Out-Null
function Log($m) { Add-Content -Path $log -Value ("{0:s} {1}" -f (Get-Date), $m) }
if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) { Move-Item $log "$log.old" -Force }

try {
  $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  $out = & $gh variable set DESKTOP_LAST_SEEN --body "$now" -R $repo 2>&1
  if ($LASTEXITCODE -ne 0) { throw "variable set failed: $out" }
} catch { Log "ERROR heartbeat: $_"; exit 1 }

# 3) outreach-engine (sales mail robot) send health -> repo variable OUTREACH_SEEN (added 2026-10-16)
#    "<unix now>|<last sent unix or 0>|<stalled 0/1>|<sent today>|<live drafts>"
#    Not updated when the crawler is unreachable, so its age grows and watch.py reports it.
#    Windows can be alive while WSL / docker / the robot is dead; the heartbeat above cannot see that.
try {
  $h = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health/sends' -TimeoutSec 15
  if (-not $h.ok) { throw "health/sends not ok" }
  $s = $h.sends
  $last = 0
  if ($s.last_sent_at) { $last = [DateTimeOffset]::Parse($s.last_sent_at).ToUnixTimeSeconds() }
  $stalled = if ($s.stalled) { 1 } else { 0 }
  $now2 = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  $val = "$now2|$last|$stalled|$([int]$s.sent_today)|$([int]$s.live_drafts)"
  $out = & $gh variable set OUTREACH_SEEN --body $val -R $repo 2>&1
  if ($LASTEXITCODE -ne 0) { throw "variable set failed: $out" }
} catch { Log "ERROR outreach: $_" }

try {
  $ip = (Invoke-WebRequest -UseBasicParsing https://api.ipify.org -TimeoutSec 15).Content.Trim()
  if ($ip -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { throw "unexpected ip response: $ip" }
  $old = if (Test-Path $ipFile) { (Get-Content $ipFile -Raw).Trim() } else { '' }
  if ($ip -ne $old) {
    $out = & $gh secret set HOME_HOST --body $ip -R $repo 2>&1
    if ($LASTEXITCODE -ne 0) { throw "secret set failed: $out" }
    Set-Content -Path $ipFile -Value $ip
    Log "public ip changed -> HOME_HOST updated"
  }
} catch { Log "ERROR ip: $_"; exit 2 }
exit 0
