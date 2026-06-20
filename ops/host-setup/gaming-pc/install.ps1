# Gaming PC = burst inference node: Ollama (fast MoE chat) + gpu-warden.
# Run in an elevated PowerShell. Idempotent: safe to re-run.
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here

# 1. Config -----------------------------------------------------------------
$cfg = Join-Path $Root "config.env"
if (-not (Test-Path $cfg)) {
  Copy-Item (Join-Path $Root "config.example.env") $cfg
  Write-Host "Created $cfg from the example — edit hosts/models/games if needed."
}
Get-Content $cfg | ForEach-Object {
  if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
    Set-Variable -Name $matches[1] -Value $matches[2] -Scope Script
  }
}

# 2. Ollama + models --------------------------------------------------------
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  Write-Host "Installing Ollama..."
  winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
}
# Serve on the tailnet (Tailscale + Windows Firewall are the access boundary).
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:$($script:GAMING_OLLAMA_PORT)", "User")
$env:OLLAMA_HOST = "0.0.0.0:$($script:GAMING_OLLAMA_PORT)"
Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
Start-Sleep 3
Write-Host "Pulling models (this can take a while)..."
ollama pull $script:GAMING_CHAT_MODEL
# Heavy model is optional; pull only if you want it locally.
# ollama pull $script:GAMING_HEAVY_MODEL

# 3. Warden venv ------------------------------------------------------------
python -m venv (Join-Path $Here ".venv")
& (Join-Path $Here ".venv\Scripts\python.exe") -m pip install -q --upgrade pip
& (Join-Path $Here ".venv\Scripts\pip.exe") install -q -r (Join-Path $Here "requirements.txt")

# 4. Scheduled Task (runs the warden at logon, keeps it up) ------------------
$run = Join-Path $Here "run_warden.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$run`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "yggdrasil-gpu-warden" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "yggdrasil-gpu-warden"
Start-Sleep 2

# 5. Verify -----------------------------------------------------------------
Write-Host "`n== Warden health =="
try { Invoke-RestMethod "http://127.0.0.1:$($script:WARDEN_PORT)/status" | ConvertTo-Json }
catch { Write-Host "(warden not answering yet — check the Scheduled Task 'yggdrasil-gpu-warden')" }
Write-Host "`nDone. From the mini, verify reachability:  curl http://$($script:GAMING_PC_HOST):$($script:WARDEN_PORT)/status"
