param(
    [int]$Port = 8091,
    [string]$HostAddress = "0.0.0.0",
    [string]$PythonExe = "",
    [switch]$NoKill
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $PythonExe) {
    $Candidates = @(
        (Join-Path $RepoRoot ".venv\Scripts\python.exe"),
        (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        "python"
    )
    foreach ($Candidate in $Candidates) {
        try {
            $Command = Get-Command $Candidate -ErrorAction Stop
            $PythonExe = $Command.Source
            break
        } catch {
            if (Test-Path -LiteralPath $Candidate) {
                $PythonExe = $Candidate
                break
            }
        }
    }
}

if (-not $PythonExe) {
    throw "Python runtime was not found."
}

if (-not $NoKill) {
    $Listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($Listener in $Listeners) {
        $Owner = [int]$Listener.OwningProcess
        if ($Owner -gt 0 -and $Owner -ne $PID) {
            Write-Host "Port $Port is occupied by process $Owner. Stopping it before startup."
            Stop-Process -Id $Owner -Force -ErrorAction Stop
        }
    }
}

$env:HOST_STANDALONE_CONSOLE_HOST = $HostAddress
$env:HOST_STANDALONE_CONSOLE_PORT = [string]$Port
Set-Location -LiteralPath $RepoRoot
& $PythonExe (Join-Path $RepoRoot "host_standalone_console.py")
