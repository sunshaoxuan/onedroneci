param(
    [string]$ServiceName = "OHRStandaloneConsole",
    [int]$Port = 8091,
    [string]$HostAddress = "0.0.0.0",
    [string]$NssmExe = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Resolve-Nssm {
    param([string]$ExplicitPath)
    if ($ExplicitPath -and (Test-Path -LiteralPath $ExplicitPath)) {
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }
    $Command = Get-Command "nssm.exe" -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }
    $LocalCandidates = @(
        (Join-Path $RepoRoot ".standalone-template\nssm\nssm.exe"),
        (Join-Path $RepoRoot "tools\nssm\nssm.exe")
    )
    foreach ($Candidate in $LocalCandidates) {
        if (Test-Path -LiteralPath $Candidate) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }
    $TemplateZip = Join-Path $RepoRoot ".standalone-template\OneHrStandalone.zip"
    if (Test-Path -LiteralPath $TemplateZip) {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $ToolsDir = Join-Path $RepoRoot ".standalone-template\nssm"
        New-Item -ItemType Directory -Path $ToolsDir -Force | Out-Null
        $OuterZip = [System.IO.Compression.ZipFile]::OpenRead($TemplateZip)
        try {
            $NssmEntry = $OuterZip.Entries | Where-Object { $_.FullName -match '(^|/)nssm\.zip$' } | Select-Object -First 1
            if ($NssmEntry) {
                $NestedZip = Join-Path $ToolsDir "nssm.zip"
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($NssmEntry, $NestedZip, $true)
                Expand-Archive -LiteralPath $NestedZip -DestinationPath $ToolsDir -Force
                $Extracted = Get-ChildItem -LiteralPath $ToolsDir -Recurse -Filter "nssm.exe" | Select-Object -First 1
                if ($Extracted) {
                    return $Extracted.FullName
                }
            }
        } finally {
            $OuterZip.Dispose()
        }
    }
    throw "nssm.exe was not found. Put nssm.exe under .standalone-template\nssm or add it to PATH, then rerun this script."
}

function Resolve-Python {
    $Candidates = @(
        (Join-Path $RepoRoot ".venv\Scripts\python.exe"),
        (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        "python"
    )
    foreach ($Candidate in $Candidates) {
        try {
            $Command = Get-Command $Candidate -ErrorAction Stop
            return $Command.Source
        } catch {
            if (Test-Path -LiteralPath $Candidate) {
                return (Resolve-Path -LiteralPath $Candidate).Path
            }
        }
    }
    throw "Python runtime was not found."
}

$Nssm = Resolve-Nssm -ExplicitPath $NssmExe
$Python = Resolve-Python
$PowerShell = (Get-Command "powershell.exe" -ErrorAction Stop).Source
$StartScript = Join-Path $RepoRoot "scripts\start_host_standalone_console.ps1"
$Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$StartScript`" -Port $Port -HostAddress $HostAddress -PythonExe `"$Python`""

$Existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($Existing) {
    & $Nssm stop $ServiceName | Out-Null
    & $Nssm remove $ServiceName confirm | Out-Null
}

& $Nssm install $ServiceName $PowerShell $Arguments | Out-Null
& $Nssm set $ServiceName AppDirectory $RepoRoot | Out-Null
& $Nssm set $ServiceName AppStdout (Join-Path $RepoRoot "dist\standalone-console-service.out.log") | Out-Null
& $Nssm set $ServiceName AppStderr (Join-Path $RepoRoot "dist\standalone-console-service.err.log") | Out-Null
& $Nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $Nssm set $ServiceName AppThrottle 1500 | Out-Null
& $Nssm start $ServiceName | Out-Null

Write-Host "$ServiceName installed and started on $HostAddress`:$Port."
