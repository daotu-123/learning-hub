@echo off
REM ===================================================================
REM  LearningHub Windows build script (M3-P1-1)
 REM
 REM  Usage: run from anywhere - "build-exe.bat"
 REM
 REM  Output (two exes, identical code, different Windows subsystem):
 REM    ..\exe\LearningHub-Service.exe   GUI     - desktop double-click, no console window
 REM    ..\exe\LearningHubSvc.exe        CONSOLE - for the service, stdout/stderr have somewhere to go
 REM
 REM  Why this script instead of calling PyInstaller directly:
 REM    A distpath written in the .spec file has NO effect (PyInstaller 6 does not
 REM    read that variable; it only injects a read-only DISTPATH). The output
 REM    directory can only be set via --distpath. The old README relied on a manual
 REM    "copy" step to move the artifact into exe\; when that step was skipped,
 REM    exe\ kept a stale build while the build log still showed success. This
 REM    build found exactly that: the artifact in exe\ was from 10-18, two
 REM    milestones behind the code. So the output path is pinned here.
 REM ===================================================================
setlocal enabledelayedexpansion
cd /d %~dp0

echo [1/2] Cleaning previous build output ...
if exist dist rmdir /s /q dist
if exist build\LearningHub rmdir /s /q build\LearningHub

echo [2/2] PyInstaller build (--distpath ..\exe) ...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath ..\exe LearningHub.spec
if errorlevel 1 (
    echo.
    echo [FAILED] PyInstaller returned an error, see the log above.
    exit /b 1
)

echo.
echo [DONE] Artifacts written to ..\exe\ :
dir /b ..\exe\*.exe
exit /b 0
