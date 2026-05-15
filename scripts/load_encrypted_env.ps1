param(
    [Parameter(Mandatory = $true)]
    [string]$Name
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

$plain = & $PythonExe (Join-Path $RepoRoot "scripts\secret_env.py") decrypt $Name
if ($LASTEXITCODE -ne 0) {
    throw "failed to decrypt secret item: $Name"
}

foreach ($line in ($plain -split "`r?`n")) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) {
        continue
    }
    if ($trimmed.StartsWith("export ")) {
        $trimmed = $trimmed.Substring(7).Trim()
    }
    $idx = $trimmed.IndexOf("=")
    if ($idx -lt 1) {
        continue
    }
    $key = $trimmed.Substring(0, $idx).Trim()
    $value = $trimmed.Substring($idx + 1).Trim()
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    [Environment]::SetEnvironmentVariable($key, $value, "Process")
}
