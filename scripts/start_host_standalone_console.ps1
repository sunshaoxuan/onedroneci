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

foreach ($EnvFileName in @("git-access.env", "vm-access.env")) {
    $EnvFile = Join-Path $RepoRoot $EnvFileName
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        continue
    }
    foreach ($RawLine in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
        $Line = $RawLine.Trim()
        if (-not $Line -or $Line.StartsWith("#") -or -not $Line.Contains("=")) {
            continue
        }
        $Key, $Value = $Line.Split("=", 2)
        $Key = $Key.Trim()
        $Value = $Value.Trim()
        if ($Value.Length -ge 2 -and (($Value.StartsWith('"') -and $Value.EndsWith('"')) -or ($Value.StartsWith("'") -and $Value.EndsWith("'")))) {
            $Value = $Value.Substring(1, $Value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($Key, $Value, "Process")
    }
}

Set-Location -LiteralPath $RepoRoot
& $PythonExe (Join-Path $RepoRoot "host_standalone_console.py")
