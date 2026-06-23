@echo off
setlocal
set "FOLDER="

for /d %%D in (ohr-cicd\conf_*) do (
    if not defined FOLDER (
        set "FOLDER=%%D"
    )
)

if defined FOLDER (
    nginx.exe -c %~dp0%FOLDER%\nginx.conf
) else (
    echo "Can't found folder like conf_* "
)

endlocal