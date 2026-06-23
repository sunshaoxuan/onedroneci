@echo off

setlocal enabledelayedexpansion

set "tempFile=%~dp0\ps_output.txt"

powershell "Get-CimInstance -ClassName Win32_Process | Where-Object {$_.Name -eq 'nginx.exe' -and $_.CommandLine -like '*%~dp0*' } | Select-Object -ExpandProperty ProcessId" > "%tempFile%"

set "foundPID="
for /f "usebackq delims=" %%a in ("%tempFile%") do (
    if "!foundPID!"=="" (
        set "foundPID=%%a"
    ) else (
        set "foundPID=!foundPID!,%%a"
    )
)

if exist "%tempFile%" del "%tempFile%"

if defined foundPID (
    echo Found matching process PID: %foundPID%
    for %%p in (%foundPID%) do (
        taskkill /F /PID %%p
        echo Process with PID %%p has been terminated
    )
) else (
    echo No matching processes found
)

endlocal
