# Launch wrapper for gpu-warden. Loads config.env, exports warden settings, and
# runs uvicorn from the local venv. Referenced by the Scheduled Task.
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here

# Parse the shared config.env (KEY=VALUE lines) into process env vars.
$cfg = Join-Path $Root "config.env"
if (Test-Path $cfg) {
  Get-Content $cfg | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
      [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
    }
  }
}

$port = if ($env:WARDEN_PORT) { $env:WARDEN_PORT } else { "9090" }
& (Join-Path $Here ".venv\Scripts\uvicorn.exe") gpu_warden:app `
  --app-dir $Here --host 0.0.0.0 --port $port
