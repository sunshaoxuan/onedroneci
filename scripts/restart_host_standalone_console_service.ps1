param(
    [string]$ServiceName = "OHRStandaloneConsole"
)

$ErrorActionPreference = "Stop"
Restart-Service -Name $ServiceName -Force
Write-Host "$ServiceName restarted."
